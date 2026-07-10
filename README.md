# XAgent Pay API

AI 에이전트와 개발자를 위한 XRPL 결제 API

## 소개

FastAPI 기반의 XRPL(XRP Ledger) 테스트넷 결제 서버입니다. 복잡한 블록체인 로직을 추상화하여 AI 에이전트와 애플리케이션이 XRP 및 RLUSD 결제를 손쉽게 통합할 수 있습니다.

- **지원 통화:** XRP, RLUSD (스테이블코인)
- **인증:** 발급/폐기 가능한 API 키, tier별 요금·한도
- **지갑:** API 키 발급 시 전용 XRPL 지갑 자동 생성/펀딩 (에이전트별 분리 운용)
- **관측:** 사용량 대시보드(웹 UI), 트랜잭션 내역, 누적 수수료 조회
- **알림:** 결제 성공/실패 시 Webhook 콜백 (서명 검증 + 재시도)

## 빠른 시작

```bash
# 1. 저장소 클론 & 의존성 설치
pip install -r requirements.txt

# 2. .env 파일 생성 (.env.example 복사 후 값 입력)
cp .env.example .env
```

`.env`에 최소한 아래 값을 채워야 서버가 기동됩니다:

```bash
SENDER_ADDRESS=테스트넷_XRP_주소       # 플랫폼 공용 지갑 (레거시 키 폴백용)
SENDER_SECRET=시크릿_키
FEE_ACCOUNT=수수료_수신_주소
XRPL_NODE=wss://s.altnet.rippletest.net:51233
ADMIN_API_KEY=강력한_관리자_키          # API 키 발급/폐기용 (없으면 /admin/keys 비활성화)
```

