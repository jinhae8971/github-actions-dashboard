"""
orchestrator.py — GitHub Actions dashboard data collector

This script keeps the dashboard focused on currently operated systems:
- core monitors
- Global Market Brief agents and orchestrator
- Cycle Intelligence agents and hub
- TrendSpider clone jobs

It intentionally excludes old disabled/noisy repositories from the operational view.
"""

import base64
import json
import os
import re
from datetime import datetime, timezone

import requests

GH_PAT = os.environ.get("GH_PAT", "").strip()
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GH_TOKEN = GH_PAT or GITHUB_TOKEN

if not GH_TOKEN:
    raise RuntimeError("GH_PAT 또는 GITHUB_TOKEN 환경변수가 필요합니다.")

HAS_PAT = bool(GH_PAT)
GH_USER = "jinhae8971"

REPOS = [
    "crypto-monitor",
    "korean-stock-agent",
    # Global Market Brief ecosystem
    "crypto-research-agent",
    "kospi-research-agent",
    "sp500-research-agent",
    "nasdaq-research-agent",
    "dow30-research-agent",
    "global-market-orchestrator",
    # Cycle Intelligence ecosystem
    "crypto-cycle-intelligence",
    "ai-semi-cycle-intelligence",
    "cycle-intelligence-hub",
    # TrendSpider Free Clone ecosystem
    "trendline-detector",
    "chart-analyzer",
    "backtest-lab",
]

EXCLUDED_WORKFLOWS = {
    ("korean-stock-agent", ".github/workflows/main.yml"),
    # Retired disabled paths. Active replacements live at .github/workflows/daily-active.yml.
    ("crypto-research-agent", ".github/workflows/daily.yml"),
    ("kospi-research-agent", ".github/workflows/daily.yml"),
    ("sp500-research-agent", ".github/workflows/daily.yml"),
    ("nasdaq-research-agent", ".github/workflows/daily.yml"),
    ("dow30-research-agent", ".github/workflows/daily.yml"),
    ("global-market-orchestrator", ".github/workflows/daily.yml"),
}

REPORT_MAP = {
    "crypto-monitor/239770946": "reports/latest.json",
    "korean-stock-agent/242830429": "docs/data/foreign_flow.json",
    # Global Market Brief ecosystem: docs/reports/index.json points to the latest daily file.
    "crypto-research-agent/latest": "index:docs/reports",
    "kospi-research-agent/latest": "index:docs/reports",
    "sp500-research-agent/latest": "index:docs/reports",
    "nasdaq-research-agent/latest": "index:docs/reports",
    "dow30-research-agent/latest": "index:docs/reports",
    "global-market-orchestrator/latest": "index:docs/reports",
    # Cycle Intelligence ecosystem
    "crypto-cycle-intelligence/latest": "data/latest.json",
    "ai-semi-cycle-intelligence/latest": "data/latest.json",
    "cycle-intelligence-hub/latest": "data/hub_summary.json",
}

