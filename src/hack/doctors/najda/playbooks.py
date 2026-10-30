"""Playbooks: Najda's memory of VERIFIED fixes, so the next incident with the same symptoms costs nothing.

A playbook is learned only after a fix passed the full replay plus the regression check (never from an
unverified patch, a kept-but-partial improvement or an escalation; escalate-fast playbooks are the one
exception and are only learned with money-at-risk evidence and only matched exactly).

Signature = structured tokens, no free text and no incident ids:
  failing-only span tokens (tool, status, error class), invariant violation types, bisect result type,
  bisected knobs, money-at-risk flag.
Tier 1 = exact token-set match (deterministic, free). Tier 2 = Jaccard over a wider token bag.

Fix template = the verified patch with values parameterised from evidence where possible:
  {"$bisect_old": knob}         value = the last-good value the bisection found for that knob
  {"$key_for": logical, "tool"} value = the response key observed in that tool's results that best
                                matches the logical field name (schema mapping old -> new)
  {"$status_code": i}           list element = the i-th failing status code
Anything else stays literal. A template that cannot be filled from the new incident does not match.
"""
from __future__ import annotations

import json
import re
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from hack.doctors.environment import Environment
from hack.doctors.najda.diffdiag import _normalise

NOISE_KINDS = ("customer", "llm")  # present in every chat: never evidence
MIN_KEY_SHARE = 0.5  # a token enters the exact key only when at least half the failing chats show it


# ------------------------------ evidence -----------------------------------

@dataclass
class Evidence:
    key: tuple[str, ...]  # tier-1 tokens, sorted
    bag: frozenset[str]  # tier-2 tokens
    status_codes: list[int]  # failing-only error status codes, most common first
    result_keys: dict[str, list[str]]  # tool -> response keys seen in failing chats
    bisect_old: dict[str, Any]  # knob -> last-good value (config bisection culprit)
    money: bool

    def to_dict(self) -> dict[str, Any]:
        return {"key": list(self.key), "bag": sorted(self.bag), "status_codes": self.status_codes,
                "result_keys": self.result_keys, "bisect_old": self.bisect_old, "money": self.money}


def span_tokens(span: dict[str, Any], allowed_tools: list[str]) -> tuple[str | None, list[str]]:
    """(exact-key token or None, extra bag tokens) for one span."""
    a = span["attributes"]
    kind = a["najda.kind"]
    if kind in NOISE_KINDS:
        return None, []
    if kind == "tool":
        name = a["tool.name"] if a["tool.name"] in allowed_tools else "?unlisted"
        code = a.get("http.response.status_code")
        if span["status"]["code"] == "ERROR":
            code_s = "timeout" if code is None else str(code)
            err = _normalise(span["status"]["message"] or "")
            return f"tool:{name}:{code_s}:error", [f"tool:{name}", f"code:{code_s}"] + ([f"err:{err}"] if err else [])
        keys = _result_keys(a.get("tool.result"))
        tok = f"tool:{name}:{code if code is not None else 'OK'}" + (f":keys={','.join(keys)}" if keys else "")
        return tok, [f"tool:{name}"]
    if kind == "log":
        sev = a["log.severity"]
        msg = _normalise(a["log.message"])
        return (f"log:{sev}:{msg}" if sev == "ERROR" else None), [f"log:{sev}:{msg}"]
    if kind == "guard":
        return f"guard:{span['name']}", []
    if kind == "reply":
        outcome = a.get("reply.outcome", "")
        return (f"reply:{outcome}" if outcome != "pending" else None), []
    return None, []


def _result_keys(raw: Any) -> list[str]:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    return sorted(data) if isinstance(data, dict) else []