테스트넷 계정이 없다면 [XRPL Faucet](https://xrpl.org/xrp-testnet-faucet.html)에서 발급받으세요.

```bash
# 3. 서버 실행
python main.py
# 또는
uvicorn main:app --host 0.0.0.0 --port 8000

# 프로덕션 (단, 아래 "알려진 제한사항" 참고 — 현재는 단일 워커 기준으로 설계됨)
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

- API: http://localhost:8000
- Swagger 문서: http://localhost:8000/docs
- 사용량 대시보드: http://localhost:8000/dashboard

```bash
# 4. 첫 API 키 발급 (관리자 키로 1회 실행)
curl -X POST "http://localhost:8000/admin/keys" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your_admin_key" \
  -d '{"name": "my-first-agent", "tier": "free"}'
```

응답으로 받은 `api_key`가 이후 모든 요청에 쓸 `X-API-Key` 값입니다. **이 응답에서만 평문으로 확인 가능**하니 안전한 곳에 보관하세요. 같은 응답의 `wallet_address`는 이 키 전용으로 자동 생성/펀딩된 지갑 주소입니다.

## 가격 정책

| Tier | 가격 | 월 요청 한도 | 결제 수수료율 |
|---|---|---|---|
| Free | $0 | 100건 | 1% |
| Pro | $49/월 | 무제한 | 0.15% |
| Enterprise | 커스텀 | 무제한 | 커스텀 협의 (볼륨에 따라 조정) |

- Pro의 $49/월 구독료는 이 API가 직접 처리하지 않습니다 (별도 SaaS 과금 레이어에서 처리).
- 이 API가 실제로 적용하는 것은 **결제 트랜잭션당 수수료율**뿐입니다.
- Enterprise는 키 발급 시 `fee_rate`를 지정해 tier 기본값을 덮어쓸 수 있습니다.
- 현재 적용 중인 tier별 요율은 `GET /payment/rates`에서 언제든 확인할 수 있습니다.

## 인증 — API 키 발급/조회/폐기

키 발급·폐기는 관리자 전용(`X-Admin-Key` 헤더)이고, 그 외 모든 API는 발급받은 키(`X-API-Key` 헤더)로 호출합니다.

```bash
# 키 발급 (전용 지갑 자동 생성 포함)
curl -X POST "http://localhost:8000/admin/keys" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your_admin_key" \
  -d '{"name": "customer-a-bot", "tier": "pro"}'

# 키 목록 조회 (평문 키는 노출되지 않음)
curl "http://localhost:8000/admin/keys" -H "X-Admin-Key: your_admin_key"

# 키 폐기
curl -X POST "http://localhost:8000/admin/keys/{key_id}/revoke" \
  -H "X-Admin-Key: your_admin_key"
```

| 코드 | 설명 |
|------|------|
| 401 | API 키 없음 |
| 403 | API 키가 유효하지 않거나 폐기됨 |
| 429 | tier 월간 한도 초과 |
| 503 | `ADMIN_API_KEY` 미설정으로 관리자 API 비활성화 |

## 지갑 관리 (멀티 에이전트)

API 키를 발급하면 XRPL 테스트넷 faucet으로 **전용 지갑이 자동 생성/펀딩**됩니다. 이후 그 키로 실행하는 모든 결제는 플랫폼 공용 지갑이 아니라 **키 전용 지갑**에서 나갑니다 — 여러 에이전트가 동시에 결제해도 지갑(=XRPL 시퀀스 번호)이 분리되어 있어 충돌하지 않습니다.

```bash
curl "http://localhost:8000/wallet/info" -H "X-API-Key: your_api_key"
```

```json
{
  "wallet_address": "r...",
  "balance_xrp": 998.5,
  "dedicated": true
}
```

`dedicated: false`이면 전용 지갑 생성/펀딩에 실패했거나(테스트넷 faucet rate limit 등) `.env`의 `API_KEYS`로 마이그레이션된 레거시 키라 플랫폼 공용 지갑을 공유하는 상태입니다.

## 결제 API

모든 결제 API는 `X-API-Key` 헤더가 필요합니다.

### 결제 생성

**XRP 결제:**
```bash
curl -X POST "http://localhost:8000/payment/create" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{
    "recipient_address": "rExampleAddress...",
    "amount": 10.0,
    "currency": "XRP"
  }'
```

**RLUSD 결제:**
```bash
curl -X POST "http://localhost:8000/payment/create" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{
    "recipient_address": "rExampleAddress...",
    "amount": 100.0,
    "currency": "RLUSD"
  }'
```

⚠️ **RLUSD 결제 전 주의사항:** 수신자가 먼저 RLUSD 토큰에 대한 trust line을 설정해야 합니다.

**Response:** (수수료율은 API 키 tier에 따라 달라집니다 — 아래는 Pro tier 예시)
```json
{
  "success": true,
  "tx_hash": "트랜잭션_해시",
  "fee_amount": 0.015,
  "fee_rate": 0.0015,
  "sent_amount": 9.985,
  "remaining_quota": null
}
```

### 결제 검증 / 상태 조회

```bash
curl "http://localhost:8000/payment/verify/{tx_hash}" -H "X-API-Key: your_api_key"
curl "http://localhost:8000/payment/status/{tx_hash}" -H "X-API-Key: your_api_key"
```

### 지원 통화 및 수수료율 확인 (인증 불필요)

```bash
curl "http://localhost:8000/payment/rates"
```

```json
{
  "supported_currencies": {
    "XRP": {"currency": "XRP", "issuer": null, "scale": 6},
    "RLUSD": {"currency": "RLUSD", "issuer": "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De", "scale": 5}
  },
  "default_currency": "XRP",
  "fee_rates_by_tier": {"free": 0.01, "pro": 0.0015, "enterprise": 0.0015}
}
```

## 사용량 대시보드

브라우저에서 http://localhost:8000/dashboard 를 열고 API 키를 입력하면 tier, 이번 달 요청 수/남은 quota, 통화별 누적 수수료, 최근 트랜잭션 내역, 지갑 주소/잔액을 한 화면에서 확인할 수 있습니다.

같은 데이터를 API로도 조회 가능합니다:

```bash
# quota + 누적 수수료 + 최근 트랜잭션 (대시보드 페이지가 호출하는 것과 동일)
curl "http://localhost:8000/usage/dashboard" -H "X-API-Key: your_api_key"

# 트랜잭션 내역만
curl "http://localhost:8000/usage/transactions?limit=50" -H "X-API-Key: your_api_key"

# quota만
curl "http://localhost:8000/usage/info" -H "X-API-Key: your_api_key"
```

## Rate Limiting

- **Free:** 월 100건 초과 시 `429 Too Many Requests`
- **Pro / Enterprise:** 무제한 (요청 수 기준 제한 없음, 수수료로 과금)
- 한도는 `FREE_MONTHLY_LIMIT` 환경변수로 조정 가능

## Webhook 알림

결제 성공(`payment.success`) / 실패(`payment.failed`) 시 지정한 URL로 이벤트를 전송합니다. 실패하면 2초·10초·60초 간격으로 최대 3회 재시도합니다.

```bash
# 등록 (등록할 때마다 서명 secret이 새로 발급되며, 이 응답에서만 확인 가능)
curl -X PUT "http://localhost:8000/webhook" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"url": "https://your-server.com/xagent-webhook"}'