HEADERS = {
    "Authorization": f"Bearer {GH_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


def gh_get(path, params=None):
    url = f"https://api.github.com{path}"
    response = requests.get(url, headers=HEADERS, params=params, timeout=25)
    response.raise_for_status()
    return response.json()


def decode_content_file(data):
    return base64.b64decode(data["content"].replace("\n", "")).decode("utf-8")


def load_paused_intent():
    try:
        with open("data/paused.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        paused = data.get("paused", {})
        print(f"  -> paused.json 로드: {len(paused)}개")
        return paused
    except FileNotFoundError:
        print("  -> paused.json 없음")
        return {}
    except Exception as exc:
        print(f"  -> paused.json 로드 실패: {exc}")
        return {}


def sync_paused_json(workflows):
    print("\n=== Sync paused.json from GitHub workflow state ===")
    old_paused = load_paused_intent()
    old_ids = set(old_paused.keys())

    new_paused = {}
    for item in workflows:
        workflow = item["wf"]
        workflow_id = str(workflow["id"])
        if workflow["state"] in ("disabled_manually", "disabled_inactivity"):
            new_paused[workflow_id] = old_paused.get(
                workflow_id,
                {"repo": item["repo"], "name": workflow["name"]},
            )

    new_ids = set(new_paused.keys())
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    sync_log = {"added": [], "removed": []}

    for workflow_id in added:
        info = new_paused[workflow_id]
        print(f"  + paused: [{info['repo']}] {info['name']}")
        sync_log["added"].append({"wf_id": workflow_id, **info})

    for workflow_id in removed:
        info = old_paused[workflow_id]
        print(f"  - resumed/removed: [{info.get('repo')}] {info.get('name')}")
        sync_log["removed"].append({"wf_id": workflow_id, **info})

    if not added and not removed:
        print("  -> 변경 없음")

    os.makedirs("data", exist_ok=True)
    paused_data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "paused": new_paused,
    }
    with open("data/paused.json", "w", encoding="utf-8") as f:
        json.dump(paused_data, f, ensure_ascii=False, indent=2)

    print(f"  -> paused.json 저장: {len(new_paused)}개")
    return sync_log


def get_cron(repo, workflow_path):
    try:
        data = gh_get(f"/repos/{GH_USER}/{repo}/contents/{workflow_path}")
        content = decode_content_file(data)
        match = re.search(r"cron:\s*[\"']([^\"']+)[\"']", content)
        return match.group(1) if match else None
    except Exception as exc:
        print(f"  [cron] {repo}/{workflow_path}: {exc}")
        return None


def fetch_workflow_runs(repo, workflow_id):
    data = gh_get(
        f"/repos/{GH_USER}/{repo}/actions/workflows/{workflow_id}/runs",
        params={"per_page": 7},
    )
    return [
        {
            "run_number": run["run_number"],
            "conclusion": run.get("conclusion"),
            "status": run["status"],
            "created_at": run["created_at"],
            "html_url": run["html_url"],
        }
        for run in data.get("workflow_runs", [])
    ]


def fetch_all_workflow_data():
    print("\n=== Collect workflow status ===")
    if not HAS_PAT:
        print("  ! GH_PAT 없음: public repo만 수집될 수 있습니다.")

    workflows = []
    skipped_repos = []

    for repo in REPOS:
        print(f"\n# {repo}")
        try:
            data = gh_get(f"/repos/{GH_USER}/{repo}/actions/workflows", params={"per_page": 100})
            for workflow in data.get("workflows", []):
                if workflow["name"] == "pages-build-deployment":
                    continue
                if (repo, workflow["path"]) in EXCLUDED_WORKFLOWS:
                    print(f"  -> 제외: {workflow['name']} ({workflow['path']})")
                    continue

                workflow_id = workflow["id"]
                state_icon = "pause" if workflow["state"] != "active" else "active"
                print(f"  {state_icon}: {workflow['name']} (ID:{workflow_id}, state:{workflow['state']})")

                cron = get_cron(repo, workflow["path"])
                runs = fetch_workflow_runs(repo, workflow_id)
                workflows.append(
                    {
                        "repo": repo,
                        "wf": {
                            "id": workflow_id,
                            "name": workflow["name"],
                            "path": workflow["path"],
                            "state": workflow["state"],
                            "html_url": workflow["html_url"],
                        },
                        "cron": cron,
                        "runs": runs,
                    }
                )
                print(f"    -> runs: {len(runs)} / cron: {cron}")

        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else 0
            if status_code in (401, 403, 404):
                skipped_repos.append(repo)
                print(f"  [skip] {repo}: HTTP {status_code}")
            else:
                print(f"  [error] {repo}: HTTP {status_code}: {exc}")
        except Exception as exc:
            print(f"  [error] {repo}: {exc}")

    if skipped_repos:
        print(f"\n  ! 접근 불가 repo {len(skipped_repos)}개: {', '.join(skipped_repos)}")

    return workflows


def latest_from_index(index_list):
    candidates = []
    for item in index_list:
        if isinstance(item, dict) and item.get("date"):
            candidates.append((item["date"], item))
        elif isinstance(item, str):
            candidates.append((item, {"date": item}))
    if not candidates:
        return None
    return max(candidates, key=lambda pair: pair[0])[1]


def fetch_report(repo, report_path):
    try:
        if report_path.startswith("index:"):
            base_path = report_path[len("index:") :]
            index_data = gh_get(f"/repos/{GH_USER}/{repo}/contents/{base_path}/index.json")
            index_list = json.loads(decode_content_file(index_data))
            latest = latest_from_index(index_list)
            if not latest:
                print(f"  [report] {repo}: index.json 비어 있음")
                return None

            latest_date = latest["date"]
            data = gh_get(f"/repos/{GH_USER}/{repo}/contents/{base_path}/{latest_date}.json")
            report = json.loads(decode_content_file(data))
            if isinstance(report, dict) and isinstance(latest, dict):
                for key, value in latest.items():
                    report.setdefault(key, value)
            return report

        data = gh_get(f"/repos/{GH_USER}/{repo}/contents/{report_path}")
        return json.loads(decode_content_file(data))
    except Exception as exc:
        print(f"  [report] {repo}/{report_path}: {exc}")
        return None


def fetch_all_reports():
    print("\n=== Collect latest report files ===")
    os.makedirs("data/reports", exist_ok=True)
    saved = 0

    for key, report_path in REPORT_MAP.items():
        repo = key.split("/", 1)[0]
        report = fetch_report(repo, report_path)
        if report is None:
            continue

        out_name = f"{key.replace('/', '_')}.json"
        out_path = os.path.join("data", "reports", out_name)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"  -> {out_path} 저장")
        saved += 1

    print(f"  -> 총 {saved}개 리포트 저장")


def main():
    timestamp = datetime.now(timezone.utc)
    print("=" * 55)
    print("GitHub Actions dashboard orchestrator")
    print(f"run_at: {timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"GH_PAT: {'set' if HAS_PAT else 'not set'}")
    print("=" * 55)

    workflows = fetch_all_workflow_data()
    sync_log = sync_paused_json(workflows)
    fetch_all_reports()

    disabled = [
        item
        for item in workflows
        if item["wf"]["state"] in ("disabled_manually", "disabled_inactivity")
    ]
    active = [item for item in workflows if item["wf"]["state"] == "active"]

    result = {
        "updated_at": timestamp.isoformat(),
        "orchestrator": {
            "version": "3.2",
            "synced_at": timestamp.isoformat(),
            "has_pat": HAS_PAT,
            "paused_count": len(disabled),
            "monitored_repos": REPOS,
            "excluded_workflows": [
                {"repo": repo, "path": path} for repo, path in sorted(EXCLUDED_WORKFLOWS)
            ],
            "sync_log": sync_log,
        },
        "workflows": workflows,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/workflows.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 55)
    print("Dashboard sync complete")
    print(f"active workflows: {len(active)}")
    print(f"paused workflows: {len(disabled)}")
    print(f"total workflows: {len(workflows)}")


if __name__ == "__main__":
    main()
