"""Baseline doctors: oracle (sanity only), do_nothing (floor), restart (B0), runbook (B1)."""
from __future__ import annotations

import json
from typing import Any

from hack.doctors.base import Diagnosis, Doctor, RootCause, register
from hack.doctors.environment import Environment


@register("oracle")
class OracleDoctor(Doctor):
    """Reads the ground truth. Proves the bench + scorer are consistent. Never a real system."""
    needs_truth = True

    def give_truth(self, truth: dict[str, Any]) -> None:
        self.truth = truth

    def treat(self, env: Environment) -> Diagnosis:
        from hack.patients import get_bench  # the oracle is bench sanity: it may see the catalog

        gt = self.truth["ground_truth"]
        labels = get_bench(env.patient.name).fault_labels
        causes = [RootCause(sorted(labels[f])[0], 1.0, gt["root_cause"]) for f in self.truth["resolved_fault_ids"]]
        if gt["correct_fix"]:
            env.apply_patch(gt["correct_fix"], "oracle fix")
        if gt.get("requires_retry"):
            env.replay()
        if gt["should_escalate"]:
            env.escalate(f"oracle: {gt['root_cause']}")
        return Diagnosis(causes, gt["root_cause"])


@register("do_nothing")
class DoNothing(Doctor):
    """The floor: no reading, no action."""

    def treat(self, env: Environment) -> Diagnosis:
        return Diagnosis([], "no action taken")


@register("restart")
class Restart(Doctor):
    """B0 'turn it off and on again': no diagnosis, restart services and retry the failed chats once."""

    def treat(self, env: Environment) -> Diagnosis:
        result = env.replay()  # every replay starts from freshly restarted services and empty caches
        return Diagnosis([], f"restarted services and retried failed chats: {result['n_pass']}/{result['n_total']} passed")


# ---------------------------------------------------------------------------
# B1: a runbook a good on-call engineer would write after seeing the DEV incidents only.
# ---------------------------------------------------------------------------

HEALTHY_MAX_TURNS = 10


@register("runbook")
class Runbook(Doctor):
    def treat(self, env: Environment) -> Diagnosis:
        tools = env.read_traces(kind="tool", limit=None)
        errors = [s for s in tools if s["status"]["code"] == "ERROR"]
        codes = [s["attributes"].get("http.response.status_code") for s in errors]
        config = env.read_config()
        metrics = env.read_metrics()
        violations = env.read_invariants()

        if not errors and not violations and metrics["chats_failed"] == 0 and metrics["loop_chats"] == 0:
            return Diagnosis([RootCause("no_fault", 0.9)], "no errors, no failed chats, no invariant violations")

        # Rules that mean "a human must act": page immediately, change nothing.
        if 401 in codes or 403 in codes:
            return self._page(env, "auth_failure", "401 from upstream: credentials expired/rotated. Paging security on-call.")
        if any(c == 503 for c in codes):
            failing = sorted({s["attributes"]["tool.name"] for s in errors if s["attributes"].get("http.response.status_code") == 503})
            return self._page(env, "upstream_outage", f"503 on {failing}: dependency down. Paging the provider.")

        causes: list[RootCause] = []
        plan: list[tuple[str, Any, str]] = []  # (kind, payload, reason)

        deploy = self._last_deploy(config)
        if deploy is not None:
            changed = list(deploy["patch"])
            label = "bad_prompt_deploy" if "prompt_version" in changed else "agent_loop" if "max_turns" in changed else "bad_prompt_deploy"
            causes.append(RootCause(label, 0.7, f"config v{deploy['version']} by {deploy['actor']}: {deploy['reason']}"))
            plan.append(("rollback", deploy["version"] - 1, f"roll back deploy v{deploy['version']}"))
        if any("unknown or disallowed tool" in (s["status"]["message"] or "") for s in errors):
            causes.append(RootCause("invalid_tool", 0.6, "bot called a tool that does not exist"))
        if 429 in codes:
            causes.append(RootCause("rate_limiting", 0.8, f"{codes.count(429)} tool calls got 429"))
            plan.append(("patch", {"retry.max_retries": 3, "retry.backoff_s": 0.5}, "retry 429s with backoff"))
        if metrics["loop_chats"] > 0 or config["current"]["max_turns"] > HEALTHY_MAX_TURNS:
            causes.append(RootCause("agent_loop", 0.6, f"{metrics['loop_chats']} chats hit the turn cap"))
            plan.append(("patch", {"max_turns": HEALTHY_MAX_TURNS}, "restore the turn guard"))
        mapping = self._field_mapping_fix(tools, config["current"]["field_mappings"], env.patient.api_contract)
        if mapping:
            causes.append(RootCause("schema_change", 0.8, f"response field renamed: {mapping}"))
            plan.append(("patch", mapping, "map renamed response fields"))

        if not plan:
            return self._page(env, "unknown", "no runbook rule matched; paging a human")
        return self._execute(env, causes, plan)

    def _execute(self, env: Environment, causes: list[RootCause], plan: list[tuple[str, Any, str]]) -> Diagnosis:
        start_version = env.read_config()["version"]
        before = env.replay()
        for kind, payload, reason in plan:
            if kind == "rollback":
                env.rollback(payload, reason)
            else:
                env.apply_patch(payload, reason)
        after = env.replay()
        causes = sorted(causes, key=lambda c: -c.confidence)
        if after["all_pass"]:
            return Diagnosis(causes, f"applied {len(plan)} runbook actions; replay passes")
        improved = after["n_pass"] > before["n_pass"] or (after["invariants_ok"] and not before["invariants_ok"])
        if not improved:
            env.rollback(start_version, "runbook actions did not help")
        env.escalate(f"runbook actions {'contained but did not fix' if improved else 'did not help'} the incident; "
                     f"replay {after['n_pass']}/{after['n_total']}")
        return Diagnosis(causes, "escalated after partial or failed fix")

    @staticmethod
    def _page(env: Environment, label: str, report: str) -> Diagnosis:
        env.escalate(report)
        return Diagnosis([RootCause(label, 0.7, report)], report)

    @staticmethod
    def _last_deploy(config: dict[str, Any]) -> dict[str, Any] | None:
        changes = [v for v in config["history"] if v["version"] > 1 and v["actor"] != "doctor"]
        return changes[-1] if changes else None

    @staticmethod
    def _field_mapping_fix(tools: list[dict[str, Any]], mappings: dict[str, str],
                           contract: dict[str, set[str]]) -> dict[str, str]:
        """One documented key missing and one undocumented key present = a renamed response field."""
        patch: dict[str, str] = {}
        for s in tools:
            if s["status"]["code"] == "ERROR":
                continue
            name = s["attributes"]["tool.name"]
            result = json.loads(s["attributes"]["tool.result"])
            if name not in contract or not isinstance(result, dict):
                continue
            missing = contract[name] - set(result)
            extra = set(result) - contract[name] - {"as_of"}
            if len(missing) == 1 and len(extra) == 1:
                physical, new_key = missing.pop(), extra.pop()
                for logical, mapped in mappings.items():
                    if mapped == physical:
                        patch[f"field_mappings.{logical}"] = new_key
        return patch
