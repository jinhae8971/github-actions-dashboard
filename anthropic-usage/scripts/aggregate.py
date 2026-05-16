"""
Anthropic Usage Aggregator
==========================
Reads data/raw_events.jsonl (append-only event log) and produces the four
dashboard JSON files:

    data/summary.json
    data/daily.json
    data/top_workflows.json
    data/model_breakdown.json

Runs after each event ingestion AND on schedule.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
log = logging.getLogger("aggregator")

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_EVENTS = DATA_DIR / "raw_events.jsonl"

LOOKBACK_DAYS = 30


def _load_events() -> list[dict[str, Any]]:
    if not RAW_EVENTS.exists():
        log.warning("raw_events.jsonl does not exist yet.")
        return []
    events: list[dict[str, Any]] = []
    with RAW_EVENTS.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as e:
                log.warning("Skipping malformed line %d: %s", i, e)
    log.info("Loaded %d events.", len(events))
    return events


def _date_of(ts: str) -> str:
    """Extract YYYY-MM-DD from ISO timestamp."""
    return ts[:10] if ts else ""


def _normalize_model(model: str) -> str:
    """Strip date suffix for cleaner grouping in the dashboard."""
    if not model:
        return "unknown"
    # claude-sonnet-4-6-20250101 → claude-sonnet-4-6
    parts = model.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) >= 6:
        return parts[0]
    return model


def aggregate(events: list[dict[str, Any]]) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    cutoff = (now_utc - timedelta(days=LOOKBACK_DAYS)).date().isoformat()

    # Filter to lookback window
    recent = [e for e in events if _date_of(e.get("ts", "")) >= cutoff]
    log.info("Events in last %dd: %d / %d total", LOOKBACK_DAYS, len(recent), len(events))

    # -------- Daily aggregation --------
    daily: dict[str, dict[str, float]] = defaultdict(
        lambda: {"tokens": 0, "input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "usd": 0.0, "events": 0}
    )
    for e in recent:
        d = _date_of(e.get("ts", ""))
        if not d:
            continue
        slot = daily[d]
        slot["input"] += e.get("input_tokens", 0)
        slot["output"] += e.get("output_tokens", 0)
        slot["cache_read"] += e.get("cache_read_tokens", 0)
        slot["cache_create"] += e.get("cache_create_tokens", 0)
        slot["tokens"] += (
            e.get("input_tokens", 0) + e.get("output_tokens", 0)
            + e.get("cache_read_tokens", 0) + e.get("cache_create_tokens", 0)
        )
        slot["usd"] += float(e.get("estimated_usd", 0.0))
        slot["events"] += 1

    daily_list = sorted(
        [{"date": d, **v, "usd": round(v["usd"], 4)} for d, v in daily.items()],
        key=lambda x: x["date"],
    )

    # -------- Workflow ranking --------
    wf_totals: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"tokens": 0, "input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "usd": 0.0, "events": 0, "models": set()}
    )
    for e in recent:
        key = f"{e.get('repo', 'unknown')} · {e.get('workflow', '?')}"
        slot = wf_totals[key]
        slot["input"] += e.get("input_tokens", 0)
        slot["output"] += e.get("output_tokens", 0)
        slot["cache_read"] += e.get("cache_read_tokens", 0)
        slot["cache_create"] += e.get("cache_create_tokens", 0)
        slot["tokens"] += (
            e.get("input_tokens", 0) + e.get("output_tokens", 0)
            + e.get("cache_read_tokens", 0) + e.get("cache_create_tokens", 0)
        )
        slot["usd"] += float(e.get("estimated_usd", 0.0))
        slot["events"] += 1
        slot["models"].add(_normalize_model(e.get("model", "unknown")))

    top_workflows = []
    for label, v in wf_totals.items():
        top_workflows.append({
            "label": label,
            "tokens": v["tokens"],
            "input": v["input"],
            "output": v["output"],
            "cache_read": v["cache_read"],
            "cache_create": v["cache_create"],
            "usd": round(v["usd"], 4),
            "events": v["events"],
            "models": sorted(v["models"]),
        })
    top_workflows.sort(key=lambda x: x["tokens"], reverse=True)

    # -------- Model breakdown --------
    model_totals: dict[str, dict[str, float]] = defaultdict(
        lambda: {"tokens": 0, "input": 0, "output": 0, "usd": 0.0, "events": 0}
    )
    for e in recent:
        m = _normalize_model(e.get("model", "unknown"))
        slot = model_totals[m]
        slot["input"] += e.get("input_tokens", 0)
        slot["output"] += e.get("output_tokens", 0)
        slot["tokens"] += (
            e.get("input_tokens", 0) + e.get("output_tokens", 0)
            + e.get("cache_read_tokens", 0) + e.get("cache_create_tokens", 0)
        )
        slot["usd"] += float(e.get("estimated_usd", 0.0))
        slot["events"] += 1

    model_breakdown = sorted(
        [{"model": m, **v, "usd": round(v["usd"], 4)} for m, v in model_totals.items()],
        key=lambda x: x["tokens"],
        reverse=True,
    )

    # -------- Summary KPIs --------
    total_tokens = sum(d["tokens"] for d in daily_list)
    total_usd = round(sum(d["usd"] for d in daily_list), 4)
    mtd_prefix = now_utc.strftime("%Y-%m")
    mtd_tokens = sum(d["tokens"] for d in daily_list if d["date"].startswith(mtd_prefix))
    mtd_usd = round(sum(d["usd"] for d in daily_list if d["date"].startswith(mtd_prefix)), 4)

    summary = {
        "generated_at": now_utc.isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "totals": {"tokens": total_tokens, "usd": total_usd, "events": len(recent)},
        "mtd": {"tokens": mtd_tokens, "usd": mtd_usd, "month": mtd_prefix},
        "all_time_events": len(events),
        "workflow_count": len(top_workflows),
        "model_count": len(model_breakdown),
        "data_source": "self-report (repository_dispatch)",
    }

    return {
        "summary": summary,
        "daily": daily_list,
        "top_workflows": top_workflows,
        "model_breakdown": model_breakdown,
    }


def main() -> None:
    events = _load_events()
    payload = aggregate(events)

    (DATA_DIR / "summary.json").write_text(
        json.dumps(payload["summary"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (DATA_DIR / "daily.json").write_text(
        json.dumps(payload["daily"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (DATA_DIR / "top_workflows.json").write_text(
        json.dumps(payload["top_workflows"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (DATA_DIR / "model_breakdown.json").write_text(
        json.dumps(payload["model_breakdown"], indent=2, ensure_ascii=False), encoding="utf-8"
    )

    log.info(
        "✓ Aggregated: events=%d tokens=%s usd=$%s workflows=%d models=%d",
        payload["summary"]["totals"]["events"],
        f"{payload['summary']['totals']['tokens']:,}",
        f"{payload['summary']['totals']['usd']:,.2f}",
        len(payload["top_workflows"]),
        len(payload["model_breakdown"]),
    )


if __name__ == "__main__":
    main()
