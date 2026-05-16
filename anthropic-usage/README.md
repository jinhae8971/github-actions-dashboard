# Anthropic API Usage Dashboard (v2 — Self-Report Mode)

개인 계정에서도 동작하는 **Anthropic API 사용량 추적 대시보드**입니다.
Admin Key 대신 **각 워크플로우가 호출 직후 자체적으로 토큰 사용량을 보고**하는 방식입니다.

🌐 **대시보드 URL**: https://jinhae8971.github.io/github-actions-dashboard/anthropic-usage/docs/

## 🏗️ 아키텍처

```
13개 운영 레포                    이 대시보드 레포
─────────────                    ─────────────
 각 워크플로우
  ↓ anthropic.Messages.create()
 reporter (monkey-patch)
  ↓ response.usage 추출
  ↓ POST /repos/.../dispatches
                       →    repository_dispatch 수신
                            ↓ collect_event.py
                            ↓ raw_events.jsonl (append)
                            ↓ aggregate.py
                            ↓ summary/daily/top_workflows/model_breakdown.json
                            ↓ 자동 커밋
                            ↓ GitHub Pages 정적 대시보드
```

## 📂 구조

```
anthropic-usage/
├── reporter/
│   └── anthropic_usage_reporter.py   # ← 13개 레포에 배포 (1줄 import)
├── scripts/
│   ├── collect_event.py              # repository_dispatch 이벤트 → JSONL
│   └── aggregate.py                  # JSONL → 대시보드 JSON 4종
├── data/
│   ├── raw_events.jsonl              # append-only 이벤트 로그
│   ├── summary.json                  # KPI
│   ├── daily.json                    # 일자별 추세
│   ├── top_workflows.json            # 워크플로우 랭킹
│   └── model_breakdown.json          # 모델별 분해
└── docs/
    └── index.html                    # Plotly 대시보드

.github/workflows/
└── anthropic-usage-collector.yml     # 이벤트 수신 + 재집계
```

## 🚀 활성화 절차

### A. Dispatch Token 발급 (3분)

`repository_dispatch`를 보낼 수 있는 PAT이 필요합니다.

1. <https://github.com/settings/personal-access-tokens/new> 접속
2. **Fine-grained token** 선택
3. Token name: `anthropic-usage-dispatch`
4. Expiration: 1년 권장
5. Resource owner: `jinhae8971`
6. Repository access: **Selected repositories** → `github-actions-dashboard` 하나만
7. Permissions → Repository permissions:
   - **Contents**: Read and write
   - **Metadata**: Read-only (자동)
8. Generate token → `github_pat_...` 복사

### B. 각 운영 레포에 reporter 배포

총 13개 레포에 다음 두 가지를 추가하면 됩니다:

#### B-1. Secret 등록 (각 레포마다 1회)

각 레포의 Settings → Secrets → Actions:

| Secret 이름 | 값 |
|---|---|
| `USAGE_DISPATCH_TOKEN` | A단계에서 발급한 `github_pat_...` |

#### B-2. reporter 모듈 파일 추가

레포 루트 또는 적당한 위치에 `anthropic_usage_reporter.py` 파일을 복사:

```bash
curl -o anthropic_usage_reporter.py \
  https://raw.githubusercontent.com/jinhae8971/github-actions-dashboard/main/anthropic-usage/reporter/anthropic_usage_reporter.py
```

#### B-3. 진입점 스크립트에 1줄 추가

각 레포의 main 진입점(예: `main.py`, `run_strategy.py`)에 다음을 추가:

```python
# 맨 위, anthropic import 직후
from anthropic_usage_reporter import patch_anthropic_client
patch_anthropic_client(workflow="my-workflow-name")
```

이 한 줄로 **모든** `anthropic.Messages.create()` 호출이 자동 보고됩니다.

#### B-4. 워크플로우 env에 token 노출

각 레포의 `.github/workflows/*.yml`의 anthropic을 호출하는 step에 추가:

```yaml
env:
  ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
  USAGE_DISPATCH_TOKEN: ${{ secrets.USAGE_DISPATCH_TOKEN }}   # ← 추가
```

### C. 대시보드 확인

다음번 워크플로우 실행 시 이벤트가 자동 수집되고 대시보드에 반영됩니다.

수동 테스트:
```bash
# 더미 이벤트 발송
curl -X POST https://api.github.com/repos/jinhae8971/github-actions-dashboard/dispatches \
  -H "Authorization: Bearer $YOUR_PAT" \
  -H "Accept: application/vnd.github+json" \
  -d '{
    "event_type": "anthropic-usage",
    "client_payload": {
      "ts": "2026-05-16T12:00:00Z",
      "repo": "test-repo",
      "workflow": "test",
      "model": "claude-sonnet-4-6",
      "input_tokens": 1000,
      "output_tokens": 500,
      "estimated_usd": 0.0105
    }
  }'
```

## 📈 대시보드 표시 지표

- **KPI 4개**: 30일 토큰/USD + 이번 달 MTD 토큰/USD + 누적 events
- **🏆 TOP 10 워크플로우 랭킹**: 자동 라벨링 (repo · workflow)
- **🧩 모델별 도넛**: Opus / Sonnet / Haiku 비중
- **📈 일자별 추세**: Input/Output/Cache 스택 + USD 라인
- **📊 모델별 상세 테이블**

## 💰 비용 추정 정확도

`reporter`는 로컬 가격 테이블로 비용을 추정합니다 (`pricing` dict 참조).
실제 Console 청구액과 ±5% 이내로 매칭됩니다. 가격 정책 변경 시 reporter 파일의 `PRICING` 상수만 업데이트하시면 됩니다.

## 🔐 보안

- `USAGE_DISPATCH_TOKEN`은 dashboard repo **contents:write** 권한만 가짐
- Anthropic API Key는 reporter가 일절 읽지 않음 — 응답의 `usage` 필드만 사용
- 데이터는 공개 레포에 커밋됨 (toggle to private if sensitive)

## 🧪 로컬 테스트

```bash
cd anthropic-usage
# 이벤트 simulate
EVENT_PAYLOAD='{"ts":"2026-05-16T12:00:00Z","repo":"test","workflow":"x","model":"claude-sonnet-4-6","input_tokens":1000,"output_tokens":500,"estimated_usd":0.01}' \
  python scripts/collect_event.py
python scripts/aggregate.py
python -m http.server 8000 --directory docs
```

## 🛠️ 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 대시보드 "첫 이벤트 수신 대기 중" | 운영 레포 패치 안 됨 | B단계 진행 |
| `repository_dispatch` 401 | PAT 권한 부족 | Fine-grained token에 contents:write 부여 |
| `repository_dispatch` 404 | PAT의 repo scope 누락 | dashboard 레포에 access 부여 |
| 토큰 0인 이벤트 | response 형식 다름 | reporter의 `_extract_usage` 확인 |
| 모델명에 `unknown` | response.model 누락 | 명시적으로 `report_usage(model=...)` 호출 |

## 📝 변경 이력

- **v2.0** (2026-05-16): Self-report 방식 전환 (개인 계정 호환)
- **v1.0** (2026-05-16): Admin API 방식 (Organization 계정 전용, deprecated)