def build_evidence(env: Environment, bisect: dict[str, Any] | None, money: list[str]) -> Evidence:
    failing, passing = set(env.failed_chat_ids()), set(env.passing_chat_ids())
    allowed = list(env.panel.current.allowed_tools)
    key_chats: dict[str, set[str]] = defaultdict(set)
    bag_chats: dict[str, set[str]] = defaultdict(set)
    codes: dict[int, int] = defaultdict(int)
    result_keys: dict[str, set[str]] = defaultdict(set)
    for s in env.read_traces(limit=None):
        chat = s["attributes"]["chat.id"]
        key_tok, extra = span_tokens(s, allowed)
        if key_tok:
            key_chats[key_tok].add(chat)
            bag_chats[key_tok].add(chat)
        for t in extra:
            bag_chats[t].add(chat)
        a = s["attributes"]
        if chat in failing and a["najda.kind"] == "tool":
            if s["status"]["code"] == "ERROR" and a.get("http.response.status_code") is not None:
                codes[int(a["http.response.status_code"])] += 1
            else:
                result_keys[a["tool.name"]].update(_result_keys(a.get("tool.result")))

    def failing_only(chats: set[str]) -> bool:
        return bool(chats & failing) and not (chats & passing)

    key = {t for t, chats in key_chats.items() if failing_only(chats) and len(chats & failing) >= MIN_KEY_SHARE * len(failing)}
    bag = {t for t, chats in bag_chats.items() if failing_only(chats)}
    violations = {f"violation:{v['invariant']}" for v in env.read_invariants()}
    key |= violations
    bisect_old: dict[str, Any] = {}
    if bisect and bisect.get("applicable"):
        if bisect.get("culprit_version"):
            key.add("bisect:culprit")
            for knob, change in (bisect.get("changed") or {}).items():
                key.add(f"bisected:{knob}")
                bisect_old[knob] = change["old"]
        else:
            key.add("bisect:no_culprit")
    else:
        key.add("bisect:na")
    if money:
        key.add("money_at_risk")
    bag |= key
    return Evidence(tuple(sorted(key)), frozenset(bag), [c for c, _ in sorted(codes.items(), key=lambda kv: -kv[1])],
                    {t: sorted(k) for t, k in result_keys.items()}, bisect_old, bool(money))


# ------------------------------ templates ----------------------------------

def parameterise(patch: dict[str, Any], ev: Evidence) -> dict[str, Any]:
    """Replace values that are explained by the evidence with placeholders."""
    out: dict[str, Any] = {}
    for knob, value in patch.items():
        if knob in ev.bisect_old and ev.bisect_old[knob] == value:
            out[knob] = {"$bisect_old": knob}
        elif knob.startswith("field_mappings.") and isinstance(value, str):
            tool = next((t for t, keys in ev.result_keys.items() if value in keys), None)
            out[knob] = {"$key_for": knob.split(".", 1)[1], "tool": tool} if tool else value
        elif isinstance(value, list) and ev.status_codes:
            out[knob] = [{"$status_code": ev.status_codes.index(v)} if v in ev.status_codes else v for v in value]
        else:
            out[knob] = value
    return out


def instantiate(template: dict[str, Any], ev: Evidence, config: dict[str, Any]) -> dict[str, Any] | None:
    """Fill a template from the new incident's evidence. None when a parameter cannot be filled."""
    out: dict[str, Any] = {}
    for knob, value in template.items():
        filled = _fill(value, ev, config)
        if filled is _UNFILLED:
            return None
        out[knob] = filled
    return out


_UNFILLED = object()


def _fill(value: Any, ev: Evidence, config: dict[str, Any]) -> Any:
    if isinstance(value, list):
        items = [_fill(v, ev, config) for v in value]
        return _UNFILLED if any(i is _UNFILLED for i in items) else items
    if not isinstance(value, dict):
        return value
    if "$bisect_old" in value:
        return ev.bisect_old.get(value["$bisect_old"], _UNFILLED)
    if "$status_code" in value:
        i = int(value["$status_code"])
        return ev.status_codes[i] if i < len(ev.status_codes) else _UNFILLED
    if "$key_for" in value:
        mapped = set((config.get("field_mappings") or {}).values())
        candidates = [k for k in ev.result_keys.get(value.get("tool", ""), []) if k not in mapped]
        return _best_key(value["$key_for"], candidates)
    return value


