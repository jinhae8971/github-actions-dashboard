# Anthropic API Usage Dashboard

GitHub Actions 워크플로우별 Anthropic API 사용량을 추적하는 서버리스 대시보드입니다.
`github-actions-dashboard` 레포의 `anthropic-usage/` 서브디렉터리에 자기완결적으로 배치됩니다.

🌐 **대시보드 URL**: https://jinhae8971.github.io/github-actions-dashboard/anthropic-usage/docs/

## 🏗️ 구조

```
anthropic-usage/
├── scripts/
│   └── fetch_usage.py          # Admin API 호출 + 4종 JSON 집계
├── data/                        # Git as DB (자동 갱신)
│   ├── key_mapping.json        # ⚠️ 영길님이 Console에서 api_key_id 채우기
│   ├── summary.json            # 자동 생성
│   ├── daily.json              # 자동 생성
│   ├── top_workflows.json      # 자동 생성
│   └── model_breakdown.json    # 자동 생성
└── docs/
    └── index.html              # Plotly 정적 대시보드

.github/workflows/
└── anthropic-usage-tracker.yml # 매일 07:45 KST 실행 (orchestrator와 15분 시간차)
```

## 🚀 활성화 (영길님이 직접 하셔야 하는 단계)

### Step 1: Admin API Key 발급
1. <https://console.anthropic.com/settings/keys> 접속
2. **Create Key** 클릭 → Type을 **Admin** 으로 선택
3. 발급된 `sk-ant-admin-...` 키 복사 (한 번만 보입니다)

### Step 2: GitHub Secret 등록
1. <https://github.com/jinhae8971/github-actions-dashboard/settings/secrets/actions> 접속
2. **New repository secret** 클릭
3. Name: `ANTHROPIC_ADMIN_API_KEY` / Value: 위에서 복사한 키
4. 저장

### Step 3: 첫 실행
- 자동: 매일 **07:45 KST** (기존 orchestrator 07:30과 15분 시간차)
- 수동: <https://github.com/jinhae8971/github-actions-dashboard/actions/workflows/anthropic-usage-tracker.yml> → **Run workflow**

약 1분 후 `data/*.json` 4개 파일이 자동 커밋되고 대시보드가 채워집니다.

### Step 4 (선택): API Key ID 매핑 채우기
가독성 향상용. 건너뛰어도 대시보드는 동작합니다.

1. Console → API Keys 페이지에서 각 활성 키의 ID(`apikey_01...`) 확인
2. `anthropic-usage/data/key_mapping.json` 편집:
   - placeholder 키(`__REPLACE_WITH_apikey_01_for_<repo>`)를 실제 ID로 교체
   - 사용하지 않는 레포 항목은 통째로 삭제
3. 커밋 & 푸시

## 📊 영길님 운영 환경 사전 매핑 결과

현재 영길님 GitHub 계정에서 **Anthropic API를 사용 중인 레포는 13개**로 자동 식별되었습니다:

| 상태 | 레포 | 워크플로우 |
|---|---|---|
| 🟢 active | `stock-dashboard` | Hourly Market Data Update |
| 🟢 active | `nasdaq-quant-analyzer` | NASDAQ Quant Analyzer Daily |
| 🟢 active | `kospi-morning-briefing` | KOSPI 모닝브리핑 |
| 🟢 active | `multi-agent-researcher` | Multi-Agent Research |
| 🟢 active | `kospi-strategy` | KOSPI Strategy Daily |
| ⚪ paused | `global-market-orchestrator` | Daily Global Orchestrator |
| ⚪ paused | `kospi-research-agent` | Daily KOSPI Research |
| ⚪ paused | `nasdaq-research-agent` | Daily NASDAQ-100 Research |
| ⚪ paused | `sp500-research-agent` | Daily S&P 500 Research |
| ⚪ paused | `dow30-research-agent` | Daily Dow 30 Research |
| ⚪ paused | `crypto-research-agent` | Daily Crypto Research |
| ⚪ paused | `korean-stock-agent` | Korean Stock Agent |
| ⚪ paused | `us-market-agent` | US Market Agent |

→ `key_mapping.json`에 이 13개 항목이 사전 작성되어 있으니, **api_key_id만 교체**하시면 됩니다.

## 📈 대시보드 표시 지표

- **KPI 4개**: 30일 누적 토큰/USD + 이번 달 MTD 토큰/USD
- **🏆 TOP 10 워크플로우 랭킹**: api_key_id → 레포 매핑된 라벨로 표시
- **🧩 모델별 도넛**: Opus / Sonnet / Haiku 비중
- **📈 일자별 추세**: Input/Output/Cache 스택 막대 + USD 라인 (이중 Y축)
- **📊 모델별 상세 테이블**: input/output/total tokens + USD per model

## 🔄 갱신 주기

| 트리거 | 시각 | 설명 |
|---|---|---|
| 정기 실행 | 매일 07:45 KST | `45 22 * * *` UTC |
| 수동 실행 | 즉시 | Actions 탭 → Run workflow |
| 코드 변경 | 즉시 | `fetch_usage.py` / `key_mapping.json` push 시 |

## 🔐 보안 노트

- Admin Key는 조직 단위 권한이라 일반 API 키보다 훨씬 강력합니다.
- 데이터는 공개 레포에 커밋됩니다. 노출되는 정보는 토큰 수와 USD 금액뿐이며, API 키 본문(`sk-ant-...`)은 절대 포함되지 않습니다.
- 민감하다고 판단되시면 레포를 private으로 전환하세요.

## 🧪 로컬 테스트

```bash
cd anthropic-usage
export ANTHROPIC_ADMIN_API_KEY="sk-ant-admin-..."
pip install requests
python scripts/fetch_usage.py
python -m http.server 8000 --directory docs
```

## 📝 변경 이력

- **v1.0** (2026-05-16): 초기 빌드. 13개 레포 사전 매핑 완료.
