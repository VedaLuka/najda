"""Najda core loop: INVESTIGATE -> HYPOTHESISE -> FIX -> VERIFY -> (next hypothesis | next fault | ESCALATE).

The LLM investigates and proposes; this controller decides what is allowed and what counts as fixed.
Every component sits behind a flag (diff_diagnosis, guardrails, canary, bisect) for ablations.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from hack.doctors.base import Diagnosis, Doctor, RootCause
from hack.doctors.environment import Environment
from hack.doctors.najda import guardrails, prompts, triage
from hack.doctors.najda.diffdiag import Differential, bisect_config, differential
from hack.doctors.najda.playbooks import Evidence, PlaybookStore, build_evidence
from hack.doctors.najda.report import build_report
from hack.doctors.najda.tools import run_read_tool, tool_names
from hack.doctors.single_llm import _span_line
from hack.doctors.taxonomy import ROOT_CAUSES
from hack.llm import ToolLLMResult
from hack.patient.config import validate_patch

DEFAULTS: dict[str, Any] = {
    "diff_diagnosis": False, "guardrails": False, "canary": False, "bisect": False,
    "structured_money": False, "replay_digest": False,
    "playbooks": False, "triage": False, "tier2_threshold": 0.6, "playbook_tiers": 2, "max_playbook_failures": 2,
    "max_rounds": 3, "max_hypotheses": 4, "max_llm_calls": 14, "max_tool_calls_per_round": 10,
    "max_tokens_total": 150_000, "max_cost_usd": 0.40, "max_knobs_per_patch": 3,
    "min_confidence": 0.2, "canary_fraction": 0.25, "effort": "medium", "max_tokens_per_call": 8000,
    "trace_digest_tokens": 2500,
}
LLMFn = Callable[[list[dict[str, Any]], list[dict[str, Any]], str], ToolLLMResult]


@dataclass
class Hypothesis:
    label: str
    confidence: float
    evidence: list[str]
    rationale: str
    patch: dict[str, Any]
    status: str = "proposed"  # proposed | invalid | ungrounded | low_confidence | no_patch | blocked |
    #                           rolled_back | kept_improvement | verified
    note: str = ""
    source: str = "controller"  # controller | model | playbook

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Replay:
    n_pass: int
    invariants_ok: bool
    progress: int
    per_chat: dict[str, dict[str, Any]] = field(default_factory=dict)
    digest: list[str] = field(default_factory=list)

    @classmethod
    def of(cls, r: dict[str, Any]) -> "Replay":
        return cls(r["n_pass"], r["invariants_ok"], sum(v.get("progress", 0) for v in r["per_chat"].values()),
                   r["per_chat"], list(r.get("error_digest") or []))

    def better_than(self, other: "Replay") -> bool:
        """Damage reduced: more chats pass, or invariants fixed, or chats get further through the flow,
        with no chat passing before and failing now."""
        regressed = any(not v["pass"] and other.per_chat.get(c, {}).get("pass") for c, v in self.per_chat.items())
        if regressed:
            return False
        return (self.n_pass > other.n_pass or (self.invariants_ok and not other.invariants_ok)
                or self.progress > other.progress)


class Najda(Doctor):
    flags: dict[str, Any] = {}

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.cfg = {**DEFAULTS, **self.flags, **self.config}
        self.llm_fn: LLMFn | None = None  # tests inject a scripted fake here

    def treat(self, env: Environment) -> Diagnosis:
        store = self.store() if self.cfg["playbooks"] else None
        return _Run(env, self.cfg, self.llm_fn, store).treat()

    def store(self) -> PlaybookStore:
        """Playbook memory lives in Doctor.memory so the runner's --memory on/off controls it."""
        if "playbooks" not in self.memory:
            self.memory["playbooks"] = PlaybookStore(max_failures=int(self.cfg["max_playbook_failures"]))
        return self.memory["playbooks"]

    def load_memory(self, path: Path) -> None:
        self.memory["playbooks"] = PlaybookStore.load(path)

    def save_memory(self, path: Path) -> None:
        self.store().save(path)


