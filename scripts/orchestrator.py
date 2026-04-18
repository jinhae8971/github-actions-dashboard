"""
orchestrator.py — GitHub Actions 대시보드 오케스트레이터
=======================================================
역할:
  1. [Step 1] 모든 워크플로우 데이터 수집 (GitHub 실제 상태)
  2. [Step 2] GitHub 실제 상태 → paused.json 자동 동기화
             - GitHub disabled_manually → paused.json에 추가
             - GitHub active           → paused.json에서 제거
             (대시보드/모바일에서 직접 GitHub API로 제어하므로,
              GitHub 실제 상태를 항상 신뢰함)
  3. [Step 3] 리포트 파일 수집
  4. [Step 4] data/workflows.json 저장

아키텍처:
  ┌──────────────────────────────────────────────┐
  │           오케스트레이터 (orchestrator.py)      │
  │  • GitHub 실제 상태 조회 (source of truth)    │
  │  • paused.json 자동 동기화 (상태 기록)        │
  │  • workflows.json 갱신                         │
  └───────────┬──────────────────────────────────┘
              │ 조회 & 기록
    ┌─────────▼─────────┐    ┌─────────────────┐
    │  Worker Repos      │    │  Dashboard       │
    │  (워크플로우)      │    │  (index.html)    │
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
    'kospi-strategy',
    'personal-terminal',
    # Global Market Brief ecosystem (2026-04 추가)
    'crypto-research-agent',
    'kospi-research-agent',
    'sp500-research-agent',
    'nasdaq-research-agent',
    'dow30-research-agent',
    'global-market-orchestrator',
    # TrendSpider Free Clone ecosystem (2026-04 추가)
    'trendline-detector',
    'chart-analyzer',
    'backtest-lab',
]

# 워크플로우 ID → 리포트 파일 매핑
#
# 표준 매핑: 리포트 파일의 상대경로를 지정
# 특수 매핑: "index:<base_path>" 형식으로 시작하면 <base_path>/index.json을 먼저 읽고
#            최신 date의 <base_path>/<date>.json을 가져옴
#            (Global Market Brief 에이전트들이 사용하는 구조)
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
    'kospi-strategy/243217019':             'docs/data/daily_report.json',
    # Global Market Brief ecosystem (index.json + <date>.json 패턴)
    'crypto-research-agent/latest':        'index:docs/reports',
    'kospi-research-agent/latest':         'index:docs/reports',
    'sp500-research-agent/latest':         'index:docs/reports',
    'nasdaq-research-agent/latest':        'index:docs/reports',
    'dow30-research-agent/latest':         'index:docs/reports',
    'global-market-orchestrator/latest':   'index:docs/reports',
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


# ── Step 2: GitHub 실제 상태 → paused.json 자동 동기화 ─────────────────────

def sync_paused_json(workflows):
    """
    GitHub 실제 상태를 source of truth로 하여 paused.json을 자동 갱신.

    - disabled_manually → paused.json에 추가
    - active            → paused.json에서 제거
    - pages-build-deployment, 유틸리티 워크플로우(workflow_dispatch only) 제외

    대시보드/모바일에서 직접 GitHub API로 disable/enable하므로,
    GitHub의 실제 상태를 항상 신뢰한다.

    Returns:
        dict: sync_log (added, removed 목록)
    """
    print('\n━━━ [동기화] GitHub 실제 상태 → paused.json ━━━')

    # 기존 paused.json 로드
    old_paused = load_paused_intent()
    old_ids = set(old_paused.keys())

    # GitHub 실제 상태에서 새 paused map 생성
    new_paused = {}
    for w in workflows:
        wf = w['wf']
        wf_id = str(wf['id'])
        is_disabled = wf['state'] in ('disabled_manually', 'disabled_inactivity')

        if is_disabled:
            # 기존 paused.json에 있으면 기존 정보 유지, 없으면 새로 추가
            if wf_id in old_paused:
                new_paused[wf_id] = old_paused[wf_id]
            else:
                new_paused[wf_id] = {'repo': w['repo'], 'name': wf['name']}

    new_ids = set(new_paused.keys())

    added   = new_ids - old_ids
    removed = old_ids - new_ids

    # 변경 로그
    sync_log = {'added': [], 'removed': []}

    for wf_id in added:
        info = new_paused[wf_id]
        print(f'  ➕ 추가: [{info["repo"]}] {info["name"]} (모바일/외부에서 정지)')
        sync_log['added'].append({'wf_id': wf_id, **info})

    for wf_id in removed:
        info = old_paused[wf_id]
        print(f'  ➖ 제거: [{info["repo"]}] {info["name"]} (모바일/외부에서 재가동)')
        sync_log['removed'].append({'wf_id': wf_id, **info})

    if not added and not removed:
        print('  ✅ paused.json과 GitHub 실제 상태 일치 — 변경 없음')

    # paused.json 저장
    paused_data = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'paused': new_paused,
    }
    with open('data/paused.json', 'w', encoding='utf-8') as f:
        json.dump(paused_data, f, ensure_ascii=False, indent=2)

    total = len(new_paused)
    print(f'\n  → paused.json 갱신 완료: {total}개 일시정지 (추가 {len(added)} / 제거 {len(removed)})')
    return sync_log


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
    """리포트 파일을 가져온다.

    - 일반 경로: 해당 경로의 JSON을 직접 로드
    - 'index:<base_path>' 패턴: <base_path>/index.json을 읽어 최신 date를 찾고
      <base_path>/<latest_date>.json 을 로드 (Global Market Brief 에이전트 패턴)
    """
    try:
        if report_path.startswith('index:'):
            base_path = report_path[len('index:'):]
            # 1) index.json 로드
            index_data = gh_get(f'/repos/{GH_USER}/{repo}/contents/{base_path}/index.json')
            raw_index  = base64.b64decode(index_data['content'].replace('\n', '')).decode('utf-8')
            index_list = json.loads(raw_index)
            if not isinstance(index_list, list) or not index_list:
                print(f'  [report] {repo}/{base_path}/index.json: empty or invalid')
                return None
            # 2) 가장 최신 date 선택 (index.json은 내림차순 정렬된다고 가정)
            latest = index_list[0]
            latest_date = latest.get('date')
            if not latest_date:
                print(f'  [report] {repo}: no date in index.json[0]')
                return None
            # 3) <base_path>/<date>.json 로드
            data = gh_get(f'/repos/{GH_USER}/{repo}/contents/{base_path}/{latest_date}.json')
            raw  = base64.b64decode(data['content'].replace('\n', '')).decode('utf-8')
            report = json.loads(raw)
            # index.json의 메타데이터도 함께 반환 (narrative_tagline 등)
            if isinstance(report, dict) and isinstance(latest, dict):
                # index.json의 요약 필드를 report에 병합 (충돌 시 report 우선)
                for k, v in latest.items():
                    report.setdefault(k, v)
            return report
        else:
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

    # ── Step 1: 워크플로우 데이터 수집 (GitHub 실제 상태) ──
    workflows = fetch_all_workflow_data()

    # ── Step 2: GitHub 실제 상태 → paused.json 자동 동기화 ──
    sync_log = sync_paused_json(workflows)

    # ── Step 3: 리포트 수집 ──
    fetch_all_reports()

    # ── Step 4: 결과 저장 ──
    os.makedirs('data', exist_ok=True)

    disabled_wfs = [
        d for d in workflows
        if d['wf']['state'] in ('disabled_manually', 'disabled_inactivity')
    ]
    active_wfs = [d for d in workflows if d['wf']['state'] == 'active']

    result = {
        'updated_at': ts.isoformat(),
        'orchestrator': {
            'version':        '3.0',
            'synced_at':      ts.isoformat(),
            'has_pat':        HAS_PAT,
            'paused_count':   len(disabled_wfs),
            'sync_log':       sync_log,
        },
        'workflows': workflows,
    }
    with open('data/workflows.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ── 최종 요약 ──
    print(f'\n{"="*55}')
    print(f'✅ 오케스트레이터 완료')
    print(f'   GH_PAT: {"있음" if HAS_PAT else "없음 (public만)"}')
    print(f'   동기화: 추가 {len(sync_log["added"])}건 / 제거 {len(sync_log["removed"])}건')
    print(f'   활성 워크플로우: {len(active_wfs)}개')
    print(f'   일시정지 워크플로우: {len(disabled_wfs)}개')
    print(f'   총 {len(workflows)}개 → data/workflows.json 저장')


if __name__ == '__main__':
    main()


