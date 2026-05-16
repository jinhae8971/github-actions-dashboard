"""
Anthropic Admin API Usage Aggregator
=====================================
Fetches usage + cost reports from Anthropic Admin API and produces
aggregated JSON files for the dashboard.

Outputs:
- data/daily.json           : Daily time-series (tokens + cost)
- data/top_workflows.json   : Ranking by api_key_id -> workflow
- data/model_breakdown.json : Per-model token/cost split
- data/summary.json         : KPI summary (MTD, last-30d totals)
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
ADMIN_KEY = os.environ.get("ANTHROPIC_ADMIN_API_KEY", "").strip()
BASE_URL = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"

# Lookback window
LOOKBACK_DAYS = int(os.environ.get("LOOKBACK_DAYS", "30"))

# Paths
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
KEY_MAPPING_PATH = DATA_DIR / "key_mapping.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
log = logging.getLogger("usage-tracker")


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def _headers() -> dict[str, str]:
    if not ADMIN_KEY:
        log.error("ANTHROPIC_ADMIN_API_KEY is not set.")
        sys.exit(1)
    return {
        "anthropic-version": ANTHROPIC_VERSION,
        "x-api-key": ADMIN_KEY,
    }


def _iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_key_mapping() -> dict[str, dict[str, str]]:
    """
    key_mapping.json schema:
    {
      "apikey_01ABC...": {"repo": "kospi-strategy", "workflow": "Daily KOSPI"},
      ...
    }
    """
    if not KEY_MAPPING_PATH.exists():
        log.warning(
            "key_mapping.json not found. api_key_id will be shown as-is."
        )
        return {}
    try:
        raw = json.loads(KEY_MAPPING_PATH.read_text(encoding="utf-8"))
        # Strip instruction/placeholder keys (those starting with '_' or 'REPLACE')
        clean = {
            k: v for k, v in raw.items()
            if not k.startswith("_") and not k.startswith("REPLACE")
        }
        return clean
    except Exception as e:
        log.warning("Failed to read key_mapping.json: %s", e)
        return {}


def _resolve_label(api_key_id: str | None, mapping: dict) -> str:
    if not api_key_id:
        return "(unattributed)"
    entry = mapping.get(api_key_id)
    if not entry:
        return api_key_id[:18] + "…"
    repo = entry.get("repo", "?")
    wf = entry.get("workflow")
    return f"{repo} · {wf}" if wf else repo


# -----------------------------------------------------------------------------
# Admin API clients
# -----------------------------------------------------------------------------
def fetch_usage_report(
    starting_at: datetime,
    ending_at: datetime,
    group_by: list[str],
    bucket_width: str = "1d",
) -> list[dict[str, Any]]:
    """
    Calls /v1/organizations/usage_report/messages with pagination.
    """
    url = f"{BASE_URL}/v1/organizations/usage_report/messages"
    params: list[tuple[str, str]] = [
        ("starting_at", _iso_z(starting_at)),
        ("ending_at", _iso_z(ending_at)),
        ("bucket_width", bucket_width),
    ]
    for g in group_by:
        params.append(("group_by[]", g))

    results: list[dict[str, Any]] = []
    page_token: str | None = None
    page = 0
    while True:
        page += 1
        page_params = list(params)
        if page_token:
            page_params.append(("page", page_token))
        resp = requests.get(url, headers=_headers(), params=page_params, timeout=60)
        if resp.status_code != 200:
            log.error("Usage API error %s: %s", resp.status_code, resp.text[:500])
            resp.raise_for_status()
        body = resp.json()
        buckets = body.get("data", [])
        results.extend(buckets)
        log.info("usage_report page %d: %d buckets", page, len(buckets))
        page_token = body.get("next_page")
        if not page_token:
            break
    return results


def fetch_cost_report(
    starting_at: datetime,
    ending_at: datetime,
    group_by: list[str],
) -> list[dict[str, Any]]:
    """
    Calls /v1/organizations/cost_report. Cost is reported in USD cents
    as decimal strings per the official spec.
    """
    url = f"{BASE_URL}/v1/organizations/cost_report"
    params: list[tuple[str, str]] = [
        ("starting_at", _iso_z(starting_at)),
        ("ending_at", _iso_z(ending_at)),
    ]
    for g in group_by:
        params.append(("group_by[]", g))

    results: list[dict[str, Any]] = []
    page_token: str | None = None
    page = 0
    while True:
        page += 1
        page_params = list(params)
        if page_token:
            page_params.append(("page", page_token))
        resp = requests.get(url, headers=_headers(), params=page_params, timeout=60)
        if resp.status_code != 200:
            log.warning(
                "Cost API error %s (continuing without cost): %s",
                resp.status_code,
                resp.text[:300],
            )
            return []
        body = resp.json()
        buckets = body.get("data", [])
        results.extend(buckets)
        log.info("cost_report page %d: %d buckets", page, len(buckets))
        page_token = body.get("next_page")
        if not page_token:
            break
    return results


# -----------------------------------------------------------------------------
# Aggregation
# -----------------------------------------------------------------------------
def _sum_tokens(result: dict[str, Any]) -> int:
    """Sum input + output + cache tokens from a usage result row."""
    return int(
        (result.get("uncached_input_tokens") or 0)
        + (result.get("cache_read_input_tokens") or 0)
        + (result.get("cache_creation_input_tokens") or 0)
        + (result.get("output_tokens") or 0)
    )


def _cents_to_usd(cents_str: str | float | int | None) -> float:
    if cents_str is None:
        return 0.0
    try:
        return round(float(cents_str) / 100.0, 4)
    except Exception:
        return 0.0


def aggregate(
    usage_buckets: list[dict[str, Any]],
    cost_buckets: list[dict[str, Any]],
    mapping: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Build all dashboard JSON payloads from raw API buckets."""

    # ---- Daily time series (sum across all groupings per bucket) ----
    daily_map: dict[str, dict[str, float]] = {}
    for bucket in usage_buckets:
        date = bucket.get("starting_at", "")[:10]
        slot = daily_map.setdefault(
            date,
            {"tokens": 0, "input": 0, "output": 0, "cache_read": 0, "cache_create": 0},
        )
        for r in bucket.get("results", []):
            slot["input"] += int(r.get("uncached_input_tokens") or 0)
            slot["output"] += int(r.get("output_tokens") or 0)
            slot["cache_read"] += int(r.get("cache_read_input_tokens") or 0)
            slot["cache_create"] += int(r.get("cache_creation_input_tokens") or 0)
            slot["tokens"] += _sum_tokens(r)

    cost_daily_map: dict[str, float] = {}
    for bucket in cost_buckets:
        date = bucket.get("starting_at", "")[:10]
        for r in bucket.get("results", []):
            amount = r.get("amount") or r.get("cost") or 0
            cost_daily_map[date] = cost_daily_map.get(date, 0.0) + _cents_to_usd(amount)

    daily = []
    for date in sorted(set(list(daily_map.keys()) + list(cost_daily_map.keys()))):
        row = {"date": date, **daily_map.get(date, {})}
        row["usd"] = round(cost_daily_map.get(date, 0.0), 4)
        daily.append(row)

    # ---- Workflow ranking (by api_key_id) ----
    wf_totals: dict[str, dict[str, float]] = {}
    for bucket in usage_buckets:
        for r in bucket.get("results", []):
            key_id = r.get("api_key_id")
            slot = wf_totals.setdefault(
                key_id or "(unattributed)",
                {"tokens": 0, "input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "usd": 0.0},
            )
            slot["input"] += int(r.get("uncached_input_tokens") or 0)
            slot["output"] += int(r.get("output_tokens") or 0)
            slot["cache_read"] += int(r.get("cache_read_input_tokens") or 0)
            slot["cache_create"] += int(r.get("cache_creation_input_tokens") or 0)
            slot["tokens"] += _sum_tokens(r)

    # Attach cost per api_key_id if cost report supports that grouping
    for bucket in cost_buckets:
        for r in bucket.get("results", []):
            key_id = r.get("api_key_id")
            if not key_id:
                continue
            amount = r.get("amount") or r.get("cost") or 0
            slot = wf_totals.setdefault(
                key_id,
                {"tokens": 0, "input": 0, "output": 0, "cache_read": 0, "cache_create": 0, "usd": 0.0},
            )
            slot["usd"] += _cents_to_usd(amount)

    top_workflows = []
    for key_id, vals in wf_totals.items():
        top_workflows.append(
            {
                "api_key_id": key_id,
                "label": _resolve_label(key_id, mapping),
                **{k: round(v, 4) if isinstance(v, float) else v for k, v in vals.items()},
            }
        )
    top_workflows.sort(key=lambda x: x["tokens"], reverse=True)

    # ---- Model breakdown ----
    model_totals: dict[str, dict[str, float]] = {}
    for bucket in usage_buckets:
        for r in bucket.get("results", []):
            model = r.get("model") or "unknown"
            slot = model_totals.setdefault(model, {"tokens": 0, "input": 0, "output": 0, "usd": 0.0})
            slot["input"] += int(r.get("uncached_input_tokens") or 0)
            slot["output"] += int(r.get("output_tokens") or 0)
            slot["tokens"] += _sum_tokens(r)

    for bucket in cost_buckets:
        for r in bucket.get("results", []):
            model = r.get("model") or r.get("description") or "unknown"
            amount = r.get("amount") or r.get("cost") or 0
            slot = model_totals.setdefault(model, {"tokens": 0, "input": 0, "output": 0, "usd": 0.0})
            slot["usd"] += _cents_to_usd(amount)

    model_breakdown = [
        {"model": k, **{kk: round(vv, 4) if isinstance(vv, float) else vv for kk, vv in v.items()}}
        for k, v in model_totals.items()
    ]
    model_breakdown.sort(key=lambda x: x["tokens"], reverse=True)

    # ---- KPI summary ----
    total_tokens = sum(d["tokens"] for d in daily)
    total_usd = round(sum(d["usd"] for d in daily), 4)

    # MTD (month-to-date)
    now_utc = datetime.now(timezone.utc)
    mtd_prefix = now_utc.strftime("%Y-%m")
    mtd_tokens = sum(d["tokens"] for d in daily if d["date"].startswith(mtd_prefix))
    mtd_usd = round(sum(d["usd"] for d in daily if d["date"].startswith(mtd_prefix)), 4)

    summary = {
        "generated_at": now_utc.isoformat(),
        "lookback_days": LOOKBACK_DAYS,
        "totals": {"tokens": total_tokens, "usd": total_usd},
        "mtd": {"tokens": mtd_tokens, "usd": mtd_usd, "month": mtd_prefix},
        "top_workflow_count": len(top_workflows),
        "model_count": len(model_breakdown),
    }

    return {
        "daily": daily,
        "top_workflows": top_workflows,
        "model_breakdown": model_breakdown,
        "summary": summary,
    }


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main() -> None:
    log.info("Anthropic Usage Tracker starting…")

    ending = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    starting = ending - timedelta(days=LOOKBACK_DAYS)
    log.info("Window: %s → %s", _iso_z(starting), _iso_z(ending))

    mapping = _load_key_mapping()
    log.info("Loaded %d key mappings.", len(mapping))

    # 1) Usage report — grouped by api_key_id + model, daily bucket
    usage = fetch_usage_report(
        starting_at=starting,
        ending_at=ending,
        group_by=["api_key_id", "model"],
        bucket_width="1d",
    )

    # 2) Cost report — grouped by description (typically includes model + workspace)
    cost = fetch_cost_report(
        starting_at=starting,
        ending_at=ending,
        group_by=["workspace_id", "description"],
    )

    # 3) Aggregate
    payload = aggregate(usage, cost, mapping)

    # 4) Write outputs
    (DATA_DIR / "daily.json").write_text(
        json.dumps(payload["daily"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (DATA_DIR / "top_workflows.json").write_text(
        json.dumps(payload["top_workflows"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (DATA_DIR / "model_breakdown.json").write_text(
        json.dumps(payload["model_breakdown"], indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (DATA_DIR / "summary.json").write_text(
        json.dumps(payload["summary"], indent=2, ensure_ascii=False), encoding="utf-8"
    )

    log.info(
        "✓ Done. tokens=%s usd=$%s top_n=%d models=%d",
        f"{payload['summary']['totals']['tokens']:,}",
        f"{payload['summary']['totals']['usd']:,.2f}",
        len(payload["top_workflows"]),
        len(payload["model_breakdown"]),
    )


if __name__ == "__main__":
    main()
