"""Make ground truth unreadable while a doctor runs.

A process-wide audit hook rejects any open/listdir/scandir of a path containing "_truth" while
the seal is active. The runner preloads all truth records into memory BEFORE sealing, so the
scorer and the replay closure never need the files during a doctor's run.
"""
from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
from typing import Any, Iterator

TRUTH_MARKER = "_truth"
_state = {"depth": 0, "installed": False}
_lock = threading.Lock()
_EVENTS = {"open", "os.listdir", "os.scandir", "os.walk", "glob.glob"}


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if _state["depth"] and event in _EVENTS and args:
        target = args[0]
        if isinstance(target, bytes):
            target = target.decode(errors="ignore")
        if isinstance(target, str) and TRUTH_MARKER in target:
            raise PermissionError(f"ground truth is sealed during doctor runs: {target}")


@contextmanager
def truth_sealed() -> Iterator[None]:
    with _lock:
        if not _state["installed"]:
            sys.addaudithook(_hook)
            _state["installed"] = True
        _state["depth"] += 1
    try:
        yield
    finally:
        with _lock:
            _state["depth"] -= 1


def is_sealed() -> bool:
    return bool(_state["depth"])