class _Run:
    def __init__(self, env: Environment, cfg: dict[str, Any], llm_fn: LLMFn | None,
                 store: PlaybookStore | None = None) -> None:
        self.env, self.cfg, self.llm_fn, self.store = env, cfg, llm_fn, store
        self.evidence: Evidence | None = None
        self.transient = False
        self.triage: dict[str, Any] | None = None
        self.messages: list[dict[str, Any]] = []
        self.tools = tool_names(bool(cfg["bisect"]))
        self.hypotheses: list[Hypothesis] = []
        self.tried: list[dict[str, Any]] = []
        self.proposal: dict[str, Any] | None = None
        self.escalate_requested: str | None = None
        self.diff: Differential | None = None
        self.bisect: dict[str, Any] | None = None
        self.money: list[str] = []
        self.failed = env.failed_chat_ids()
        self.passing = env.passing_chat_ids()
        self.remaining = list(self.failed)
        self.base_version = env.panel.version
        self.kept_version = self.base_version
        self.best: Replay | None = None
        self.verified: Hypothesis | None = None
        self.budget_hit: str | None = None
        self.n_calls = 0
        self.last_digest: list[str] = []

    # ------------------------------ main --------------------------------------
    def treat(self) -> Diagnosis:
        env, cfg = self.env, self.cfg
        if not self.failed and not env.read_invariants():
            env.record("decision", {"status": "healthy", "reason": "no failed chats and no invariant violations"})
            return Diagnosis([RootCause("no_fault", 0.9, "no failed chats, no invariant violations")],
                             "healthy: nothing to fix")

        baseline = Replay.of(env.replay("failed"))  # free retry: restarted services, later in time
        self.best = baseline
        transient = baseline.n_pass == len(baseline.per_chat) and baseline.invariants_ok
        env.record("baseline_replay", {"n_pass": baseline.n_pass, "n_total": len(baseline.per_chat),
                                        "transient": transient})
        if cfg["guardrails"]:
            self.money = guardrails.money_at_risk_ledger(env) if cfg["structured_money"] else guardrails.money_at_risk(env)
            env.record("money_at_risk", {"evidence": self.money[:5]})
        if cfg["diff_diagnosis"]:
            self.diff = differential(env)
            env.record("differential", {"top": self.diff.rows[:8], "grounded": len(self.diff.grounded_signatures)})
        if cfg["bisect"]:
            self.bisect = bisect_config(env)
            env.record("bisect", self.bisect)
        self.transient = transient
        if self.store is not None and not transient:
            done = self.try_playbooks()
            if done is not None:
                return done
        if cfg["triage"] and not transient:
            self.triage = self.run_triage()

        self.messages = [{"role": "user", "content": self.initial_context(baseline, transient)}]
        for rnd in range(int(cfg["max_rounds"])):
            proposal = self.investigate(rnd)
            if proposal is None:
                break
            hyps = self.validate(proposal)
            if transient:
                return self.finish("recovered", top=hyps[0] if hyps else None, note="transient: retry passed")
            improved = self.try_hypotheses(hyps)
            if self.verified:
                return self.finish("recovered", top=self.verified)
            if improved:
                h = next(h for h in reversed(self.hypotheses) if h.status == "kept_improvement")
                msg = prompts.NEXT_ROUND.format(
                    patch=json.dumps(h.patch), label=h.label, n_pass=self.best.n_pass, n_total=len(self.best.per_chat),
                    remaining=", ".join(self.remaining), tried=[x["patch"] for x in self.tried])
                if cfg["replay_digest"] and self.last_digest:
                    msg += "\n\nFresh evidence from the replay under the kept patch:\n" + "\n".join(self.last_digest)
                self.messages.append({"role": "user", "content": msg})
                continue
            if proposal.get("escalate_recommended") and not any(h.patch for h in hyps):
                break  # the model says a human is needed and has nothing to try
            outcomes = "; ".join(f"{h.label} {h.patch}: {h.status} {h.note}".strip() for h in hyps) or "no hypotheses"
            self.messages.append({"role": "user", "content": prompts.RETRY_ROUND.format(outcomes=outcomes)})
        return self.finish("contained" if self.kept_version != self.base_version else "escalated")

    # ------------------------------ investigate ------------------------------
    def investigate(self, rnd: int) -> dict[str, Any] | None:
        """Tool loop until the model calls propose_hypotheses. None on budget hit or no proposal."""
        env = self.env
        self.proposal = None
        nudged = False
        for _ in range(int(self.cfg["max_tool_calls_per_round"]) + 2):
            limit = self.budget_exceeded()
            if limit:
                self.budget_hit = limit
                env.record("budget_hit", {"limit": limit, "round": rnd})
                return None
            res = self.call()
            self.messages.append({"role": "assistant", "content": res.content})
            env.record("turn", {"round": rnd, "text": res.text[:400], "tools": [u["name"] for u in res.tool_uses],
                                "stop_reason": res.stop_reason})
            if not res.tool_uses:
                if nudged or res.stop_reason not in ("end_turn", "max_tokens"):
                    return None
                nudged = True
                self.messages.append({"role": "user", "content": prompts.NUDGE})
                continue
            results = [{"type": "tool_result", "tool_use_id": u["id"], "content": self.dispatch(u["name"], u["input"])}
                       for u in res.tool_uses]
            self.messages.append({"role": "user", "content": results})
            if self.proposal is not None:
                return self.proposal
        env.record("no_proposal", {"round": rnd})
        return None

    def call(self) -> ToolLLMResult:
        self.n_calls += 1
        if self.llm_fn is not None:
            return self.llm_fn(self.messages, self.tools, prompts.SYSTEM)
        return self.env.llm_tools(self.messages, self.tools, system=prompts.SYSTEM, effort=str(self.cfg["effort"]),
                                 max_tokens=int(self.cfg["max_tokens_per_call"]), purpose="investigate")

    def dispatch(self, name: str, args: dict[str, Any]) -> str:
        env = self.env
        args = args if isinstance(args, dict) else {}
        if name == "propose_hypotheses":
            self.proposal = args
            return "hypotheses received; the controller will verify them in order"
        if name == "bisect_config":
            if self.bisect is None:
                self.bisect = bisect_config(env)
                env.record("bisect", self.bisect)
            return json.dumps(self.bisect, ensure_ascii=False, default=str)
        if name == "apply_patch":
            patch = args.get("patch") or {}
            if not isinstance(patch, dict) or not patch:
                return "error: patch must be a non-empty object"
            if self.cfg["guardrails"]:
                verdict = self.check_patch(patch)
                env.record("guardrail", {"source": "model", "patch": patch, **verdict.to_dict()})
                if not verdict.allowed:
                    return f"refused by guardrail {verdict.rule}: {verdict.reason}"
            r = env.apply_patch(patch, f"najda(model): {args.get('reason', '')}"[:200])
            return json.dumps(r, default=str)
        if name == "rollback":
            r = env.rollback(int(args.get("to_version", self.kept_version)), str(args.get("reason", "najda(model)")))
            return json.dumps(r, default=str)
        if name == "replay":
            r = Replay.of(env.replay("failed"))
            if r.n_pass == len(r.per_chat) and r.invariants_ok and env.panel.version != self.kept_version:
                self.kept_version = env.panel.version
                self.verified = Hypothesis("unknown", 0.5, [], "model-initiated patch verified by replay",
                                           env.panel.history[-1].patch, "verified", source="model")
                self.hypotheses.append(self.verified)
            out = {"n_pass": r.n_pass, "n_total": len(r.per_chat), "invariants_ok": r.invariants_ok,
                   "failing": sorted(c for c, v in r.per_chat.items() if not v["pass"])}
            if self.cfg["replay_digest"]:
                out["error_digest"] = r.digest
            return json.dumps(out, ensure_ascii=False)
        if name == "escalate":
            self.escalate_requested = str(args.get("reason", ""))
            return "escalation recorded; finish with propose_hypotheses so the report has your diagnosis"
        return run_read_tool(env, name, args)

    def check_patch(self, patch: dict[str, Any]) -> guardrails.Verdict:
        fn = guardrails.check_patch_v3 if self.cfg["structured_money"] else guardrails.check_patch
        return fn(self.env, patch, int(self.cfg["max_knobs_per_patch"]), self.money)

    def budget_exceeded(self) -> str | None:
        u = self.env.llm_usage
        if max(u["calls"], self.n_calls) >= int(self.cfg["max_llm_calls"]):
            return f"max_llm_calls={self.cfg['max_llm_calls']}"
        if u["input_tokens"] + u["output_tokens"] >= int(self.cfg["max_tokens_total"]):
            return f"max_tokens_total={self.cfg['max_tokens_total']}"
        if u["cost_usd"] >= float(self.cfg["max_cost_usd"]):
            return f"max_cost_usd={self.cfg['max_cost_usd']}"
        return None

    # ------------------------------ hypothesise ------------------------------
    def validate(self, proposal: dict[str, Any]) -> list[Hypothesis]:
        out: list[Hypothesis] = []
        for raw in proposal.get("hypotheses") or []:
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("root_cause", "unknown"))
            patch = raw.get("patch") if isinstance(raw.get("patch"), dict) else {}
            evidence = [str(s) for s in (raw.get("evidence_span_ids") or [])]
            try:
                conf = min(1.0, max(0.0, float(raw.get("confidence", 0.5))))
            except (TypeError, ValueError):
                conf = 0.5
            h = Hypothesis(label if label in ROOT_CAUSES else "unknown", conf, evidence, str(raw.get("rationale", ""))[:300], patch)
            if patch:
                problem = validate_patch(self.env.panel.current, patch)
                if problem:
                    h.status, h.note = "invalid", problem
                elif self.diff is not None and not (self.diff.is_grounded(evidence) or self.bisect_grounds(patch)):
                    h.status, h.note = "ungrounded", "no cited span is specific to the failing chats"
            out.append(h)
        out.sort(key=lambda h: -h.confidence)
        self.hypotheses.extend(out)
        self.env.record("hypotheses", {"ranked": [h.to_dict() for h in out],
                                       "escalate_recommended": bool(proposal.get("escalate_recommended"))})
        return out

    def bisect_grounds(self, patch: dict[str, Any]) -> bool:
        """A patch that reverts knobs the bisection blamed is grounded by that deterministic replay evidence."""
        if not self.bisect or not self.bisect.get("culprit_version"):
            return False
        return bool(patch) and set(patch) <= set(self.bisect.get("changed", {}))

    # ------------------------------ fix + verify -----------------------------
    def try_hypotheses(self, hyps: list[Hypothesis]) -> bool:
        """Try patches by confidence. Returns True when a patch improved things but did not fix everything
        (multi-fault: go investigate the remaining failures)."""
        for h in [h for h in hyps if h.status == "proposed"][: int(self.cfg["max_hypotheses"])]:
            if not h.patch:
                h.status = "no_patch"
                continue
            if h.confidence < float(self.cfg["min_confidence"]):
                h.status = "low_confidence"
                continue
            self.try_fix(h)
            if h.status == "verified":
                return False
            if h.status == "kept_improvement":
                return True
        return False

    def try_fix(self, h: Hypothesis) -> None:
        env, cfg = self.env, self.cfg
        if cfg["guardrails"]:
            verdict = self.check_patch(h.patch)
            env.record("guardrail", {"source": "controller", "patch": h.patch, **verdict.to_dict()})
            if not verdict.allowed:
                h.status, h.note = "blocked", f"{verdict.rule}: {verdict.reason}"
                self.tried.append({"label": h.label, "patch": h.patch, "outcome": f"blocked ({verdict.rule})"})
                return
        before = env.panel.version
        res = env.apply_patch(h.patch, f"najda: {h.label}: {h.rationale[:120]}")
        if not res.get("ok"):
            h.status, h.note = "invalid", str(res.get("error"))
            return
        assert self.best is not None
        if cfg["canary"] and len(self.remaining) >= 2:
            k = max(1, math.ceil(float(cfg["canary_fraction"]) * len(self.remaining)))
            subset = self.remaining[:k]
            canary = Replay.of(env.replay(subset))
            base_subset = Replay(sum(self.best.per_chat[c]["pass"] for c in subset),
                                 all(self.best.per_chat[c]["invariants_ok"] for c in subset),
                                 sum(self.best.per_chat[c].get("progress", 0) for c in subset),
                                 {c: self.best.per_chat[c] for c in subset})
            ok = canary.better_than(base_subset) or canary.n_pass == k
            env.record("canary", {"chats": subset, "n_pass": canary.n_pass, "passed": ok, "patch": h.patch})
            if not ok:
                self.rollback(h, before, "canary did not improve")
                return
        full = Replay.of(env.replay("failed"))
        all_pass = full.n_pass == len(full.per_chat) and full.invariants_ok
        if not all_pass and not full.better_than(self.best):
            self.rollback(h, before, f"replay {full.n_pass}/{len(full.per_chat)}: no improvement")
            return
        if cfg["guardrails"]:
            reg = guardrails.regression(env, self.passing)
            env.record("regression_check", {"patch": h.patch, **reg})
            if reg["broke"]:
                self.rollback(h, before, f"broke previously passing chats {reg['broke']}")
                return
        self.best, self.kept_version = full, env.panel.version
        self.last_digest = full.digest
        self.remaining = sorted(c for c, v in full.per_chat.items() if not v["pass"])
        h.status = "verified" if all_pass else "kept_improvement"
        h.note = f"replay {full.n_pass}/{len(full.per_chat)}"
        if all_pass:
            self.verified = h
        self.tried.append({"label": h.label, "patch": h.patch, "outcome": f"{h.status} ({h.note})"})
        env.record("verify", {"patch": h.patch, "status": h.status, "n_pass": full.n_pass, "n_total": len(full.per_chat),
                              "remaining": self.remaining})

    def rollback(self, h: Hypothesis, to_version: int, why: str) -> None:
        self.env.rollback(to_version, f"najda: {why}")
        h.status, h.note = "rolled_back", why
        self.tried.append({"label": h.label, "patch": h.patch, "outcome": f"rolled back ({why})"})

    # ------------------------------ playbooks ---------------------------------
    def try_playbooks(self) -> Diagnosis | None:
        """Before any big-model call: match the incident's structured signature against learned playbooks and
        push the matched patches through the SAME guardrails, canary, replay and regression check.
        Returns the final diagnosis when a playbook settled the incident, else None (fall back)."""
        env, cfg, store = self.env, self.cfg, self.store
        assert store is not None
        self.evidence = build_evidence(env, self.bisect, self.money)
        m = store.match(self.evidence, env.panel.current.to_dict(), float(cfg["tier2_threshold"]), int(cfg["playbook_tiers"]))
        if m is None:
            env.record("playbook", {"event": "miss", "key": list(self.evidence.key), "active": len(store.active())})
            return None
        pb = m.playbook
        env.record("playbook", {"event": "match", "id": pb.id, "kind": pb.kind, "tier": m.tier, "score": round(m.score, 3),
                                "label": pb.label, "patches": m.patches, "source_incident": pb.source_incident})
        last: Hypothesis | None = None
        conf = 0.9 if m.tier == 1 else 0.6
        for i, patch in enumerate(m.patches):
            last = Hypothesis(pb.label_of(i), conf, [], f"playbook {pb.id} (tier {m.tier}, score {m.score:.2f})", patch,
                              source="playbook")
            self.hypotheses.append(last)
            self.try_fix(last)
            if last.status != "kept_improvement":
                break
        if pb.kind == "escalate":
            if last is None:  # no containment step: still name the known root cause in the report
                last = Hypothesis(pb.label, conf, [], f"playbook {pb.id}: known must-escalate signature", {}, "no_patch",
                                  source="playbook")
                self.hypotheses.append(last)
            store.record(pb, True)  # an escalation cannot be verified by replay: counted as a use, reported apart
            env.record("playbook", {"event": "hit_escalate", "id": pb.id, "tier": m.tier})
            status = "contained" if self.kept_version != self.base_version else "escalated"
            return self.finish(status, top=last, note=f"playbook {pb.id}: known must-escalate signature")
        if self.verified is not None:
            store.record(pb, True)
            env.record("playbook", {"event": "hit", "id": pb.id, "tier": m.tier, "llm_calls": self.n_calls})
            return self.finish("recovered", top=self.verified, note=f"playbook {pb.id} verified by replay")
        if last is not None and last.status == "kept_improvement":
            pb.uses += 1  # the known fault was real, the incident has more: neither a success nor a failure
            env.record("playbook", {"event": "partial", "id": pb.id, "tier": m.tier, "remaining": self.remaining})
            return None
        store.record(pb, False)
        env.record("playbook", {"event": "false_match", "id": pb.id, "tier": m.tier, "disabled": pb.disabled,
                                "outcome": last.status if last else "no_patch"})
        return None

    def learn(self, status: str) -> None:
        """Learn only from this run's own verified outcome. Never from a transient, an unverified patch, a
        kept-but-partial improvement alone, a model-initiated patch, or a playbook hit (already known)."""
        store, env = self.store, self.env
        assert store is not None
        if self.evidence is None or self.transient:
            return
        chain = [h for h in self.hypotheses if h.status in ("kept_improvement", "verified")]
        if any(h.source != "controller" for h in chain):
            env.record("playbook", {"event": "not_learned", "reason": "fix came from a playbook or a model-initiated patch"})
            return
        if status == "recovered" and self.verified is not None and chain and chain[-1] is self.verified:
            pb = store.learn("fix", self.verified.label, self.evidence, [h.patch for h in chain], env.incident_id,
                             [h.label for h in chain])
        elif status != "recovered" and self.money and not self.budget_hit:
            pb = store.learn("escalate", self.rank_causes(None)[0].label if self.hypotheses else "unknown",
                             self.evidence, [h.patch for h in chain], env.incident_id)
        else:
            env.record("playbook", {"event": "not_learned", "reason": f"status={status}, nothing verified"})
            return
        env.record("playbook", {"event": "learned" if pb else "known", "id": pb.id if pb else None,
                                "kind": pb.kind if pb else None, "steps": pb.steps if pb else None})

    # ------------------------------ triage ------------------------------------
    def run_triage(self) -> dict[str, Any]:
        env = self.env
        transcripts = "\n".join(
            f"[{c['chat_id']} -> {c['outcome']}] " + " | ".join(f"{t['role']}: {t['text'][:160]}" for t in c["transcript"])
            for c in env.read_chats() if c["chat_id"] in self.failed[:3])
        return triage.run_triage(env, self.diff.digest(12) if self.diff else "n/a", self.money, env.config_history_diff(),
                                 transcripts, self.trace_digest(int(self.cfg["trace_digest_tokens"]) * 2))

    # ------------------------------ finish ------------------------------------
    def finish(self, status: str, top: Hypothesis | None = None, note: str = "") -> Diagnosis:
        env = self.env
        if env.panel.version != self.kept_version:  # anything unverified goes back
            env.rollback(self.kept_version, "najda: discard unverified changes before finishing")
        ranked = self.rank_causes(top)
        label = ranked[0].label if ranked else "unknown"
        proposal = self.proposal or {}
        summary = str(proposal.get("summary") or note or "see evidence")
        human = str(proposal.get("recommended_human_action") or proposal.get("escalation_reason")
                    or self.escalate_requested or ("none" if status == "recovered" else "investigate the upstream"))
        evidence = self.evidence_lines(top)
        if self.budget_hit:
            evidence.append(f"budget limit hit: {self.budget_hit}")
        report = build_report(env, status, label, summary, evidence, self.tried, human)
        env.record("decision", {"status": status, "label": label, "kept_version": self.kept_version,
                                "budget_hit": self.budget_hit, "escalate_requested": self.escalate_requested,
                                "cost_usd": round(env.llm_usage["cost_usd"], 4)})
        if status != "recovered":
            env.escalate(report)
        if self.store is not None:
            self.learn(status)
        return Diagnosis(ranked, report)

    def rank_causes(self, top: Hypothesis | None) -> list[RootCause]:
        order = {"verified": 0, "kept_improvement": 1}
        hyps = sorted(self.hypotheses, key=lambda h: (order.get(h.status, 2), -h.confidence))
        if top is not None and top in hyps:
            hyps.remove(top)
            hyps.insert(0, top)
        seen: set[str] = set()
        out: list[RootCause] = []
        for h in hyps:
            if h.label in seen or h.label == "unknown" and out:
                continue
            seen.add(h.label)
            out.append(RootCause(h.label, h.confidence, f"{h.status}: {h.rationale}"[:300]))
        return out

    def evidence_lines(self, top: Hypothesis | None) -> list[str]:
        lines: list[str] = []
        if top is not None and top.evidence:
            lines.append(f"{top.label}: spans {', '.join(top.evidence[:6])}")
        if self.bisect and self.bisect.get("applicable"):
            lines.append(f"bisection: {self.bisect['verdict']}")
        if self.diff is not None:
            lines += [f"failing-only signature: {r['signature']} ({r['n_fail']} chats)" for r in self.diff.rows[:3]
                      if r["n_pass"] == 0]
        if self.money:
            lines.append(f"money at risk: {self.money[0]}")
        return lines

    # ------------------------------ context -----------------------------------
    def initial_context(self, baseline: Replay, transient: bool) -> str:
        env = self.env
        metrics = env.read_metrics()
        per_chat = metrics.pop("per_chat", {})
        parts = [
            f"# Incident {env.incident_id}",
            f"Failing chats: {', '.join(self.failed) or '(none)'}\nPassing chats: {', '.join(self.passing) or '(none)'}",
            "## Metrics\n" + _compact(metrics) + "\nper chat: " + _compact(per_chat),
            "## Invariant violations\n" + (_compact(env.read_invariants()[:12]) or "none"),
            "## Config (current)\n" + _compact(env.read_config()["current"]),
            "## Config change history (old -> new)\n" + (_compact(env.config_history_diff()) or "no changes since v1"),
            "## Baseline replay (failed chats rerun on the CURRENT config, services restarted, 1h later)\n"
            + f"{baseline.n_pass}/{len(baseline.per_chat)} pass, invariants_ok={baseline.invariants_ok}"
            + ("\n=> The failure cleared without any change: it looks transient. Label the root cause and propose "
               "hypotheses with EMPTY patches; do not change config that is not broken." if transient else ""),
        ]
        if self.kept_version != self.base_version:
            parts.append("## Already applied and KEPT before you (a learned playbook improved but did not fix everything)\n"
                         + "; ".join(f"{t['patch']}: {t['outcome']}" for t in self.tried)
                         + f"\nStill failing after it: {', '.join(self.remaining)}. Investigate THOSE chats; there is "
                         "probably a SECOND, independent problem."
                         + ("\nFresh evidence from the replay under the kept patch:\n" + "\n".join(self.last_digest)
                            if self.cfg["replay_digest"] and self.last_digest else ""))
        if self.bisect is not None and self.bisect.get("applicable"):
            parts.append("## Config bisection (deterministic replays against older versions)\n" + self.bisect["verdict"])
        if self.diff is not None:
            parts.append("## Differential: span signatures in failing vs passing chats (weight = failing share - "
                         "passing share; cite the span ids as evidence)\n" + self.diff.digest())
        if self.money:
            parts.append("## Money at risk (payment upstream failing or payments without orders)\n" + "\n".join(self.money[:5]))
        digest_chars = int(self.cfg["trace_digest_tokens"]) * 4
        if self.triage is not None:
            parts.append(f"## Triage brief (cheap model, advisory; class={self.triage['class']}; "
                         f"suspect knobs={self.triage['suspect_knobs']})\n{self.triage['brief']}\n"
                         "(Transcripts omitted: call read_chats if you need them.)")
            digest_chars //= 2
        else:
            parts.append("## Chat transcripts\n" + "\n".join(
                f"[{c['chat_id']} -> {c['outcome']}] " + " | ".join(f"{t['role']}: {t['text']}" for t in c["transcript"])
                for c in env.read_chats()))
        parts.append("## Trace digest (span_id first; errors and warnings, then tool calls)\n"
                     + self.trace_digest(digest_chars))
        parts.append("Investigate with the tools as needed, then call propose_hypotheses.")
        return "\n\n".join(parts)


    def trace_digest(self, char_budget: int) -> str:
        spans = self.env.read_traces(limit=None)
        important = [s for s in spans if s["status"]["code"] == "ERROR" or s["attributes"].get("log.severity") in ("WARN", "ERROR")]
        rest = [s for s in spans if s not in important and s["attributes"]["najda.kind"] in ("tool", "guard")]
        lines, used = [], 0
        for s in important + rest:
            line = f"{s['span_id']} {_span_line(s)}"
            if used + len(line) > char_budget:
                lines.append(f"... {len(important) + len(rest) - len(lines)} more spans omitted (use search_traces)")
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)


def _compact(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
