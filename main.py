"""
XRPL Payment API Server
FastAPI 기반 XRPL 결제 서비스
API 키 인증, 사용량 제한, 요청 로깅 포함
"""

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from xrpl.clients import WebsocketClient
from xrpl.wallet import Wallet
from xrpl.models.transactions import Payment
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.transaction import autofill_and_sign, submit
from xrpl.models.requests.account_info import AccountInfo
from xrpl.models.requests.tx import Tx
from xrpl.models.requests.account_lines import AccountLines
import os
from dotenv import load_dotenv
from typing import Optional, Dict, List
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
import asyncio
import json
import logging
from pathlib import Path
from functools import lru_cache
import threading
import jwt
import secrets

# 환경변수 로드
load_dotenv()

app = FastAPI(
    title="XAgent Pay API",
    description="XRPL 기반 결제 API 서비스 - API 키 인증, 사용량 제한, 로깅, x402 지원",
    version="2.0.0"
)

# 환경변수 설정
SENDER_ADDRESS = os.getenv("SENDER_ADDRESS")
SENDER_SECRET = os.getenv("SENDER_SECRET")
FEE_ACCOUNT = os.getenv("FEE_ACCOUNT")
XRPL_NODE = os.getenv("XRPL_NODE", "wss://s.altnet.rippletest.net:51233")
API_KEYS = os.getenv("API_KEYS", "").split(",") if os.getenv("API_KEYS") else []
MONTHLY_REQUEST_LIMIT = int(os.getenv("MONTHLY_REQUEST_LIMIT", "100"))
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))  # JWT 서명 키
X402_PAYMENT_AMOUNT = float(os.getenv("X402_PAYMENT_AMOUNT", "0.1"))  # x402 결제 금액
X402_FEE_ADDRESS = os.getenv("X402_FEE_ADDRESS", FEE_ACCOUNT)  # x402 수수료 수신 주소

# RLUSD 스테이블코인 설정
RLUSD_ISSUER = os.getenv("RLUSD_ISSUER", "rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De")  # RLUSD 발행자 주소
RLUSD_CURRENCY = os.getenv("RLUSD_CURRENCY", "USD")  # RLUSD 통화 코드

# 지원 통화 설정
SUPPORTED_CURRENCIES = {
    "XRP": {"currency": "XRP", "issuer": None, "scale": 6},  # 1 XRP = 1,000,000 drops
    "RLUSD": {"currency": RLUSD_CURRENCY, "issuer": RLUSD_ISSUER, "scale": 5}  # 소수점 5자리
}

# 필수 환경변수 검증
if not all([SENDER_ADDRESS, SENDER_SECRET, FEE_ACCOUNT]):
    raise ValueError("필수 환경변수가 설정되지 않았습니다. .env 파일을 확인해주세요.")

# API 키 검증
if not API_KEYS:
    print("경고: API_KEYS가 설정되지 않았습니다. .env 파일에 API_KEYS를 설정해주세요.")

# 폴더 생성
Path("logs").mkdir(exist_ok=True)
Path("usage").mkdir(exist_ok=True)

# ============= 로깅 시스템 =============

class RequestLogger:
    """요청 로깅 시스템"""

    def __init__(self):
        self.log_dir = Path("logs")
        self.lock = threading.Lock()

    def get_log_file_path(self) -> Path:
        """오늘 날짜의 로그 파일 경로 반환"""
        today = datetime.now().strftime("%Y-%m-%d")
        return self.log_dir / f"api_{today}.log"

    def log_request(
        self,
        timestamp: str,
        api_key: str,
        endpoint: str,
        method: str,
        success: bool,
        status_code: int,
        error_message: str = ""
    ):
        """요청 정보를 로그 파일에 기록"""
        log_entry = {
            "timestamp": timestamp,
            "api_key": api_key,
            "endpoint": endpoint,
            "method": method,
            "success": success,
            "status_code": status_code,
            "error_message": error_message
        }

        with self.lock:
            log_file = self.get_log_file_path()
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

# 전역 로거 인스턴스
logger = RequestLogger()


# ============= 사용량 제한 시스템 =============

