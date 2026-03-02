"""
orchestrator.py — GitHub Actions 대시보드 오케스트레이터
=======================================================
역할:
  1. [Step 1] data/paused.json (의도 파일)를 읽어 일시정지 대상 파악
  2. [Step 2] 각 워크플로우의 실제 GitHub 상태와 의도를 비교하여 강제 적용
             - 의도: 정지 + 실제: active  →  GitHub API로 disable
             - 의도: 활성 + 실제: disabled →  GitHub API로 enable
  3. [Step 3] 강제 적용 후 모든 워크플로우 데이터 수집 (최신 상태 반영)
  4. [Step 4] 리포트 파일 수집
  5. [Step 5] data/workflows.json 저장 (오케스트레이터 실행 로그 포함)

아키텍처:
  ┌──────────────────────────────────────────────┐
  │           오케스트레이터 (orchestrator.py)      │
  │  • paused.json 의도 읽기                       │
  │  • GitHub 실제 상태 확인                       │
  │  • 불일치 시 강제 적용 (disable/enable API)    │
  │  • workflows.json 갱신                         │
  └───────────┬──────────────────────────────────┘
              │ 감시 & 제어
    ┌─────────▼─────────┐    ┌─────────────────┐
    │  Worker Repos      │    │  Dashboard       │
      (10개 워크플로우)  │    │  (index.html)    ││
    │  실제 작업 수행     │    │  • paused.json   │
    └───────────────────┘    │  • workflows.json │
                             └─────────────────┘

토큰 전략 (2026-03 개선):
  - GH_PAT: workflow 스코프 PAT — private 저장소 Actions API 접근 가능
  - GITHUB_TOKEN: 자동 발급 — public 저장소만 접근 가능 (PAT 없을 때 폴백)
  - PAT가 없거나 만료된 경우에도 public 저장소 데이터는 정상 수집됨
"""
import os, json, base64, re, requests, sys
from datetime import datetime, timezone

# ── 환경 변수 ───────────────────────────────────────────────────────────────
GH_PAT          = os.environ.get('GH_PAT', '').strip()
GITHUB_TOKEN    = os.environ.get('GITHUB_TOKEN', '').strip()

# PAT 우선, 없으면 GITHUB_TOKEN 폴백
GH_TOKEN = GH_PAT or GITHUB_TOKEN
if not GH_TOKEN:
    raise RuntimeError("GH_PAT 또는 GITHUB_TOKEN 환경변수가 필요합니다.")

HAS_PAT = bool(GH_PAT)

GH_USER        = 'jinhae8971'
DASHBOARD_REPO = 'github-actions-dashboard'

# 감시할 워커 레포 목록
REPOS = [
    'korean-market-bot',
    'lgd-news-monitor',
    'livebench-notify',
    'memory-price-tracker',
    'realestate-permit-tracker',
    'competitor-ai-tracker',
    'crypto-monitor',
    'kospi-peak-detector',
    'gmail-auto-cleanup',
    'korean-stock-agent',
    'us-market-agent',
    'etf-strategist',
]

# 워크플로우 ID → 리포트 파일 매핑
REPORT_MAP = {
    'korean-market-bot/236541757':         'reports/latest_kr.json',
    'korean-market-bot/236636495':         'reports/latest_weekly.json',
    'korean-market-bot/236553677':         'reports/latest_us.json',
    'competitor-ai-tracker/237174445':     'reports/latest.json',
    'lgd-news-monitor/236856279':          'reports/latest.json',
    'livebench-notify/236850987':          'reports/latest.json',
    'memory-price-tracker/236642604':      'reports/latest.json',
    'realestate-permit-tracker/236653953': 'reports/latest.json',
    'crypto-monitor/239770946':            'reports/latest.json',
    'kospi-peak-detector/latest':          'reports/latest.json',
    'korean-stock-agent/240094820':        'docs/data/daily_report.json',
    'us-market-agent/240126478':           'docs/data/daily_report.json',
    'etf-strategist/240142776':            'docs/data/daily_report.json',
}

