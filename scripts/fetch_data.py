"""
GitHub Actions 대시보드 - 데이터 수집 스크립트
GitHub Actions 워크플로우에서 실행됩니다. (토큰은 GH_PAT 환경변수로 주입)
"""
import os, json, base64, re, requests
from datetime import datetime, timezone

# ── 설정 ─────────────────────────────────────────────────────────────────────
GH_TOKEN = os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')
if not GH_TOKEN:
    raise RuntimeError("GH_PAT 환경변수가 설정되지 않았습니다.")

GH_USER = 'jinhae8971'

REPOS = [
    'korean-market-bot',
    'lgd-news-monitor',
    'livebench-notify',
    'memory-price-tracker',
    'realestate-permit-tracker',
    'competitor-ai-tracker',
]

# 리포트 파일 매핑: { "repo/workflow_id": "repo내_경로" }
# workflow ID는 첫 실행 후 workflows.json을 보고 업데이트하세요
REPORT_MAP = {
    'korean-market-bot/236541757':         'reports/latest_kr.json',
    'korean-market-bot/236553677':         'reports/latest_us.json',
    'competitor-ai-tracker/237174445':     'reports/latest.json',
    'lgd-news-monitor/236856279':          'reports/latest.json',
    'livebench-notify/236850987':          'reports/latest.json',
    'memory-price-tracker/236642604':      'reports/latest.json',
    'realestate-permit-tracker/236653953': 'reports/latest.json',
}

HEADERS = {
    'Authorization': f'token {GH_TOKEN}',
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
}

# ── API 호출 ──────────────────────────────────────────────────────────────────
def gh_get(path, params=None):
    url = f'https://api.github.com{path}'
    r = requests.get(url, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def get_cron(repo, wf_path):
    """워크플로우 YAML에서 cron 스케줄 추출"""
    try:
        data = gh_get(f'/repos/{GH_USER}/{repo}/contents/{wf_path}')
        content = base64.b64decode(data['content'].replace('\n', '')).decode('utf-8')
        m = re.search(r"cron:\s*[\"']([^\"']+)[\"']", content)
        return m.group(1) if m else None
    except Exception as e:
        print(f'  [cron] {repo}/{wf_path}: {e}')
        return None


def fetch_report(repo, report_path):
    """리포트 JSON 파일 가져오기"""
    try:
        data = gh_get(f'/repos/{GH_USER}/{repo}/contents/{report_path}')
        raw = base64.b64decode(data['content'].replace('\n', '')).decode('utf-8')
        return json.loads(raw)
    except Exception as e:
        print(f'  [report] {repo}/{report_path}: {e}')
        return None


# ── 메인 수집 ─────────────────────────────────────────────────────────────────
def main():
    print(f'[{datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}] 데이터 수집 시작')
    workflows = []

    for repo in REPOS:
        print(f'\n■ {repo}')
        try:
            wfs = gh_get(f'/repos/{GH_USER}/{repo}/actions/workflows')
            for wf in wfs.get('workflows', []):
                wf_id = wf['id']
                print(f'  워크플로우: {wf["name"]} (ID: {wf_id})')

                cron   = get_cron(repo, wf['path'])
                runs_d = gh_get(
                    f'/repos/{GH_USER}/{repo}/actions/runs',
                    params={'workflow_id': wf_id, 'per_page': 7}
                )
                runs = [
                    {
                        'run_number': r['run_number'],
                        'conclusion': r.get('conclusion'),
                        'status':     r['status'],
                        'created_at': r['created_at'],
                        'html_url':   r['html_url'],
                    }
                    for r in runs_d.get('workflow_runs', [])
                ]

                workflows.append({
                    'repo': repo,
                    'wf': {
                        'id':       wf_id,
                        'name':     wf['name'],
                        'path':     wf['path'],
                        'state':    wf['state'],
                        'html_url': wf['html_url'],
                    },
                    'cron': cron,
                    'runs': runs,
                })
                print(f'    → 최근 {len(runs)}회 실행 / cron: {cron}')

        except Exception as e:
            print(f'  [오류] {repo}: {e}')

    # ── 리포트 수집 ──────────────────────────────────────────────────────────
    print('\n■ 리포트 파일 수집')
    os.makedirs('data/reports', exist_ok=True)
    for key, report_path in REPORT_MAP.items():
        repo = key.split('/')[0]
        report = fetch_report(repo, report_path)
        if report:
            out_name = key.replace('/', '_') + '.json'
            with open(f'data/reports/{out_name}', 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f'  → data/reports/{out_name} 저장 완료')

    # ── 결과 저장 ─────────────────────────────────────────────────────────────
    os.makedirs('data', exist_ok=True)
    result = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'workflows':  workflows,
    }
    with open('data/workflows.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f'\n✅ 완료: {len(workflows)}개 워크플로우 → data/workflows.json')


if __name__ == '__main__':
    main()