def _best_key(logical: str, candidates: list[str]) -> Any:
    """The response key that looks most like the logical field: shared word pieces, then substring."""
    if not candidates:
        return _UNFILLED
    pieces = set(re.split(r"[_\-]", logical.lower()))

    def score(k: str) -> tuple[int, int]:
        kp = set(re.split(r"[_\-]", k.lower()))
        return len(pieces & kp), int(k.lower() in logical.lower() or logical.lower() in k.lower())

    best = max(candidates, key=score)
    return best if score(best) > (0, 0) or len(candidates) == 1 else _UNFILLED


# ------------------------------ store ---------------------------------------

@dataclass
class Playbook:
    id: str
    kind: str  # fix | escalate
    label: str  # root-cause taxonomy label
    key: list[str]
    bag: list[str]
    steps: list[dict[str, Any]]  # ordered patch templates (containment steps for an escalate playbook)
    created_at: str
    source_incident: str
    uses: int = 0
    successes: int = 0
    failures: int = 0
    disabled: bool = False
    step_labels: list[str] | None = None  # root-cause label per step (multi-fault playbooks)

    def label_of(self, step: int) -> str:
        return self.step_labels[step] if self.step_labels and step < len(self.step_labels) else self.label

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Match:
    playbook: Playbook
    tier: int
    score: float
    patches: list[dict[str, Any]]


@dataclass
class PlaybookStore:
    playbooks: list[Playbook] = field(default_factory=list)
    max_failures: int = 2

    @classmethod
    def load(cls, path: Path) -> "PlaybookStore":
        data = json.loads(Path(path).read_text())
        return cls([Playbook(**p) for p in data["playbooks"]], int(data.get("max_failures", 2)))

    def save(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps({"version": 1, "max_failures": self.max_failures,
                                          "playbooks": [p.to_dict() for p in self.playbooks]}, indent=1, ensure_ascii=False))

    def active(self) -> list[Playbook]:
        return [p for p in self.playbooks if not p.disabled]

    def learn(self, kind: str, label: str, ev: Evidence, patches: list[dict[str, Any]], source_incident: str,
              step_labels: list[str] | None = None) -> Playbook | None:
        """Store a template for these symptoms. Identical (kind, key, steps) already known -> no duplicate."""
        steps = [parameterise(p, ev) for p in patches]
        for p in self.playbooks:
            if p.kind == kind and tuple(p.key) == ev.key and p.steps == steps:
                return None
        pb = Playbook(f"pb{len(self.playbooks) + 1:03d}", kind, label, list(ev.key), sorted(ev.bag), steps,
                      time.strftime("%Y-%m-%dT%H:%M:%S%z"), source_incident, step_labels=step_labels)
        self.playbooks.append(pb)
        return pb

    def match(self, ev: Evidence, config: dict[str, Any], threshold: float, tiers: int = 2) -> Match | None:
        """Best playbook for this evidence: exact key first, then Jaccard over the bag (escalate playbooks
        only ever match exactly and only with money at risk). Deterministic: ties go to the older playbook."""
        best: Match | None = None
        for pb in self.active():
            if pb.kind == "escalate" and not ev.money:
                continue
            exact = tuple(pb.key) == ev.key
            if exact:
                tier, score = 1, 1.0
            elif tiers >= 2 and pb.kind == "fix":
                tier, score = 2, _jaccard(set(pb.bag), ev.bag)
                if score < threshold:
                    continue
            else:
                continue
            patches = [instantiate(t, ev, config) for t in pb.steps]
            if any(p is None for p in patches):
                continue
            cand = Match(pb, tier, score, patches)  # type: ignore[arg-type]
            if best is None or (cand.tier, -cand.score, cand.playbook.id) < (best.tier, -best.score, best.playbook.id):
                best = cand
        return best

    def record(self, pb: Playbook, success: bool) -> None:
        pb.uses += 1
        if success:
            pb.successes += 1
        else:
            pb.failures += 1
            if pb.failures >= self.max_failures:
                pb.disabled = True

    def stats(self) -> dict[str, Any]:
        return {"playbooks": len(self.playbooks), "active": len(self.active()),
                "uses": sum(p.uses for p in self.playbooks), "successes": sum(p.successes for p in self.playbooks),
                "failures": sum(p.failures for p in self.playbooks)}


def _jaccard(a: set[str], b: frozenset[str] | set[str]) -> float:
    return len(a & b) / len(a | b) if a or b else 0.0