HEADERS = {
    'Authorization': f'token {GH_TOKEN}',
    'Accept': 'application/vnd.github+json',
    'X-GitHub-Api-Version': '2022-11-28',
}


# ── GitHub API 유틸 ─────────────────────────────────────────────────────────

def gh_get(path, params=None):
    url = f'https://api.github.com{path}'
    r = requests.get(url, headers=HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def gh_put(path):
    """PUT 요청 — 워크플로우 enable/disable에 사용. 상태 코드 반환."""
    url = f'https://api.github.com{path}'
    r = requests.put(url, headers=HEADERS, timeout=20)
    return r.status_code


# ── Step 1: 의도 파일 로드 ──────────────────────────────────────────────────

def load_paused_intent():
    """
    data/paused.json에서 일시정지 의도(intent)를 로드.
    대시보드 UI에서 사용자가 설정한 정지 목록이 저장된 파일.
    """
    try:
        with open('data/paused.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
        paused = data.get('paused', {})
        print(f'  → paused.json 로드 성공: {len(paused)}개 의도')
        return paused
    except FileNotFoundError:
        print('  → paused.json 없음 (일시정지 의도 없음)')
        return {}
    except Exception as e:
        print(f'  → paused.json 로드 실패: {e}')
        return {}


# ── Step 2: 상태 강제 적용 (오케스트레이터 핵심) ───────────────────────────

def enforce_workflow_states(paused_intent):
    """
    오케스트레이터 핵심 기능:
    paused.json의 의도를 GitHub 실제 상태에 강제 적용.

    - 의도: 정지  + 실제: active   → GitHub API disable
    - 의도: 활성  + 실제: disabled → GitHub API enable
    - 의도 = 실제                  → 아무것도 하지 않음 (OK)

    GH_PAT 없을 경우: 상태 강제 적용 스킵 (데이터 수집만 수행)

    Returns:
        list: 적용 로그 (변경 사항만 포함)
    """
    print('\n━━━ [오케스트레이터] 워크플로우 상태 강제 적용 ━━━')

    if not HAS_PAT:
        print('  ⚠️  GH_PAT 없음 — 상태 강제 적용 스킵 (데이터 수집만 수행)')
        print('  ℹ️  private 저장소 제어를 위해 GH_PAT 시크릿을 갱신해 주세요.')
        return [{'action': 'skipped', 'reason': 'GH_PAT not set — enforcement skipped, data collection only'}]

    paused_ids = set(str(k) for k in paused_intent.keys())
    enforcement_log = []
    ok_count = 0

    for repo in REPOS:
        try:
            wfs = gh_get(f'/repos/{GH_USER}/{repo}/actions/workflows')
            for wf in wfs.get('workflows', []):
                wf_id       = str(wf['id'])
                should_pause = wf_id in paused_ids
                is_disabled  = wf['state'] in ('disabled_manually', 'disabled_inactivity')

                if should_pause and not is_disabled:
                    # ── 의도: 정지 / 실제: 활성 → 비활성화 ──
                    status = gh_put(
                        f'/repos/{GH_USER}/{repo}/actions/workflows/{wf_id}/disable'
                    )
                    if status == 204:
                        msg = f'⏸ DISABLED  [{repo}] {wf["name"]}'
                        print(f'  {msg}')
                        enforcement_log.append({'action': 'disabled', 'repo': repo,
                                                'wf_id': wf_id, 'name': wf['name']})
                    else:
                        msg = f'❌ FAIL_DISABLE [{repo}] {wf["name"]} (HTTP {status})'
                        print(f'  {msg}')
                        enforcement_log.append({'action': 'fail_disable', 'repo': repo,
                                                'wf_id': wf_id, 'name': wf['name'],
                                                'status': status})

                elif not should_pause and is_disabled:
                    # ── 의도: 활성 / 실제: 비활성 → 활성화 ──
                    status = gh_put(
                        f'/repos/{GH_USER}/{repo}/actions/workflows/{wf_id}/enable'
                    )
                    if status == 204:
                        msg = f'▶ ENABLED   [{repo}] {wf["name"]}'
                        print(f'  {msg}')
                        enforcement_log.append({'action': 'enabled', 'repo': repo,
                                                'wf_id': wf_id, 'name': wf['name']})
                    else:
                        msg = f'❌ FAIL_ENABLE [{repo}] {wf["name"]} (HTTP {status})'
                        print(f'  {msg}')
                        enforcement_log.append({'action': 'fail_enable', 'repo': repo,
                                                'wf_id': wf_id, 'name': wf['name'],
                                                'status': status})

                else:
                    # ── 상태 일치 ──
                    icon = '⏸' if is_disabled else '▶'
                    label = '일시정지' if is_disabled else '활성'
                    print(f'  ✅ OK        [{repo}] {wf["name"]} ({icon} {label})')
                    ok_count += 1

        except Exception as e:
            print(f'  [오류] {repo}: {e}')
            enforcement_log.append({'action': 'error', 'repo': repo, 'error': str(e)})

    changed = len(enforcement_log)
    print(f'\n  → 강제 적용 완료: 변경 {changed}건 / 일치 {ok_count}건')
    return enforcement_log


# ── Step 3: 워크플로우 데이터 수집 ─────────────────────────────────────────

def get_cron(repo, wf_path):
    """워크플로우 YAML에서 cron 표현식 추출."""
    try:
        data    = gh_get(f'/repos/{GH_USER}/{repo}/contents/{wf_path}')
        content = base64.b64decode(data['content'].replace('\n', '')).decode('utf-8')
        m = re.search(r"cron:\s*[\"']([^\"']+)[\"']", content)
        return m.group(1) if m else None
    except Exception as e:
        print(f'  [cron] {repo}/{wf_path}: {e}')
        return None


def fetch_all_workflow_data():
    """
    강제 적용 이후 모든 워크플로우의 최신 상태와 실행 이력 수집.
    wf.state는 enforce 이후의 실제 GitHub 상태를 반영함.

    GH_PAT 없을 경우: public 저장소만 수집 (private 저장소는 접근 불가)
    """
    print('\n━━━ [데이터 수집] 워크플로우 현황 조회 ━━━')
    if not HAS_PAT:
        print('  ⚠️  GH_PAT 없음 — public 저장소만 수집됩니다.')
    workflows = []
    skipped_repos = []

    for repo in REPOS:
        print(f'\n■ {repo}')
        try:
            wfs = gh_get(f'/repos/{GH_USER}/{repo}/actions/workflows')
            for wf in wfs.get('workflows', []):
                wf_id = wf['id']
                # pages-build-deployment 제외
                if wf['name'] == 'pages-build-deployment':
                    continue
                state_icon = '⏸' if wf['state'] != 'active' else '▶'
                print(f'  {state_icon} {wf["name"]} (ID:{wf_id}, state:{wf["state"]})')

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

        except requests.exceptions.HTTPError as e:
            # 주의: bool(Response)는 status_code >= 400이면 False를 반환하므로
            # 반드시 "is not None" 비교를 사용해야 함
            status_code = e.response.status_code if e.response is not None else 0
            if status_code in (401, 403):
                print(f'  [접근 불가] {repo}: private 저장소 — GH_PAT 필요 (HTTP {status_code})')
                skipped_repos.append(repo)
            else:
                print(f'  [오류] {repo}: HTTP {status_code}: {e}')
        except Exception as e:
            print(f'  [오류] {repo}: {e}')

    if skipped_repos:
        print(f'\n  ⚠️  접근 불가 저장소 {len(skipped_repos)}개: {", ".join(skipped_repos)}')
        print('  ℹ️  GH_PAT 시크릿을 갱신하면 모든 저장소 데이터를 수집할 수 있습니다.')

    return workflows


# ── Step 4: 리포트 파일 수집 ────────────────────────────────────────────────

def fetch_report(repo, report_path):
    try:
        data = gh_get(f'/repos/{GH_USER}/{repo}/contents/{report_path}')
        raw  = base64.b64decode(data['content'].replace('\n', '')).decode('utf-8')
        return json.loads(raw)
    except Exception as e:
        print(f'  [report] {repo}/{report_path}: {e}')
        return None


def fetch_all_reports():
    """워커 레포의 최근 리포트 파일들을 data/reports/ 에 저장."""
    print('\n━━━ [리포트 수집] 최근 실행 결과 파일 ━━━')
    os.makedirs('data/reports', exist_ok=True)
    saved = 0

    for key, report_path in REPORT_MAP.items():
        repo   = key.split('/')[0]
        report = fetch_report(repo, report_path)
        if report:
            out_name = key.replace('/', '_') + '.json'
            with open(f'data/reports/{out_name}', 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f'  → data/reports/{out_name} 저장')
            saved += 1
    print(f'  → 총 {saved}개 리포트 저장 완료')


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    ts = datetime.now(timezone.utc)
    print(f'{"="*55}')
    print(f'  GitHub Actions 오케스트레이터')
    print(f'  실행 시각: {ts.strftime("%Y-%m-%dT%H:%M:%SZ")}')
    print(f'  GH_PAT: {"✅ 설정됨" if HAS_PAT else "❌ 없음 (public 저장소만 수집)"}')
    print(f'{"="*55}')

    # ── Step 1: 의도 파일 로드 ──
    print('\n━━━ [Step 1] 일시정지 의도 파일 로드 ━━━')
    paused_intent = load_paused_intent()
    for wf_id, info in paused_intent.items():
        print(f'  → [{info.get("repo","?")}] {info.get("name","?")} (ID:{wf_id})')

    # ── Step 2: 오케스트레이터 — 상태 강제 적용 ──
    enforcement_log = enforce_workflow_states(paused_intent)

    # ── Step 3: 데이터 수집 (강제 적용 후 실제 상태 반영) ──
    workflows = fetch_all_workflow_data()

    # ── Step 4: 리포트 수집 ──
    fetch_all_reports()

    # ── Step 5: 결과 저장 ──
    os.makedirs('data', exist_ok=True)
    result = {
        'updated_at': ts.isoformat(),
        'orchestrator': {
            'version':        '2.1',
            'enforced_at':    ts.isoformat(),
            'has_pat':        HAS_PAT,
            'paused_intent':  len(paused_intent),
            'enforcement_log': enforcement_log,
        },
        'workflows': workflows,
    }
    with open('data/workflows.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ── 최종 요약 ──
    disabled_wfs = [
        d for d in workflows
        if d['wf']['state'] in ('disabled_manually', 'disabled_inactivity')
    ]
    active_wfs = [d for d in workflows if d['wf']['state'] == 'active']
    print(f'\n{"="*55}')
    print(f'✅ 오케스트레이터 완료')
    print(f'   GH_PAT: {"있음" if HAS_PAT else "없음 (public만)"}')
    print(f'   강제 적용: {len(enforcement_log)}건')
    print(f'   활성 워크플로우: {len(active_wfs)}개')
    print(f'   일시정지 워크플로우: {len(disabled_wfs)}개')
    print(f'   총 {len(workflows)}개 → data/workflows.json 저장')

    # 강제 적용 실패 건 경고 (PAT 있을 때만 실패로 처리)
    if HAS_PAT:
        failures = [e for e in enforcement_log if e.get('action', '').startswith('fail')]
        if failures:
            print(f'\n⚠️  강제 적용 실패 {len(failures)}건:')
            for f in failures:
                print(f'   - [{f["repo"]}] {f.get("name","?")} ({f["action"]})')
            sys.exit(1)  # CI에서 실패 표시


if __name__ == '__main__':
    main()
