"""Differential diagnosis: what do FAILING chats do that PASSING chats never do?

Each span is reduced to a signature (tool + status + error class, log severity + message, guard, reply
outcome). A signature's weight is (share of failing chats that show it) - (share of passing chats that
show it): evidence that also appears in passing chats is down-weighted. Signatures seen in failing chats
only are the "grounded" set; a hypothesis must cite at least one grounded span before any patch is tried.

Also: config bisection. Replay the failed chats (scripted brain, free) against older config versions and
binary-search for the first version that fails.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from hack.doctors.environment import Environment


def signature(span: dict[str, Any]) -> str:
    a = span["attributes"]
    kind = a["najda.kind"]
    if kind == "tool":
        code = a.get("http.response.status_code")
        err = _normalise(span["status"]["message"] or "")
        keys = _result_keys(a.get("tool.result", ""))
        return f"tool:{a['tool.name']}:{code if code is not None else 'OK'}" + (f":err={err}" if err else "") + \
            (f":keys={keys}" if keys else "")
    if kind == "log":
        return f"log:{a['log.severity']}:{_normalise(a['log.message'])}"
    if kind == "guard":
        return f"guard:{span['name']}"
    if kind == "reply":
        return f"reply:{a.get('reply.outcome', '')}"
    return f"{kind}:{span['name']}"


def _normalise(text: str) -> str:
    text = re.sub(r"[0-9a-f]{6,}", "#", text.lower())  # ids / hashes
    text = re.sub(r"\d+(\.\d+)?", "#", text)  # numbers (latencies, counts)
    return text.strip()[:80]


def _result_keys(raw: str) -> str:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return ""
    return ",".join(sorted(data)) if isinstance(data, dict) else ""


@dataclass
class Differential:
    failing: list[str]
    passing: list[str]
    rows: list[dict[str, Any]]  # sorted by weight desc
    span_sig: dict[str, str] = field(default_factory=dict)

    @property
    def grounded_signatures(self) -> set[str]:
        return {r["signature"] for r in self.rows if r["n_pass"] == 0 and r["n_fail"] > 0}

    def is_grounded(self, span_ids: list[str]) -> bool:
        """At least one cited span carries a signature seen in failing chats only. With no passing chats
        to compare against, any real span id counts."""
        grounded = self.grounded_signatures
        cited = {m for text in span_ids for m in re.findall(r"s\d{5}", text)}
        return any(self.span_sig.get(s) in grounded for s in cited)

    def digest(self, top: int = 20) -> str:
        if not self.failing:
            return "no failing chats"
        lines = [f"failing chats: {', '.join(self.failing)}", f"passing chats: {', '.join(self.passing) or '(none)'}",
                 "signature | in failing chats | in passing chats | weight | example span ids"]
        for r in self.rows[:top]:
            lines.append(f"{r['signature']} | {r['n_fail']}/{len(self.failing)} | {r['n_pass']}/{len(self.passing)} | "
                         f"{r['weight']:+.2f} | {', '.join(r['examples'][:3])}")
        return "\n".join(lines)


def differential(env: Environment) -> Differential:
    failing, passing = env.failed_chat_ids(), env.passing_chat_ids()
    fail_set, pass_set = set(failing), set(passing)
    chats_with: dict[str, set[str]] = defaultdict(set)
    examples: dict[str, list[str]] = defaultdict(list)
    span_sig: dict[str, str] = {}
    for s in env.read_traces(limit=None):
        sig = signature(s)
        chat = s["attributes"]["chat.id"]
        span_sig[s["span_id"]] = sig
        chats_with[sig].add(chat)
        if chat in fail_set and len(examples[sig]) < 5:
            examples[sig].append(s["span_id"])
    rows = []
    for sig, chats in chats_with.items():
        n_fail, n_pass = len(chats & fail_set), len(chats & pass_set)
        if n_fail == 0:
            continue
        weight = n_fail / max(len(failing), 1) - (n_pass / len(passing) if passing else 0.0)
        rows.append({"signature": sig, "n_fail": n_fail, "n_pass": n_pass, "weight": round(weight, 3),
                     "examples": examples[sig]})
    rows.sort(key=lambda r: (-r["weight"], -r["n_fail"], r["signature"]))
    return Differential(failing, passing, rows, span_sig)


# ------------------------------ config bisection ---------------------------------

def bisect_config(env: Environment) -> dict[str, Any]:
    """Binary-search the config history for the first version under which the failed chats fail.
    Only versions that existed before the doctor started are candidates (actor != doctor)."""
    history = [v for v in env.panel.history if v.actor != "doctor" and not str(v.reason).startswith("rollback")]
    versions = [v.version for v in history]
    if len(versions) < 2:
        return {"applicable": False, "reason": "config has a single version", "tested": []}
    tested: list[dict[str, Any]] = []

    def passes(version: int) -> bool:
        r = env.replay_at_version(version)
        tested.append({"version": version, "n_pass": r["n_pass"], "n_total": r["n_total"], "all_pass": r["all_pass"]})
        return r["all_pass"]

    if not passes(versions[0]):
        return {"applicable": True, "culprit_version": None, "tested": tested,
                "verdict": f"failed chats also fail under the oldest config v{versions[0]}: the config history "
                           f"did not introduce this failure"}
    lo, hi = 0, len(versions) - 1  # versions[lo] passes
    if passes(versions[hi]):
        return {"applicable": True, "culprit_version": None, "tested": tested,
                "verdict": f"failed chats pass under the current config v{versions[hi]} on replay: the failure "
                           f"was transient or has cleared"}
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if passes(versions[mid]):
            lo = mid
        else:
            hi = mid
    culprit = next(v for v in history if v.version == versions[hi])
    prev = next(v for v in history if v.version == versions[lo])
    changed = {k: {"old": o, "new": n} for k, (o, n) in env.diff_configs(prev.config, culprit.config).items()}
    return {"applicable": True, "culprit_version": culprit.version, "last_good_version": prev.version,
            "changed": changed, "actor": culprit.actor, "reason": culprit.reason, "tested": tested,
            "verdict": f"tested versions {','.join(str(t['version']) for t in tested)} -> v{culprit.version} "
                       f"({culprit.actor}: {culprit.reason}) broke it; it changed {changed}"}
