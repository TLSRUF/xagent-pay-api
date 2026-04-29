# XAgent Pay API

AI 에이전트와 개발자를 위한 XRPL 결제 API

## 소개

FastAPI 기반의 XRPL(XRP Ledger) 테스트넷 결제 서버입니다. 복잡한 블록체인 로직을 추상화하여 AI 에이전트와 애플리케이션이 XRP 및 RLUSD 결제를 손쉽게 통합할 수 있습니다.

**지원 통화:** XRP, RLUSD (스테이블코인)

## 설치

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정 (.env 파일)
SENDER_ADDRESS=테스트넷_XRP_주소
SENDER_SECRET=시크릿_키
FEE_ACCOUNT=수수료_수신_주소
XRPL_NODE=wss://s.altnet.rippletest.net:51233
RLUSD_ISSUER=rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De
```

테스트넷 계정: [XRPL Faucet](https://xrpl.org/xrp-testnet-faucet.html)

## 실행

```bash
# 개발 모드
python main.py

# 프로덕션
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

- API: http://localhost:8000
- Swagger 문서: http://localhost:8000/docs

## API 사용법

모든 요청은 API 키 인증이 필요합니다. 헤더에 `X-API-Key`를 포함해야 합니다.

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

**RLUSD 결제 전 주의사항:** 수신자가 먼저 RLUSD 토큰에 대한 trust line을 설정해야 합니다.

**Response:**
```json
{
  "success": true,
  "tx_hash": "트랜잭션_해시",
  "fee_amount": 0.1,
  "sent_amount": 9.9
}
```

### 결제 검증

```bash
curl "http://localhost:8000/payment/verify/{tx_hash}" \
  -H "X-API-Key: your_api_key"
```

### 상태 조회

```bash
curl "http://localhost:8000/payment/status/{tx_hash}" \
  -H "X-API-Key: your_api_key"
```

### 지원 통화 확인

```bash
curl "http://localhost:8000/payment/rates"
```

**Response:**
```json
{
  "supported_currencies": {
    "XRP": {"currency": "XRP", "issuer": null, "scale": 6},
    "RLUSD": {"currency": "RLUSD", "issuer": "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De", "scale": 5}
  },
  "default_currency": "XRP",
  "fee_rate": 0.01
}
```

### x402 결제

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

### 인증 에러

| 코드 | 설명 |
|------|------|
| 401 | API 키 없음 또는 유효하지 않음 |
| 403 | API 키 권한 부족 |

## 수수료 구조

| 구분 | 비율 |
|------|------|
| 애플리케이션 수수료 | 1% |
| 네트워크 수수료 | 0.00001 XRP (XRPL 기본) |

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
# 특정 주소의 RLUSD trust line 확인
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

**Response (Trust Line 있음):**
```json
{
  "address": "rExampleAddress...",
  "has_rlUSD_trustline": true,
  "rlUSD_limit": 1000.0,
  "rlUSD_balance": 50.0,
  "message": "RLUSD trust line이 설정되어 있습니다."
}
```

### Trust Line 없는 경우 에러

```bash
# RLUSD 결제 시도 (수신자가 trust line 없음)
curl -X POST "http://localhost:8000/payment/create" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{
    "recipient_address": "rReceiverWithoutTrustline...",
    "amount": 100.0,
    "currency": "RLUSD"
  }'
```

**Error Response:**
```json
{
  "detail": "수신자가 RLUSD 토큰에 대한 trust line을 설정하지 않았습니다. 수신자가 먼저 RLUSD를 받을 수 있도록 trust line을 설정해야 합니다."
}
```

**해결 방법:** 수신자에게 위 Trust Line 설정 가이드를 공유하고 trust line을 설정하도록 안내하세요.

**예시:** 100 XRP 또는 100 RLUSD 결제 시
- 수수료: 1 (해당 통화)
- 전송금액: 99 (해당 통화)

## Claude MCP 연동

Claude AI가 XAgent Pay API를 직접 툴로 호출할 수 있습니다.

### 설치

mcp_server.py를 Claude Desktop 설정에 추가:

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

- **get_rates**: 지원 통화 및 수수료 조회
- **create_payment**: XRP/RLUSD 결제 생성
- **verify_payment**: 트랜잭션 검증
- **check_trustline**: RLUSD Trust Line 확인

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
- [ ] 추가 IOU 토큰 지원
- [ ] 메인넷 배포
- [ ] 웹훅 알림
- [ ] 배치 결제

## MCP 서버 (Claude AI 연동)

XAgent Pay API를 Claude AI가 직접 사용할 수 있는 MCP 서버를 제공합니다.

### 설치 및 설정

```bash
# MCP 패키지 설치
pip install -r requirements.txt

# .env 파일에 MCP API 키 설정
MCP_API_KEY=test_key_123456
```

### MCP 서버 실행

```bash
# XAgent Pay API 서버 시작
python main.py

# MCP 서버 시작 (다른 터미널)
python mcp_server.py
```

### Claude Desktop 설정

Claude Desktop 설정 파일에 다음 내용을 추가하세요:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "xagent-pay-api": {
      "command": "python",
      "args": ["C:/XRPL_MVP/mcp_server.py"],
      "env": {
        "XAGENT_PAY_API_URL": "http://localhost:8000",
        "MCP_API_KEY": "test_key_123456"
      }
    }
  }
}
```

### 사용 가능한 MCP 툴

1. **create_payment** - XRP/RLUSD 결제 생성
2. **verify_payment** - 결제 트랜잭션 검증
3. **check_trustline** - RLUSD Trust Line 확인
4. **get_rates** - 지원 통화 및 수수료 정보 조회

### Claude에서 사용 예시

```
"100 XRP를 rAddress...로 전송해줘"
"최신 결제 내역을 검증해줘"
"RLUSD trust line을 확인해줘"
"지원하는 통화와 수수료율 알려줘"
```

## 보안

**현재 테스트넷 전용**입니다. 메인넷 사용 시 보안 강화가 필요합니다:
- 인증/인가 시스템
- Rate Limiting
- 시크릿 키 암호화 저장

## 라이선스

MIT License

## GitHub 리포지토리

이 프로젝트는 GitHub에서 관리됩니다. 버그 신고 및 기능 요청은 Issues를 통해 제출해주세요.

---

문의: [GitHub Issues](https://github.com/TLSRUF/xagent-pay-api/issues)