# 조회
curl "http://localhost:8000/webhook" -H "X-API-Key: your_api_key"

# 삭제
curl -X DELETE "http://localhost:8000/webhook" -H "X-API-Key: your_api_key"
```

수신 서버에서는 `X-XAgent-Signature: sha256=<hmac>` 헤더로 위변조 여부를 검증하세요:

```python
import hmac, hashlib

expected = hmac.new(webhook_secret.encode(), request_body, hashlib.sha256).hexdigest()
is_valid = hmac.compare_digest(expected, received_signature.removeprefix("sha256="))
```

내부/사설 IP(localhost, 사내망 등)는 SSRF 방지를 위해 webhook URL로 등록할 수 없습니다.

## x402 결제

AI 에이전트를 위한 HTTP 402 Payment Required 표준 지원

```bash
# 1. 결제 필요 리소스 요청
curl "http://localhost:8000/data/market-info"
# → 402 Payment Required + 결제 정보 헤더

# 2. x402 결제 생성
curl -X POST "http://localhost:8000/x402/create-payment" \
  -H "X-API-Key: your_api_key"

# 3. 액세스 토큰 발급
curl -X POST "http://localhost:8000/x402/pay" \
  -H "Content-Type: application/json" \
  -d '{"tx_hash": "트랜잭션_해시"}'

# 4. 토큰으로 리소스 접근
curl "http://localhost:8000/data/market-info" \
  -H "X-Payment-Token: access_token"
