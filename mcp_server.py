"""
XAgent Pay API MCP 서버 (FastMCP)

Claude AI가 XAgent Pay API를 툴로 사용할 수 있는 MCP 서버입니다.
XRP 및 RLUSD 결제를 생성하고 검증할 수 있습니다.
"""

from mcp.server.fastmcp import FastMCP
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

# MCP 서버 인스턴스 생성
mcp = FastMCP("xagent-pay-api")

# XAgent Pay API 설정
API_BASE = os.getenv("XAGENT_PAY_API_URL", "http://localhost:8000")
API_KEY = os.getenv("MCP_API_KEY", "test_key_123456")


@mcp.tool()
def get_rates() -> str:
    """
    지원 통화 및 수수료 정보 조회

    현재 지원하는 통화 목록과 수수료율을 반환합니다.
    """
    try:
        response = httpx.get(
            f"{API_BASE}/payment/rates",
            headers={"X-API-Key": API_KEY},
            timeout=10.0
        )
        response.raise_for_status()
        return str(response.json())
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def create_payment(recipient_address: str, amount: float, currency: str = "XRP") -> str:
    """
    XRP 또는 RLUSD 결제 생성

    수신자 주소와 금액을 받아 결제를 생성합니다.
    전체 금액의 1%가 수수료로 자동 차감됩니다.

    Args:
        recipient_address: 수신자 XRP 주소 (r로 시작)
        amount: 전송 금액 (통화 단위)
        currency: 통화 종류 ("XRP" or "RLUSD", default: "XRP")
    """
    try:
        response = httpx.post(
            f"{API_BASE}/payment/create",
            headers={"X-API-Key": API_KEY},
            json={
                "recipient_address": recipient_address,
                "amount": amount,
                "currency": currency
            },
            timeout=10.0
        )
        response.raise_for_status()
        return str(response.json())
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def verify_payment(tx_hash: str) -> str:
    """
    결제 트랜잭션 검증

    트랜잭션 해시로 결제 성공/실패 여부를 확인합니다.

    Args:
        tx_hash: 검증할 트랜잭션 해시
    """
    try:
        response = httpx.get(
            f"{API_BASE}/payment/verify/{tx_hash}",
            headers={"X-API-Key": API_KEY},
            timeout=10.0
        )
        response.raise_for_status()
        return str(response.json())
    except Exception as e:
        return f"Error: {str(e)}"


@mcp.tool()
def check_trustline(address: str) -> str:
    """
    RLUSD Trust Line 확인

    특정 주소가 RLUSD를 받을 수 있는지 확인합니다.
    Trust Line 설정 여부, 한도, 잔액을 반환합니다.

    Args:
        address: 확인할 XRP 주소
    """
    try:
        response = httpx.get(
            f"{API_BASE}/payment/trustline/{address}",
            headers={"X-API-Key": API_KEY},
            timeout=10.0
        )
        response.raise_for_status()
        return str(response.json())
    except Exception as e:
        return f"Error: {str(e)}"


if __name__ == "__main__":
    mcp.run()
