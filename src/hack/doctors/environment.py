"""The ONLY things a doctor may use for one incident.

Read: traces (OpenTelemetry-shaped), metrics, config + history, chat transcripts, invariant
violations, knob docs. Act: apply_patch, rollback (through the control panel), replay (verify),
escalate. Think: llm() (cost-accounted). Every call is logged as a step. Risky actions pass an
approval gate; in eval the gate auto-approves but records that approval was needed.
The Environment never sees ground truth: replay is a closure the runner builds from memory.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from hack.bench.incidents import load_bundle
from hack.llm import call_llm_ex
from hack.patient.config import KNOB_DOCS, ControlPanel, diff_configs, validate_patch
from hack.patient.otel import to_otel

ReplayFn = Callable[[ControlPanel], dict[str, Any]]
RISKY_KEYS = ("prompt_version", "payment_verify", "auth.key_slot")


class EscalatedError(RuntimeError):
    """Raised when a doctor tries to act after escalating."""


class ApprovalGate:
    def __init__(self, auto_approve: bool = True) -> None:
        self.auto_approve = auto_approve

    @staticmethod
    def is_risky(changed_keys: list[str]) -> bool:
        return any(k in RISKY_KEYS or "payment" in k for k in changed_keys)

    def request(self, action: str, changed_keys: list[str]) -> dict[str, Any]:
        if not self.is_risky(changed_keys):
            return {"required": False, "approved": True}
        return {"required": True, "approved": self.auto_approve, "by": "auto(eval)" if self.auto_approve else None,
                "reason": f"{action} touches {', '.join(k for k in changed_keys if self.is_risky([k]))}"}


class Environment:
    def __init__(self, bundle_dir: Path, replay_fn: ReplayFn, gate: ApprovalGate | None = None) -> None:
        self._bundle = load_bundle(Path(bundle_dir))
        self._replay_fn = replay_fn
        self.gate = gate or ApprovalGate()
        self.incident_id = self._bundle["incident_id"]
        self.panel = ControlPanel.from_snapshot(self._bundle["config"])
        self.initial_config = self.panel.current.to_dict()
        self._otel = [to_otel(s) for s in self._bundle["traces"]]
        self.steps: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []
        self.escalated = False
        self.escalation_report = ""
        self.llm_usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        self._t0 = time.time()

    # ------------------------------ read ------------------------------------
    def read_traces(self, kind: str | None = None, name: str | None = None, errors_only: bool = False,
                    search: str | None = None, chat_id: str | None = None, limit: int | None = 200) -> list[dict[str, Any]]:
        out = []
        for s in self._otel:
            a = s["attributes"]
            if kind and a["najda.kind"] != kind:
                continue
            if name and s["name"] != name and a.get("tool.name") != name:
                continue
            if errors_only and s["status"]["code"] != "ERROR":
                continue
            if chat_id and a["chat.id"] != chat_id:
                continue
            if search and search.lower() not in json.dumps(s, ensure_ascii=False).lower():
                continue
            out.append(s)
        total = len(out)
        out = out if limit is None else out[:limit]
        self._log("read_traces", {"kind": kind, "name": name, "errors_only": errors_only, "search": search,
                                  "chat_id": chat_id, "limit": limit}, {"returned": len(out), "matched": total})
        return out

    def read_metrics(self) -> dict[str, Any]:
        self._log("read_metrics", {}, {})
        return json.loads(json.dumps(self._bundle["metrics"]))

    def read_config(self) -> dict[str, Any]:
        self._log("read_config", {}, {"version": self.panel.version})
        return self.panel.snapshot()

    def read_chats(self) -> list[dict[str, Any]]:
        self._log("read_chats", {}, {"chats": len(self._bundle["chats"])})
        return json.loads(json.dumps(self._bundle["chats"]))

    def read_invariants(self) -> list[dict[str, Any]]:
        self._log("read_invariants", {}, {"violations": len(self._bundle["invariants"])})
        return json.loads(json.dumps(self._bundle["invariants"]))

    @staticmethod
    def describe_knobs() -> dict[str, str]:
        return dict(KNOB_DOCS)

    # ------------------------------ act -------------------------------------
    def apply_patch(self, patch: dict[str, Any], reason: str = "") -> dict[str, Any]:
        self._check_open()
        problem = validate_patch(self.panel.current, patch)
        if problem:
            return self._log("apply_patch", {"patch": patch, "reason": reason}, {"ok": False, "error": problem})
        approval = self.gate.request("apply_patch", list(patch))
        if not approval["approved"]:
            return self._log("apply_patch", {"patch": patch, "reason": reason}, {"ok": False, "error": "not approved"}, approval)
        version = self.panel.apply(patch, reason, "doctor")
        self.actions.append({"type": "patch", "patch": patch, "reason": reason, "version": version})
        return self._log("apply_patch", {"patch": patch, "reason": reason}, {"ok": True, "version": version}, approval)

    def rollback(self, to_version: int, reason: str = "") -> dict[str, Any]:
        self._check_open()
        target = next((v for v in self.panel.history if v.version == to_version), None)
        if target is None:
            return self._log("rollback", {"to_version": to_version}, {"ok": False, "error": "no such version"})
        changed = list(diff_configs(self.panel.current.to_dict(), target.config))
        approval = self.gate.request("rollback", changed)
        if not approval["approved"]:
            return self._log("rollback", {"to_version": to_version}, {"ok": False, "error": "not approved"}, approval)
        version = self.panel.rollback(to_version, "doctor")
        self.actions.append({"type": "rollback", "to_version": to_version, "reason": reason, "version": version,
                             "changed": changed})
        return self._log("rollback", {"to_version": to_version, "reason": reason},
                         {"ok": True, "version": version, "changed": changed}, approval)

    def replay(self) -> dict[str, Any]:
        """Rerun the incident's failed chats with the CURRENT config. Returns pass/fail per chat."""
        result = self._replay_fn(self.panel)
        summary = {"n_pass": result["n_pass"], "n_total": result["n_total"], "all_pass": result["all_pass"],
                   "invariants_ok": result["invariants_ok"], "violations": result["violation_names"]}
        self._log("replay", {"config_version": self.panel.version}, summary)
        return result

    def escalate(self, report: str) -> None:
        self._check_open()
        self.escalated = True
        self.escalation_report = report
        self._log("escalate", {"report": report[:500]}, {"ok": True})

    def llm(self, prompt: str | list[dict], role: str = "big", system: str | None = None,
            max_tokens: int = 4000, purpose: str = "") -> str:
        res = call_llm_ex(prompt, role=role, system=system, max_tokens=max_tokens)
        u = self.llm_usage
        u["calls"] += 1
        u["input_tokens"] += res.input_tokens
        u["output_tokens"] += res.output_tokens
        u["cost_usd"] += res.cost_usd
        self._log("llm", {"role": role, "model": res.model, "purpose": purpose},
                  {"input_tokens": res.input_tokens, "output_tokens": res.output_tokens,
                   "cost_usd": round(res.cost_usd, 6), "cached": res.cached, "priced": res.priced})
        return res.text

    # ------------------------------ internals --------------------------------
    @property
    def wall_s(self) -> float:
        return time.time() - self._t0

    def _check_open(self) -> None:
        if self.escalated:
            raise EscalatedError("incident already escalated to a human")

    def _log(self, action: str, args: dict[str, Any], result: dict[str, Any],
             approval: dict[str, Any] | None = None) -> dict[str, Any]:
        step = {"i": len(self.steps) + 1, "t": round(time.time() - self._t0, 3), "action": action,
                "args": args, "result": result}
        if approval and approval.get("required"):
            step["approval"] = approval
        self.steps.append(step)
        return result