```

## RLUSD Trust Line 설정 가이드

### Trust Line이란?

Trust Line은 XRPL에서 IOU 토큰(예: RLUSD)을 주고받기 위해 설정해야 하는 허용 한도입니다. 발행자별로 trust line을 설정해야 해당 토큰을 수신할 수 있습니다.

### Trust Line 설정 방법

#### 1. Xaman 지갑 사용 (추천)

```
1. Xaman 지갑 접속 (https://xaman.app)
2. 테스트넷 설정 → "I want to add a trust line"
3. 아래 정보 입력:
   - Currency: USD
   - Issuer: rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De
4. Trust Line 한도 설정 (예: 1000)
5. 확인 및 설정
```

#### 2. XRPL Explorer 사용

```
1. XRPL Testnet Explorer 접속 (https://testnet.xrpl.org)
2. 지갑 주소 검색
3. "Trust Lines" 탭 → "Add Trust Line"
4. Currency: USD, Issuer: rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De
5. 한도 설정 후 추가
```

### Trust Line 확인

```bash
curl "http://localhost:8000/payment/trustline/{address}" \
  -H "X-API-Key: your_api_key"
```

**Response (Trust Line 없음):**
```json
{
  "address": "rExampleAddress...",
  "has_rlUSD_trustline": false,
  "rlUSD_limit": null,
  "rlUSD_balance": null,
  "message": "RLUSD trust line이 설정되지 않았습니다."
}
```

### Trust Line 없는 경우 에러

RLUSD 결제 시 수신자가 trust line을 설정하지 않았다면 아래와 같은 에러가 반환됩니다:

```json
{
  "detail": "수신자가 RLUSD 토큰에 대한 trust line을 설정하지 않았습니다. 수신자가 먼저 RLUSD를 받을 수 있도록 trust line을 설정해야 합니다."
}
```

**해결 방법:** 수신자에게 위 Trust Line 설정 가이드를 공유하고 trust line을 설정하도록 안내하세요.

## Claude MCP 연동

Claude AI가 XAgent Pay API를 직접 툴로 호출할 수 있습니다.

### 설치 및 실행

```bash
# XAgent Pay API 서버 시작
python main.py

# MCP 서버 시작 (별도 터미널)
python mcp_server.py
```

`.env`에 MCP가 사용할 API 키를 지정하세요:

```bash
MCP_API_KEY=your_api_key
```

### Claude Desktop 설정

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "xagent-pay-api": {
      "command": "python",
      "args": ["/path/to/mcp_server.py"],
      "env": {
        "XAGENT_PAY_API_URL": "http://localhost:8000",
        "MCP_API_KEY": "your_api_key"
      }
    }
  }
}
```

### 사용 가능한 툴

- **get_rates** — 지원 통화 및 수수료 조회
- **create_payment** — XRP/RLUSD 결제 생성
- **verify_payment** — 트랜잭션 검증
- **check_trustline** — RLUSD Trust Line 확인

### 데모

Claude AI가 직접 1 XRP 송금한 실제 결과:
- 수신 주소: rM9SpkNUPUygwTcE7baTYTeZWP6BwhKePK
- 실제 송금액: 0.99 XRP
- 수수료: 0.01 XRP (1%)
- TX 해시: CB2AC710B2EA8E335FB7EBEB258306CE96C30C0F09ABD728087C6099AC28D9AB

## 로드맵

- [x] x402 토큰 지원
- [x] RLUSD(스테이블코인) 지원
- [x] MCP 서버 지원 (Claude AI 연동)
- [x] 발급/폐기 가능한 API 키 + tier별 인증
- [x] 사용량 대시보드
- [x] Rate Limiting + 멀티 지갑 관리
- [x] Webhook 알림
- [ ] 추가 IOU 토큰 지원
- [ ] 메인넷 배포
- [ ] 배치 결제

## 알려진 제한사항

- 현재 API 키/트랜잭션/webhook 설정은 JSON 파일 기반으로 저장됩니다. 단일 프로세스(`--workers 1`) 기준으로 안전하며, 여러 워커/인스턴스로 스케일아웃하려면 SQLite 등으로 마이그레이션이 필요합니다 (자세한 내용은 [TODO_MIGRATION.md](TODO_MIGRATION.md) 참고).
- 현재 테스트넷 전용입니다. 메인넷 전환 시 추가 보안 검토가 필요합니다.

## 보안

- **전용 지갑 시크릿(seed)은 `SECRET_ENCRYPTION_KEY`(Fernet)로 암호화되어 저장됩니다.** 이 키가 없으면 전용 지갑 생성 자체가 비활성화됩니다(평문 저장 방지). 마스터 키는 절대 코드에 하드코딩하지 말고 `.env`로만 관리하세요.
- `.env`의 `SENDER_SECRET`(플랫폼 공용 지갑)은 여전히 평문입니다 — 서버 부팅 시 필요한 부트스트랩 credential이라 이 앱의 저장소 암호화 범위 밖입니다. 메인넷 전환 전 KMS/Secrets Manager 연동을 검토하세요.

⚠️ **현재 테스트넷 전용**입니다. 메인넷 사용 시 아래를 추가로 검토하세요:
- API 키/관리자 키 저장소를 SQLite 등으로 마이그레이션 후 접근 통제 강화
- Webhook 대상 URL의 SSRF 방지 로직(현재 사설/루프백 IP 차단 적용됨) 및 DNS 리바인딩 방어 보강

## 라이선스

MIT License

## GitHub 리포지토리

이 프로젝트는 GitHub에서 관리됩니다. 버그 신고 및 기능 요청은 Issues를 통해 제출해주세요.

---

문의: [GitHub Issues](https://github.com/TLSRUF/xagent-pay-api/issues)
