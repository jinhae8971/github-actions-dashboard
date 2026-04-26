"""Enrich dashboard data with manifest-driven operations health.

This runs after scripts/orchestrator.py has collected GitHub workflow state and
report snapshots. It keeps the legacy collector stable while adding a control
plane view: expected state, freshness, report health, and hub dependencies.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path

import yaml


ROOT = Path(".")
SYSTEMS_PATH = ROOT / "config" / "systems.yaml"
WORKFLOWS_PATH = ROOT / "data" / "workflows.json"
REPORTS_DIR = ROOT / "data" / "reports"


def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def age_hours(value, now):
    dt = parse_dt(value)
    if not dt:
        return None
    return max(0.0, (now - dt.astimezone(timezone.utc)).total_seconds() / 3600)


def load_json(path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data):
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def load_manifest():
    if not SYSTEMS_PATH.exists():
        return {"defaults": {"expected_state": "active", "freshness_sla_hours": 30}, "systems": []}
    with SYSTEMS_PATH.open("r", encoding="utf-8") as f:
        manifest = yaml.safe_load(f) or {}
    manifest.setdefault("defaults", {})
    manifest.setdefault("systems", [])
    manifest["defaults"].setdefault("expected_state", "active")
    manifest["defaults"].setdefault("freshness_sla_hours", 30)
    return manifest


def report_output_name(key):
    return f"{key.replace('/', '_')}.json"


def extract_report_at(report):
    if not isinstance(report, dict):
        return None
    for key in ("timestamp", "generated_at", "updated_at", "date", "as_of"):
        dt = parse_dt(report.get(key))
        if dt:
            return dt
    return None


def status(state, label, severity, reason, **extra):
    out = {"state": state, "label": label, "severity": severity, "reason": reason}
    out.update(extra)
    return out


def build_system_maps(manifest):
    defaults = manifest["defaults"]
    systems = manifest["systems"]
    by_repo = {item["repo"]: item for item in systems if item.get("repo")}
    report_meta = {}
    for item in systems:
        repo = item.get("repo")
        if not repo:
            continue
        for report in item.get("reports") or []:
            key = report.get("key")
            if not key:
                continue
            report_meta[key] = {
                "repo": repo,
                "system_id": item.get("id", repo),
                "label": item.get("label", repo),
                "freshness_sla_hours": item.get(
                    "freshness_sla_hours", defaults["freshness_sla_hours"]
                ),
            }
    return by_repo, report_meta


def ops_for_workflow(repo, wf_path, system, defaults):
    reports = [r["key"] for r in (system.get("reports") or []) if r.get("key")]
    return {
        "system_id": system.get("id", repo),
        "label": system.get("label", repo),
        "group": system.get("group", "uncategorized"),
        "role": system.get("role", "workflow"),
        "expected_state": system.get("expected_state", defaults["expected_state"]),
        "schedule_kst": system.get("schedule_kst"),
        "telegram_policy": system.get("telegram_policy", "unspecified"),
        "freshness_sla_hours": system.get("freshness_sla_hours", defaults["freshness_sla_hours"]),
        "dependency_min_fresh": system.get("dependency_min_fresh"),
        "depends_on": system.get("depends_on") or [],
        "dashboard_url": system.get("dashboard_url"),
        "report_keys": reports,
        "workflow_path": wf_path,
    }


def workflow_health(item, now):
    wf = item["wf"]
    runs = item.get("runs") or []
    ops = item.get("ops") or {}
    expected = ops.get("expected_state", "active")
    sla = float(ops.get("freshness_sla_hours") or 30)
    wf_state = wf.get("state")

    if wf_state in ("disabled_manually", "disabled_inactivity"):
        if expected == "paused":
            return status("paused_expected", "의도 정지", 0, "Manifest marks this workflow as intentionally paused.")
        return status("paused_unexpected", "정책 불일치", 2, "Workflow is disabled, but manifest expects active.")

    if expected == "paused" and wf_state == "active":
        return status("active_unexpected", "예상 밖 활성", 1, "Manifest expects paused, but workflow is active.")

    if not runs:
        return status("no_recent_run", "실행 기록 없음", 2, "No recent workflow runs were found.")

    last = runs[0]
    last_at = last.get("created_at")
    run_age = age_hours(last_at, now)
    if last.get("status") in ("queued", "in_progress"):
        return status("running", "실행 중", 0, "Workflow is currently running.", last_run_at=last_at, age_hours=run_age)

    conclusion = last.get("conclusion")
    if conclusion in ("failure", "timed_out", "action_required"):
        return status("failing", "실패", 3, f"Last run concluded with {conclusion}.", last_run_at=last_at, age_hours=run_age)

    if run_age is not None and run_age > sla:
        return status("stale_run", "실행 지연", 2, f"Last run is {run_age:.1f}h old; SLA is {sla:g}h.", last_run_at=last_at, age_hours=run_age, sla_hours=sla)

    return status("ok", "정상", 0, "Workflow is active and recent.", last_run_at=last_at, age_hours=run_age, sla_hours=sla)


def report_health(key, meta, now):
    repo = meta.get("repo", key.split("/", 1)[0])
    path = REPORTS_DIR / report_output_name(key)
    sla = float(meta.get("freshness_sla_hours") or 30)
    base = {"key": key, "repo": repo, "system_id": meta.get("system_id"), "label": meta.get("label"), "sla_hours": sla}

    if not path.exists():
        return {**base, **status("missing", "리포트 없음", 2, "Latest report cache is missing."), "report_at": None, "age_hours": None}

    try:
        report = load_json(path)
    except Exception as exc:
        return {**base, **status("invalid", "리포트 오류", 2, f"Report JSON could not be read: {exc}"), "report_at": None, "age_hours": None}

    report_at = extract_report_at(report)
    if not report_at:
        return {**base, **status("unknown", "시각 미상", 1, "Report exists, but no parseable timestamp was found."), "report_at": None, "age_hours": None}

    report_age = max(0.0, (now - report_at.astimezone(timezone.utc)).total_seconds() / 3600)
    stale = report_age > sla
    return {
        **base,
        **status(
            "stale" if stale else "fresh",
            "리포트 지연" if stale else "리포트 최신",
            2 if stale else 0,
            f"Report is {report_age:.1f}h old; SLA is {sla:g}h.",
        ),
        "report_at": report_at.astimezone(timezone.utc).isoformat(),
        "age_hours": report_age,
    }


def health_counts(workflows):
    counts = {}
    for item in workflows:
        state = (item.get("health") or {}).get("state", "unknown")
        counts[state] = counts.get(state, 0) + 1
    return counts


def finite_float(value):
    return None if value is None or not math.isfinite(float(value)) else round(float(value), 2)


def main():
    now = datetime.now(timezone.utc)
    manifest = load_manifest()
    defaults = manifest["defaults"]
    by_repo, report_meta = build_system_maps(manifest)
    data = load_json(WORKFLOWS_PATH)
    workflows = data.get("workflows") or []

    for item in workflows:
        repo = item["repo"]
        system = by_repo.get(repo, {"repo": repo, "id": repo, "label": repo})
        item["ops"] = ops_for_workflow(repo, item["wf"].get("path"), system, defaults)
        item["health"] = workflow_health(item, now)

    reports = {key: report_health(key, meta, now) for key, meta in report_meta.items()}
    report_by_repo = {}
    for rep in reports.values():
        report_by_repo.setdefault(rep["repo"], rep)

    for item in workflows:
        rep = report_by_repo.get(item["repo"])
        if rep:
            rep = {**rep, "age_hours": finite_float(rep.get("age_hours"))}
            item["report"] = rep
            if item["health"]["state"] in ("ok", "running"):
                if rep["state"] == "missing":
                    item["health"] = status("missing_report", "리포트 없음", 2, "Workflow is active, but latest report cache is missing.")
                elif rep["state"] == "stale":
                    item["health"] = status("stale_report", "리포트 지연", 2, rep["reason"], report_at=rep.get("report_at"), age_hours=rep.get("age_hours"), sla_hours=rep.get("sla_hours"))

    workflow_by_repo = {item["repo"]: item for item in workflows}
    for item in workflows:
        deps = item.get("ops", {}).get("depends_on") or []
        if not deps:
            continue
        rows = []
        fresh_count = 0
        for dep in deps:
            dep_item = workflow_by_repo.get(dep)
            dep_report = report_by_repo.get(dep)
            wf_state = dep_item["health"]["state"] if dep_item else "missing_workflow"
            rep_state = dep_report["state"] if dep_report else "missing_report"
            fresh = dep_item is not None and wf_state in ("ok", "running") and rep_state in ("fresh", "unknown")
            fresh_count += 1 if fresh else 0
            rows.append({
                "repo": dep,
                "workflow_state": wf_state,
                "workflow_label": dep_item["health"]["label"] if dep_item else "워크플로 없음",
                "report_state": rep_state,
                "report_at": dep_report.get("report_at") if dep_report else None,
                "fresh": fresh,
            })

        required = item.get("ops", {}).get("dependency_min_fresh") or len(deps)
        ok = fresh_count >= required
        item["upstream"] = {
            "ok": ok,
            "fresh_count": fresh_count,
            "required_fresh_count": required,
            "total_count": len(deps),
            "dependencies": rows,
        }
        if not ok and item["health"]["state"] in ("ok", "running", "stale_run", "stale_report"):
            item["health"] = status("upstream_degraded", "상위 입력 문제", 2, f"Only {fresh_count}/{len(deps)} dependencies are fresh; required {required}.", fresh_count=fresh_count, required_fresh_count=required)

    systems = []
    for item in workflows:
        rep = report_by_repo.get(item["repo"]) or {}
        systems.append({
            "repo": item["repo"],
            "system_id": item["ops"]["system_id"],
            "label": item["ops"]["label"],
            "group": item["ops"]["group"],
            "role": item["ops"]["role"],
            "expected_state": item["ops"]["expected_state"],
            "workflow_state": item["wf"]["state"],
            "health_state": item["health"]["state"],
            "health_label": item["health"]["label"],
            "severity": item["health"]["severity"],
            "report_state": rep.get("state"),
            "upstream_ok": (item.get("upstream") or {}).get("ok"),
        })

    data["systems"] = systems
    data["reports"] = reports
    data.setdefault("orchestrator", {})
    data["orchestrator"]["version"] = "4.0"
    data["orchestrator"]["config_version"] = manifest.get("version")
    data["orchestrator"]["health_counts"] = health_counts(workflows)
    data["orchestrator"]["systems_manifest"] = str(SYSTEMS_PATH)
    write_json(WORKFLOWS_PATH, data)
    print(f"ops health enriched: {len(workflows)} workflows, {len(reports)} reports")


if __name__ == "__main__":
    main()
