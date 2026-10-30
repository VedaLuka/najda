"""Root-cause labels a doctor reports. A generic on-call taxonomy, not a list of benchmark faults."""
from __future__ import annotations

ROOT_CAUSES: dict[str, str] = {
    "no_fault": "nothing is broken",
    "schema_change": "an upstream API renamed or removed a response field",
    "bad_prompt_deploy": "a prompt version change altered the bot's behaviour or tool plan",
    "invalid_tool": "the bot calls a tool that does not exist or is not allowed",
    "agent_loop": "the bot repeats actions without progress (stuck upstream state, loose turn guard)",
    "rate_limiting": "an upstream returns 429 Too Many Requests",
    "auth_failure": "credentials rejected by an upstream (401/403)",
    "unit_mismatch": "a numeric field is in a different unit than the bot assumes",
    "input_format": "customers send input in a format the parser does not handle",
    "stale_data": "an upstream serves stale or cached data",
    "missing_event": "an expected async event or webhook never arrives",
    "upstream_latency": "an upstream is slower than the bot's timeout",
    "upstream_outage": "a dependency is down (5xx on every call)",
    "data_corruption": "an upstream returns impossible values",
    "ambiguous_state": "a side effect may have happened but its outcome is unknown",
    "unknown": "could not determine the cause",
}
