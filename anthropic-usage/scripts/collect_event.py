"""
Anthropic Usage Event Collector
================================
Receives a single usage event from repository_dispatch payload and appends
it to data/raw_events.jsonl as a JSON Lines record.

Triggered by .github/workflows/anthropic-usage-collector.yml on
`repository_dispatch` events of type 'anthropic-usage'.

The aggregator (separate workflow) reads raw_events.jsonl periodically and
produces the dashboard JSON files.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
log = logging.getLogger("collector")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_EVENTS = DATA_DIR / "raw_events.jsonl"


def _required_int(d: dict, key: str) -> int:
    v = d.get(key, 0)
    try:
        return int(v) if v is not None else 0
    except (ValueError, TypeError):
        return 0


def main() -> int:
    payload_raw = os.environ.get("EVENT_PAYLOAD", "").strip()
    if not payload_raw:
        log.error("EVENT_PAYLOAD environment variable is empty.")
        return 1

    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError as e:
        log.error("Invalid JSON payload: %s", e)
        log.error("Raw: %s", payload_raw[:500])
        return 1

    # Build normalized event record
    event = {
        "ts":              payload.get("ts") or datetime.now(timezone.utc).isoformat(),
        "received_at":     datetime.now(timezone.utc).isoformat(),
        "repo":            str(payload.get("repo", "unknown"))[:100],
        "workflow":        str(payload.get("workflow", "unknown"))[:200],
        "run_id":          str(payload.get("run_id", ""))[:50],
        "tag":             str(payload.get("tag", ""))[:50],
        "model":           str(payload.get("model", "unknown"))[:100],
        "input_tokens":          _required_int(payload, "input_tokens"),
        "output_tokens":         _required_int(payload, "output_tokens"),
        "cache_read_tokens":     _required_int(payload, "cache_read_tokens"),
        "cache_create_tokens":   _required_int(payload, "cache_create_tokens"),
        "estimated_usd":         float(payload.get("estimated_usd", 0.0) or 0.0),
    }

    # Sanity: skip if all token counts are zero (likely test/empty)
    total_tokens = (
        event["input_tokens"]
        + event["output_tokens"]
        + event["cache_read_tokens"]
        + event["cache_create_tokens"]
    )
    if total_tokens == 0:
        log.warning("All token counts are zero. Skipping (event=%s).", event)
        return 0

    # Append to JSONL
    with RAW_EVENTS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")

    log.info(
        "✓ Appended event: repo=%s wf=%s model=%s tokens=%d usd=$%.4f",
        event["repo"], event["workflow"], event["model"], total_tokens, event["estimated_usd"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