class RateLimiter:
    """API 키별 사용량 제한 시스템"""

    def __init__(self, limit: int):
        self.limit = limit
        self.usage_dir = Path("usage")
        self.lock = threading.Lock()

    def get_usage_file_path(self, api_key: str) -> Path:
        """API 키별 사용량 파일 경로 반환"""
        # 현재 월의 파일명
        current_month = datetime.now().strftime("%Y-%m")
        # API 키에서 안전한 파일명 생성 (특수문자 제거)
        safe_key = api_key.replace("/", "_").replace("\\", "_")
        return self.usage_dir / f"{safe_key}_{current_month}.json"

    def get_usage(self, api_key: str) -> Dict:
        """API 키의 현재 사용량 조회"""
        usage_file = self.get_usage_file_path(api_key)

        if not usage_file.exists():
            return {
                "api_key": api_key,
                "month": datetime.now().strftime("%Y-%m"),
                "count": 0,
                "last_updated": datetime.now().isoformat()
            }

        try:
            with open(usage_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {
                "api_key": api_key,
                "month": datetime.now().strftime("%Y-%m"),
                "count": 0,
                "last_updated": datetime.now().isoformat()
            }

    def increment_usage(self, api_key: str) -> Dict:
        """API 키의 사용량 증가"""
        with self.lock:
            usage_data = self.get_usage(api_key)
            usage_data["count"] += 1
            usage_data["last_updated"] = datetime.now().isoformat()

            # 파일에 저장
            usage_file = self.get_usage_file_path(api_key)
            with open(usage_file, "w", encoding="utf-8") as f:
                json.dump(usage_data, f, indent=2, ensure_ascii=False)

            return usage_data

    def check_rate_limit(self, api_key: str) -> tuple[bool, int]:
        """사용량 제한 확인 (is_allowed, remaining_count)"""
        usage_data = self.get_usage(api_key)
        current_count = usage_data["count"]
        remaining = max(0, self.limit - current_count)

        if current_count >= self.limit:
            return False, 0

        return True, remaining - 1  # 증가할 것을 고려해서 -1

# 전역 Rate Limiter 인스턴스
rate_limiter = RateLimiter(limit=MONTHLY_REQUEST_LIMIT)


# ============= x402 액세스 토큰 시스템 =============

class AccessTokenManager:
    """x402 액세스 토큰 관리 시스템"""

    def __init__(self, secret_key: str):
        self.secret_key = secret_key
        self.tokens_dir = Path("usage")
        self.lock = threading.Lock()

    def generate_token(self, payment_info: Dict) -> str:
        """액세스 토큰 생성 (1시간 유효)"""
        payload = {
            "payment_info": payment_info,
            "exp": datetime.utcnow() + timedelta(hours=1),
            "iat": datetime.utcnow()
        }
        token = jwt.encode(payload, self.secret_key, algorithm="HS256")

        # 토큰 정보 저장
        self._save_token_info(token, payment_info)

        return token

    def verify_token(self, token: str) -> tuple[bool, Optional[Dict]]:
        """액세스 토큰 검증"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=["HS256"])
            return True, payload
        except jwt.ExpiredSignatureError:
            return False, {"error": "토큰 만료"}
        except jwt.InvalidTokenError:
            return False, {"error": "유효하지 않은 토큰"}

    def _save_token_info(self, token: str, payment_info: Dict):
        """토큰 정보 저장"""
        with self.lock:
            token_file = self.tokens_dir / f"x402_token_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{token[:8]}.json"
            token_data = {
                "token": token,
                "payment_info": payment_info,
                "created_at": datetime.now().isoformat()
            }
            with open(token_file, "w", encoding="utf-8") as f:
                json.dump(token_data, f, indent=2, ensure_ascii=False)

# 전역 액세스 토큰 매니저 인스턴스
token_manager = AccessTokenManager(secret_key=JWT_SECRET)


# ============= API 키 인증 =============

async def verify_api_key(x_api_key: Optional[str] = Header(None, alias="X-API-Key")):
    """API 키 검증 의존성 함수"""

    if not x_api_key:
        # 요청 로깅
        logger.log_request(
            timestamp=datetime.now().isoformat(),
            api_key="missing",
            endpoint="unknown",
            method="unknown",
            success=False,
            status_code=401,
            error_message="API 키가 없습니다"
        )
        raise HTTPException(
            status_code=401,
            detail="API 키가 필요합니다. X-API-Key 헤더를 포함해주세요."
        )

    if x_api_key not in API_KEYS:
        # 요청 로깅
        logger.log_request(
            timestamp=datetime.now().isoformat(),
            api_key=x_api_key,
            endpoint="unknown",
            method="unknown",
            success=False,
            status_code=403,
            error_message="유효하지 않은 API 키"
        )
        raise HTTPException(
            status_code=403,
            detail="유효하지 않은 API 키입니다."
        )

    # 사용량 제한 확인
    is_allowed, remaining = rate_limiter.check_rate_limit(x_api_key)

    if not is_allowed:
        # 요청 로깅
        logger.log_request(
            timestamp=datetime.now().isoformat(),
            api_key=x_api_key,
            endpoint="unknown",
            method="unknown",
            success=False,
            status_code=429,
            error_message=f"월 사용량 초과 (제한: {MONTHLY_REQUEST_LIMIT}건)"
        )
        raise HTTPException(
            status_code=429,
            detail=f"월 사용량을 초과했습니다. 제한: {MONTHLY_REQUEST_LIMIT}건/월"
        )

    return x_api_key


# 요청 모델 정의
class PaymentRequest(BaseModel):
    """결제 요청 모델"""
    recipient_address: str = Field(
        ...,
        description="수신자 XRP 주소 (r로 시작하는 주소)"
    )
    amount: float = Field(
        ...,
        gt=0,
        description="전송할 금액 (통화 단위)"
    )
    currency: str = Field(
        default="XRP",
        description="통화 종류: XRP 또는 RLUSD"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "recipient_address": "rExampleReceiverAddress1234567890abcdefghijk",
                    "amount": 10.0,
                    "currency": "XRP"
                },
                {
                    "recipient_address": "rReceiverTestAccount987654321zyxwvutsrq",
                    "amount": 50.5,
                    "currency": "RLUSD"
                }
            ]
        }
    }

class PaymentResponse(BaseModel):
    """결제 응답 모델"""
    success: bool
    tx_hash: Optional[str] = None
    message: str
    fee_amount: Optional[float] = None
    sent_amount: Optional[float] = None
    remaining_quota: Optional[int] = None

class VerifyResponse(BaseModel):
    """검증 응답 모델"""
    success: bool
    verified: bool
    message: str

class PaymentStatus(BaseModel):
    """결제 상태 모델"""
    tx_hash: str
    success: bool
    amount: float
    sender: str
    recipient: str
    fee: float
    timestamp: str
    ledger_index: Optional[int] = None

class UsageInfo(BaseModel):
    """사용량 정보 모델"""
    api_key: str
    month: str
    count: int
    limit: int
    remaining: int

# x402 관련 모델
class X402PaymentRequest(BaseModel):
    """x402 결제 요청 모델"""
    tx_hash: str = Field(
        ...,
        description="결제 트랜잭션 해시"
    )

class X402PaymentResponse(BaseModel):
    """x402 결제 응답 모델"""
    access_token: str
    expires_in: int  # 초 단위
    message: str
    payment_verified: bool


def xrp_to_drops(xrp_amount: float) -> int:
    """XRP를 drops로 변환 (1 XRP = 1,000,000 drops)"""
    return int(xrp_amount * 1_000_000)


def drops_to_xrp(drops: int) -> float:
    """drops를 XRP로 변환"""
    return drops / 1_000_000


def validate_currency(currency: str) -> bool:
    """통화 종류 검증"""
    return currency in SUPPORTED_CURRENCIES


def create_amount(amount: float, currency: str):
    """
    XRPL 트랜잭션용 Amount 객체 생성

    Args:
        amount: 전송 금액
        currency: 통화 종류 (XRP 또는 RLUSD)

    Returns:
        XRP의 경우: 문자열 (drops 단위)
        IOU 토큰의 경우: IssuedCurrencyAmount 객체
    """
    if currency == "XRP":
        # XRP는 drops 단위의 문자열
        return str(xrp_to_drops(amount))
    elif currency == "RLUSD":
        # RLUSD는 IOU 토큰 형식 (IssuedCurrencyAmount 객체 사용)
        return IssuedCurrencyAmount(
            currency=RLUSD_CURRENCY,  # 표준 통화 코드 (예: USD)
            value=str(amount),
            issuer=RLUSD_ISSUER
        )
    else:
        raise ValueError(f"지원하지 않는 통화: {currency}")


@app.post("/payment/create", response_model=PaymentResponse)
async def create_payment(
    request: PaymentRequest,
    api_key: str = Depends(verify_api_key),
    http_request: Request = None
):
    """
    결제 생성 엔드포인트

    수신자 주소와 금액을 받아서 XRPL 테스트넷에 결제를 생성합니다.
    XRP와 RLUSD 통화를 지원합니다. 전체 금액의 1%를 수수료로 차감하고, 나머지 금액을 수신자에게 전송합니다.

    Headers:
        X-API-Key: (required) API 인증 키

    Args:
        request: PaymentRequest (recipient_address, amount, currency)

    Returns:
        PaymentResponse: 트랜잭션 해시와 수수료 정보 포함

    Raises:
        HTTPException: 결제 실패 시
    """
    endpoint = "/payment/create"
    start_time = datetime.now()
    status_code = 200
    error_message = ""

    try:
        # 통화 검증
        if not validate_currency(request.currency):
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 통화: {request.currency}. 지원 통화: {list(SUPPORTED_CURRENCIES.keys())}"
            )

        # 수수료 계산 (1%)
        fee_amount = request.amount * 0.01
        sent_amount = request.amount - fee_amount

        # 수수료와 전송 금액을 XRPL Amount 형식으로 변환
        fee_amount_obj = create_amount(fee_amount, request.currency)
        sent_amount_obj = create_amount(sent_amount, request.currency)

        def create_payment_sync():
            # WebsocketClient 생성 및 연결 (동기적)
            with WebsocketClient(XRPL_NODE) as client:
                # 발신자 지갑 생성
                sender_wallet = Wallet.from_secret(SENDER_SECRET)

                # 발신자 계정 정보 확인 (잔액 확인 등)
                try:
                    account_info_req = AccountInfo(account=SENDER_ADDRESS)
                    account_info = client.request(account_info_req)
                    balance = drops_to_xrp(int(account_info.result['account_data']['Balance']))

                    if balance < request.amount:
                        raise HTTPException(
                            status_code=400,
                            detail=f"잔액 부족. 현재 잔액: {balance:.6f} XRP, 요청 금액: {request.amount:.6f} XRP"
                        )
                except Exception as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"계정 정보 조회 실패: {str(e)}"
                    )

                # 수수료를 FEE_ACCOUNT로 전송하는 트랜잭션 (XRP만 해당)
                if request.currency == "XRP" and fee_amount > 0:
                    fee_tx = Payment(
                        account=SENDER_ADDRESS,
                        destination=FEE_ACCOUNT,
                        amount=fee_amount_obj
                    )

                    try:
                        fee_tx_signed = autofill_and_sign(fee_tx, client, sender_wallet)
                        fee_result = submit(fee_tx_signed, client)

                        if fee_result.result.get('engine_result') != 'tesSUCCESS':
                            raise HTTPException(
                                status_code=500,
                                detail=f"수수료 전송 실패: {fee_result.result.get('engine_result', 'Unknown')}"
                            )
                    except HTTPException:
                        raise
                    except Exception as e:
                        raise HTTPException(
                            status_code=500,
                            detail=f"수수료 전송 중 오류 발생: {str(e)}"
                        )

                # 송신자와 수신자 주소 검증 (자신에게 전송 방지)
                if SENDER_ADDRESS == request.recipient_address:
                    raise HTTPException(
                        status_code=400,
                        detail="송신자와 수신자가 같습니다. 다른 주소로 전송해주세요."
                    )

                # 실제 결제 금액을 수신자에게 전송하는 트랜잭션
                # IOU 토큰(RLUSD)은 send_max 없이 직접 전송 (IssuedCurrencyAmount 사용)
                payment_tx = Payment(
                    account=SENDER_ADDRESS,
                    destination=request.recipient_address,
                    amount=sent_amount_obj
                )

                # 트랜잭션 자동 필드 채우기 및 서명
                payment_signed = autofill_and_sign(payment_tx, client, sender_wallet)

                # 트랜잭션 제출
                result = submit(payment_signed, client)

                if result.result.get('engine_result') == 'tesSUCCESS':
                    # 트랜잭션 해시 가져오기
                    tx_hash = result.result.get('tx_json', {}).get('hash', result.result.get('hash', 'unknown'))
                    return {
                        "success": True,
                        "tx_hash": tx_hash,
                        "fee_amount": round(fee_amount, 6),
                        "sent_amount": round(sent_amount, 6)
                    }
                else:
                    engine_result = result.result.get('engine_result', 'Unknown')

                    # IOU 토큰 관련 에러 메시지 개선
                    if engine_result == 'tecPATH_DRY':
                        if request.currency == "RLUSD":
                            raise HTTPException(
                                status_code=400,
                                detail=f"수신자가 {request.currency} 토큰에 대한 trust line을 설정하지 않았습니다. 수신자가 먼저 {request.currency}를 받을 수 있도록 trust line을 설정해야 합니다."
                            )
                        else:
                            raise HTTPException(
                                status_code=400,
                                detail=f"수신자가 {request.currency} 토큰을 받을 수 없습니다. trust line을 확인해주세요."
                            )

                    raise HTTPException(
                        status_code=500,
                        detail=f"트랜잭션 실패: {engine_result}"
                    )

        # 스레드 풀에서 동기 함수 실행
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, create_payment_sync)

            # 사용량 증가
            usage_data = rate_limiter.increment_usage(api_key)

            # 성공 로깅
            logger.log_request(
                timestamp=start_time.isoformat(),
                api_key=api_key,
                endpoint=endpoint,
                method="POST",
                success=True,
                status_code=200,
                error_message=""
            )

            result["message"] = "결제가 성공적으로 생성되었습니다."
            result["remaining_quota"] = max(0, MONTHLY_REQUEST_LIMIT - usage_data["count"])

            return PaymentResponse(**result)

    except HTTPException as e:
        status_code = e.status_code
        error_message = str(e.detail)

        # 실패 로깅 (HTTPException은 사용량 증가 안 함)
        logger.log_request(
            timestamp=start_time.isoformat(),
            api_key=api_key,
            endpoint=endpoint,
            method="POST",
            success=False,
            status_code=status_code,
            error_message=error_message
        )

        raise
    except Exception as e:
        status_code = 500
        error_message = str(e)

        # 실패 로깅
        logger.log_request(
            timestamp=start_time.isoformat(),
            api_key=api_key,
            endpoint=endpoint,
            method="POST",
            success=False,
            status_code=status_code,
            error_message=error_message
        )

        raise HTTPException(
            status_code=500,
            detail=f"결제 생성 중 오류 발생: {str(e)}"
        )


@app.get("/payment/verify/{tx_hash}", response_model=VerifyResponse)
async def verify_payment(
    tx_hash: str,
    api_key: str = Depends(verify_api_key)
):
    """
    결제 검증 엔드포인트

    트랜잭션 해시를 통해 결제의 성공/실패 여부를 확인합니다.

    Headers:
        X-API-Key: (required) API 인증 키

    Args:
        tx_hash: 검증할 트랜잭션 해시

    Returns:
        VerifyResponse: 검증 결과 (성공/실패 여부)

    Raises:
        HTTPException: 트랜잭션 조회 실패 시
    """
    endpoint = f"/payment/verify/{tx_hash}"
    start_time = datetime.now()
    status_code = 200
    error_message = ""

    try:
        def verify_sync():
            with WebsocketClient(XRPL_NODE) as client:
                # 트랜잭션 조회 요청
                tx_req = Tx(transaction=tx_hash)
                tx_response = client.request(tx_req)

                if tx_response.is_successful():
                    tx_result = tx_response.result
                    # XRPL 트랜잭션 데이터는 tx_json 필드에 있음
                    tx_data = tx_result.get('tx_json', {})
                    meta = tx_result.get('meta', {})

                    # 트랜잭션 결과 확인
                    transaction_result = meta.get('TransactionResult', 'tesFAILURE')

                    is_success = transaction_result == 'tesSUCCESS'

                    return VerifyResponse(
                        success=True,
                        verified=is_success,
                        message=f"트랜잭션 {'성공' if is_success else '실패'}"
                    )
                else:
                    return VerifyResponse(
                        success=False,
                        verified=False,
                        message="트랜잭션을 찾을 수 없거나 아직 승인되지 않았습니다."
                    )

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, verify_sync)

            # 사용량 증가
            rate_limiter.increment_usage(api_key)

            # 성공 로깅
            logger.log_request(
                timestamp=start_time.isoformat(),
                api_key=api_key,
                endpoint=endpoint,
                method="GET",
                success=True,
                status_code=200,
                error_message=""
            )

            return result

    except Exception as e:
        status_code = 500
        error_message = str(e)

        # 실패 로깅
        logger.log_request(
            timestamp=start_time.isoformat(),
            api_key=api_key,
            endpoint=endpoint,
            method="GET",
            success=False,
            status_code=status_code,
            error_message=error_message
        )

        raise HTTPException(
            status_code=500,
            detail=f"결제 검증 중 오류 발생: {str(e)}"
        )


@app.get("/payment/status/{tx_hash}", response_model=PaymentStatus)
async def get_payment_status(
    tx_hash: str,
    api_key: str = Depends(verify_api_key)
):
    """
    결제 상세 상태 조회 엔드포인트

    트랜잭션 해시를 통해 결제의 상세 정보를 조회합니다.
    금액, 수신자, 시간, 수수료 등의 정보를 반환합니다.

    Headers:
        X-API-Key: (required) API 인증 키

    Args:
        tx_hash: 조회할 트랜잭션 해시

    Returns:
        PaymentStatus: 결제 상세 정보

    Raises:
        HTTPException: 트랜잭션 조회 실패 시
    """
    endpoint = f"/payment/status/{tx_hash}"
    start_time = datetime.now()
    status_code = 200
    error_message = ""

    try:
        def get_status_sync():
            with WebsocketClient(XRPL_NODE) as client:
                # 트랜잭션 조회 요청
                tx_req = Tx(transaction=tx_hash)
                tx_response = client.request(tx_req)

                if not tx_response.is_successful():
                    raise HTTPException(
                        status_code=404,
                        detail="트랜잭션을 찾을 수 없습니다."
                    )

                tx_result = tx_response.result

                # XRPL 트랜잭션 데이터는 tx_json 필드에 있음
                tx_data = tx_result.get('tx_json', {})
                meta = tx_result.get('meta', {})

                # 트랜잭션 정보 추출
                # Amount 필드가 문자열 또는 딕셔너리 형태로 올 수 있음
                # DeliverMax 필드도 확인 (최신 XRPL 버전)
                amount_field = tx_data.get('Amount') or tx_data.get('DeliverMax', '0')
                if isinstance(amount_field, dict):
                    # 토큰 결제의 경우: {'currency': ..., 'value': ...}
                    amount_value = amount_field.get('value', '0')
                    amount = float(amount_value)
                elif isinstance(amount_field, str):
                    # XRP 결제의 경우: drops 단위 문자열
                    try:
                        amount = drops_to_xrp(int(amount_field))
                    except ValueError:
                        amount = 0.0
                else:
                    amount = 0.0

                sender = tx_data.get('Account', '')
                recipient = tx_data.get('Destination', '')

                # 트랜잭션 결과 확인
                transaction_result = meta.get('TransactionResult', 'tesFAILURE')
                is_success = transaction_result == 'tesSUCCESS'

                # 트랜잭션 수수료 (네트워크 수수료)
                fee_in_drops = int(tx_data.get('Fee', 0))
                network_fee = drops_to_xrp(fee_in_drops)

                # 타임스탬프 정보
                date = tx_result.get('date', None)
                ledger_index = tx_result.get('ledger_index', None)

                # XRPL epoch 시간 (2000-01-01 00:00:00 UTC)을 Unix 타임스탬프로 변환
                timestamp_str = "Unknown"
                if date is not None:
                    xrpl_epoch = 946684800  # 2000-01-01 00:00:00 UTC
                    unix_timestamp = xrpl_epoch + date
                    timestamp_str = datetime.fromtimestamp(unix_timestamp).strftime('%Y-%m-%d %H:%M:%S UTC')

                # 애플리케이션 수수료 계산 (1%)
                original_amount = amount / 0.99
                app_fee = original_amount * 0.01

                return PaymentStatus(
                    tx_hash=tx_hash,
                    success=is_success,
                    amount=round(amount, 6),
                    sender=sender,
                    recipient=recipient,
                    fee=round(app_fee, 6),
                    timestamp=timestamp_str,
                    ledger_index=ledger_index
                )

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, get_status_sync)

            # 사용량 증가
            rate_limiter.increment_usage(api_key)

            # 성공 로깅
            logger.log_request(
                timestamp=start_time.isoformat(),
                api_key=api_key,
                endpoint=endpoint,
                method="GET",
                success=True,
                status_code=200,
                error_message=""
            )

            return result

    except HTTPException:
        raise
    except Exception as e:
        status_code = 500
        error_message = str(e)

        # 실패 로깅
        logger.log_request(
            timestamp=start_time.isoformat(),
            api_key=api_key,
            endpoint=endpoint,
            method="GET",
            success=False,
            status_code=status_code,
            error_message=error_message
        )

        raise HTTPException(
            status_code=500,
            detail=f"결제 상태 조회 중 오류 발생: {str(e)}"
        )


@app.get("/usage/info", response_model=UsageInfo)
async def get_usage_info(api_key: str = Depends(verify_api_key)):
    """
    사용량 정보 조회 엔드포인트

    현재 API 키의 월간 사용량 정보를 반환합니다.

    Headers:
        X-API-Key: (required) API 인증 키

    Returns:
        UsageInfo: 사용량 정보 (현재 사용량, 한도, 잔여)
    """
    endpoint = "/usage/info"
    start_time = datetime.now()

    try:
        usage_data = rate_limiter.get_usage(api_key)
        current_count = usage_data["count"]
        remaining = max(0, MONTHLY_REQUEST_LIMIT - current_count)

        # 성공 로깅 (사용량 조회는 카운트하지 않음)
        logger.log_request(
            timestamp=start_time.isoformat(),
            api_key=api_key,
            endpoint=endpoint,
            method="GET",
            success=True,
            status_code=200,
            error_message=""
        )

        return UsageInfo(
            api_key=api_key,
            month=usage_data["month"],
            count=current_count,
            limit=MONTHLY_REQUEST_LIMIT,
            remaining=remaining
        )

    except Exception as e:
        # 실패 로깅
        logger.log_request(
            timestamp=start_time.isoformat(),
            api_key=api_key,
            endpoint=endpoint,
            method="GET",
            success=False,
            status_code=500,
            error_message=str(e)
        )

        raise HTTPException(
            status_code=500,
            detail=f"사용량 조회 중 오류 발생: {str(e)}"
        )


@app.get("/")
async def root():
    """루트 엔드포인트 - API 정보"""
    return {
        "message": "XAgent Pay API Server",
        "version": "2.0.0",
        "features": {
            "authentication": "API Key (X-API-Key header)",
            "rate_limiting": f"{MONTHLY_REQUEST_LIMIT} requests/month per API key",
            "logging": "All requests logged to logs/ directory",
            "x402": "HTTP 402 Payment Required 표준 지원"
        },
        "endpoints": {
            "POST /payment/create": "결제 생성 (API 키 필요)",
            "GET /payment/verify/{tx_hash}": "결제 검증 (API 키 필요)",
            "GET /payment/status/{tx_hash}": "결제 상세 상태 조회 (API 키 필요)",
            "GET /usage/info": "사용량 정보 조회 (API 키 필요)",
            "GET /data/market-info": "x402 결제 테스트 리소스 (결제 필요)",
            "POST /x402/pay": "x402 결제 토큰 발급",
            "GET /docs": "API 문서 (Swagger UI)",
            "GET /redoc": "API 문서 (ReDoc)"
        }
    }


@app.get("/health")
async def health_check():
    """헬스체크 엔드포인트 (API 키 불필요)"""
    return {
        "status": "healthy",
        "service": "XAgent Pay API",
        "version": "2.0.0",
        "api_keys_configured": len(API_KEYS),
        "rate_limit": f"{MONTHLY_REQUEST_LIMIT}/month",
        "x402_enabled": True
    }


# ============= x402 결제 표준 엔드포인트 =============

@app.post("/x402/create-payment", response_model=PaymentResponse)
async def create_x402_payment(
    api_key: str = Depends(verify_api_key),
    http_request: Request = None
):
    """
    x402 전용 결제 생성 엔드포인트

    x402 결제용으로 고정된 금액(0.1 XRP)을 FEE_ACCOUNT로 직접 전송합니다.
    이 결제의 트랜잭션 해시로 /x402/pay 엔드포인트에서 액세스 토큰을 발급받을 수 있습니다.

    Headers:
        X-API-Key: (required) API 인증 키

    Returns:
        PaymentResponse: 트랜잭션 해시 포함

    Raises:
        HTTPException: 결제 실패 시
    """
    endpoint = "/x402/create-payment"
    start_time = datetime.now()
    status_code = 200
    error_message = ""

    try:
        # x402 결제는 고정 금액
        payment_amount = X402_PAYMENT_AMOUNT

        def create_x402_payment_sync():
            # WebsocketClient 생성 및 연결 (동기적)
            with WebsocketClient(XRPL_NODE) as client:
                # 발신자 지갑 생성
                sender_wallet = Wallet.from_secret(SENDER_SECRET)

                # 발신자 계정 정보 확인 (잔액 확인 등)
                try:
                    account_info_req = AccountInfo(account=SENDER_ADDRESS)
                    account_info = client.request(account_info_req)
                    balance = drops_to_xrp(int(account_info.result['account_data']['Balance']))

                    if balance < payment_amount:
                        raise HTTPException(
                            status_code=400,
                            detail=f"잔액 부족. 현재 잔액: {balance:.6f} XRP, 요청 금액: {payment_amount:.6f} XRP"
                        )
                except Exception as e:
                    raise HTTPException(
                        status_code=500,
                        detail=f"계정 정보 조회 실패: {str(e)}"
                    )

                # x402 결제 금액 전체를 FEE_ACCOUNT로 전송 (수수료 없음)
                payment_tx = Payment(
                    account=SENDER_ADDRESS,
                    destination=X402_FEE_ADDRESS,
                    amount=str(xrp_to_drops(payment_amount))
                )

                # 트랜잭션 자동 필드 채우기 및 서명
                payment_signed = autofill_and_sign(payment_tx, client, sender_wallet)

                # 트랜잭션 제출
                result = submit(payment_signed, client)

                if result.result.get('engine_result') == 'tesSUCCESS':
                    # 트랜잭션 해시 가져오기
                    tx_hash = result.result.get('tx_json', {}).get('hash', result.result.get('hash', 'unknown'))
                    return {
                        "success": True,
                        "tx_hash": tx_hash,
                        "fee_amount": 0.0,  # x402는 별도 수수료 없음
                        "sent_amount": payment_amount
                    }
                else:
                    raise HTTPException(
                        status_code=500,
                        detail=f"트랜잭션 실패: {result.result.get('engine_result', 'Unknown')}"
                    )

        # 스레드 풀에서 동기 함수 실행
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, create_x402_payment_sync)

            # 사용량 증가
            usage_data = rate_limiter.increment_usage(api_key)

            # 성공 로깅
            logger.log_request(
                timestamp=start_time.isoformat(),
                api_key=api_key,
                endpoint=endpoint,
                method="POST",
                success=True,
                status_code=200,
                error_message=""
            )

            result["message"] = "x402 결제가 성공적으로 생성되었습니다."
            result["remaining_quota"] = max(0, MONTHLY_REQUEST_LIMIT - usage_data["count"])

            return PaymentResponse(**result)

    except HTTPException as e:
        status_code = e.status_code
        error_message = str(e.detail)

        # 실패 로깅 (HTTPException은 사용량 증가 안 함)
        logger.log_request(
            timestamp=start_time.isoformat(),
            api_key=api_key,
            endpoint=endpoint,
            method="POST",
            success=False,
            status_code=status_code,
            error_message=error_message
        )

        raise
    except Exception as e:
        status_code = 500
        error_message = str(e)

        # 실패 로깅
        logger.log_request(
            timestamp=start_time.isoformat(),
            api_key=api_key,
            endpoint=endpoint,
            method="POST",
            success=False,
            status_code=status_code,
            error_message=error_message
        )

        raise HTTPException(
            status_code=500,
            detail=f"x402 결제 생성 중 오류 발생: {str(e)}"
        )


@app.get("/data/market-info")
async def get_market_info(
    request: Request,
    x_payment_token: Optional[str] = Header(None, alias="X-Payment-Token")
):
    """
    x402 결제 테스트 리소스 엔드포인트

    AI 에이전트가 접근 가능한 시장 정보 리소스입니다.
    X-Payment-Token 헤더가 없으면 402 응답과 결제 정보를 반환합니다.

    Args:
        request: FastAPI Request 객체
        x_payment_token: x402 액세스 토큰

    Returns:
        dict: 시장 정보 데이터 또는 402 Payment Required
    """
    # 토큰 검증
    if x_payment_token:
        is_valid, payload = token_manager.verify_token(x_payment_token)
        if is_valid:
            # 토큰이 유효하면 데이터 반환
            return JSONResponse(
                status_code=200,
                content={
                    "market": "XRP/KRW",
                    "price": 1500.50,
                    "volume_24h": 125000000,
                    "change_24h": 2.5,
                    "timestamp": datetime.now().isoformat(),
                    "source": "XAgent Pay API"
                }
            )
        else:
            # 토큰 만료 또는 유효하지 않음
            return JSONResponse(
                status_code=401,
                content={"error": "액세스 토큰이 만료되었거나 유효하지 않습니다"}
            )

    # 토큰이 없으면 402 Payment Required 응답
    response = JSONResponse(
        status_code=402,
        content={
            "error": "Payment Required",
            "message": "이 리소스에 접근하려면 결제가 필요합니다",
            "payment_protocol": "x402"
        }
    )

    # 결제 정보 헤더 추가
    response.headers["X-Payment-Required"] = "true"
    response.headers["X-Payment-Amount"] = str(X402_PAYMENT_AMOUNT)
    response.headers["X-Payment-Currency"] = "XRP"
    response.headers["X-Payment-Address"] = X402_FEE_ADDRESS
    response.headers["X-Payment-Description"] = "XAgent Pay API Access - 1 hour access"

    return response


@app.post("/x402/pay", response_model=X402PaymentResponse)
async def x402_payment(request: X402PaymentRequest):
    """
    x402 결제 토큰 발급 엔드포인트

    AI 에이전트가 결제 완료 후 트랜잭션 해시를 제출하면,
    검증 후 액세스 토큰을 발급합니다. 토큰은 1시간 유효합니다.

    Args:
        request: X402PaymentRequest (tx_hash)

    Returns:
        X402PaymentResponse: 액세스 토큰과 만료 시간

    Raises:
        HTTPException: 결제 검증 실패 시
    """
    endpoint = "/x402/pay"
    start_time = datetime.now()

    try:
        # 트랜잭션 검증
        def verify_payment_sync():
            with WebsocketClient(XRPL_NODE) as client:
                # 트랜잭션 조회 요청
                tx_req = Tx(transaction=request.tx_hash)
                tx_response = client.request(tx_req)

                if not tx_response.is_successful():
                    return False, "트랜잭션을 찾을 수 없습니다"

                tx_result = tx_response.result
                # XRPL 트랜잭션 데이터는 tx_json 필드에 있음
                tx_data = tx_result.get('tx_json', {})
                meta = tx_result.get('meta', {})

                # 트랜잭션 결과 확인
                transaction_result = meta.get('TransactionResult', 'tesFAILURE')
                if transaction_result != 'tesSUCCESS':
                    return False, "트랜잭션이 실패했습니다"

                # 수신자 주소 확인 (x402 수수료 주소로 전송되었는지)
                recipient = tx_data.get('Destination', '')
                if recipient != X402_FEE_ADDRESS:
                    return False, f"잘못된 수신자 주소: {recipient}"

                # 전송 금액 확인
                # Amount 또는 DeliverMax 필드 확인
                amount_drops = tx_data.get('Amount') or tx_data.get('DeliverMax', '0')
                if isinstance(amount_drops, str):
                    amount_xrp = drops_to_xrp(int(amount_drops))
                else:
                    amount_xrp = drops_to_xrp(amount_drops)

                if amount_xrp < X402_PAYMENT_AMOUNT:
                    return False, f"결제 금액 부족: {amount_xrp} XRP (필요: {X402_PAYMENT_AMOUNT} XRP)"

                return True, {
                    "amount": amount_xrp,
                    "recipient": recipient,
                    "tx_hash": request.tx_hash
                }

        # 결제 검증 실행
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            is_valid, result = await loop.run_in_executor(pool, verify_payment_sync)

            if not is_valid:
                # 실패 로깅
                logger.log_request(
                    timestamp=start_time.isoformat(),
                    api_key="x402",
                    endpoint=endpoint,
                    method="POST",
                    success=False,
                    status_code=400,
                    error_message=str(result)
                )

                raise HTTPException(
                    status_code=400,
                    detail=f"결제 검증 실패: {result}"
                )

            # 결제 성공 - 액세스 토큰 생성
            payment_info = {
                "tx_hash": request.tx_hash,
                "amount": result["amount"],
                "recipient": result["recipient"]
            }

            access_token = token_manager.generate_token(payment_info)

            # 성공 로깅
            logger.log_request(
                timestamp=start_time.isoformat(),
                api_key="x402",
                endpoint=endpoint,
                method="POST",
                success=True,
                status_code=200,
                error_message=""
            )

            return X402PaymentResponse(
                access_token=access_token,
                expires_in=3600,  # 1시간 (3600초)
                message="액세스 토큰이 발급되었습니다",
                payment_verified=True
            )

    except HTTPException:
        raise
    except Exception as e:
        # 실패 로깅
        logger.log_request(
            timestamp=start_time.isoformat(),
            api_key="x402",
            endpoint=endpoint,
            method="POST",
            success=False,
            status_code=500,
            error_message=str(e)
        )

        raise HTTPException(
            status_code=500,
            detail=f"x402 결제 처리 중 오류 발생: {str(e)}"
        )


# ============= 통화 지원 엔드포인트 =============

class TrustLineInfo(BaseModel):
    """Trust Line 정보 모델"""
    address: str
    has_rlUSD_trustline: bool
    rlUSD_limit: Optional[float] = None
    rlUSD_balance: Optional[float] = None
    message: str


@app.get("/payment/trustline/{address}", response_model=TrustLineInfo)
async def check_trustline(
    address: str,
    api_key: str = Depends(verify_api_key)
):
    """
    Trust Line 확인 엔드포인트

    해당 주소가 RLUSD 토큰에 대한 trust line을 설정했는지 확인합니다.

    Args:
        address: 확인할 XRP 주소
        api_key: API 인증 키

    Returns:
        TrustLineInfo: trust line 설정 정보

    Raises:
        HTTPException: 주소 조회 실패 시
    """
    endpoint = f"/payment/trustline/{address}"
    start_time = datetime.now()

    try:
        def check_trustline_sync():
            with WebsocketClient(XRPL_NODE) as client:
                # 계정의 trust lines 조회
                account_lines_req = AccountLines(
                    account=address,
                    peer=RLUSD_ISSUER  # 특정 발행자의 trust line만 조회
                )
                lines_response = client.request(account_lines_req)

                if not lines_response.is_successful():
                    return {
                        "has_trustline": False,
                        "limit": 0,
                        "balance": 0
                    }

                # 응답에서 trust line 정보 추출
                lines = lines_response.result.get('lines', [])
                rlUSD_line = None

                for line in lines:
                    currency = line.get('currency', '')
                    if currency == RLUSD_CURRENCY:  # USD
                        rlUSD_line = line
                        break

                if rlUSD_line:
                    # trust line이 설정된 경우
                    limit = float(rlUSD_line.get('limit', '0'))
                    balance = float(rlUSD_line.get('balance', '0'))
                    return {
                        "has_trustline": True,
                        "limit": limit,
                        "balance": balance
                    }
                else:
                    # trust line이 설정되지 않은 경우
                    return {
                        "has_trustline": False,
                        "limit": 0,
                        "balance": 0
                    }

        # trust line 확인 실행
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor() as pool:
            result = await loop.run_in_executor(pool, check_trustline_sync)

            # 성공 로깅
            logger.log_request(
                timestamp=start_time.isoformat(),
                api_key=api_key,
                endpoint=endpoint,
                method="GET",
                success=True,
                status_code=200,
                error_message=""
            )

            return TrustLineInfo(
                address=address,
                has_rlUSD_trustline=result["has_trustline"],
                rlUSD_limit=result["limit"] if result["has_trustline"] else None,
                rlUSD_balance=result["balance"] if result["has_trustline"] else None,
                message="RLUSD trust line이 설정되어 있습니다." if result["has_trustline"] else "RLUSD trust line이 설정되지 않았습니다."
            )

    except Exception as e:
        # 실패 로깅
        logger.log_request(
            timestamp=start_time.isoformat(),
            api_key=api_key,
            endpoint=endpoint,
            method="GET",
            success=False,
            status_code=500,
            error_message=str(e)
        )

        raise HTTPException(
            status_code=500,
            detail=f"Trust line 조회 중 오류 발생: {str(e)}"
        )


@app.get("/payment/rates")
async def get_supported_currencies():
    """
    지원 통화 목록 엔드포인트

    현재 지원하는 통화 목록과 정보를 반환합니다.

    Returns:
        dict: 지원 통화 정보

    예시:
        {
            "supported_currencies": {
                "XRP": {"currency": "XRP", "issuer": null, "scale": 6},
                "RLUSD": {"currency": "RLUSD", "issuer": "r...", "scale": 5}
            },
            "default_currency": "XRP",
            "fee_rate": 0.01
        }
    """
    return {
        "supported_currencies": SUPPORTED_CURRENCIES,
        "default_currency": "XRP",
        "fee_rate": 0.01,  # 1% 수수료
        "message": "현재 XRP와 RLUSD 스테이블코인을 지원합니다"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
