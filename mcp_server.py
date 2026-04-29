"""
XAgent Pay API MCP 서버

Claude AI가 XAgent Pay API를 툴로 사용할 수 있게 하는 MCP 서버입니다.
XRP 및 RLUSD 결제를 생성하고 검증할 수 있습니다.
"""

import asyncio
import os
import json
from typing import Any, Optional
from mcp.server.models import InitializationOptions
from mcp.server import NotificationOptions, Server
from mcp.server.stdio import stdio_server
from dotenv import load_dotenv
import requests
from pydantic import BaseModel

# 환경변수 로드
load_dotenv()

# MCP 서버 설정
XAGENT_PAY_API_URL = os.getenv("XAGENT_PAY_API_URL", "http://localhost:8000")
MCP_API_KEY = os.getenv("MCP_API_KEY", "test_key_123456")

# 서버 인스턴스 생성
server = Server("xagent-pay-api")


class MCPToolError(Exception):
    """MCP 툴 에러"""
    pass


async def call_xagent_api(
    method: str,
    endpoint: str,
    data: Optional[dict] = None
) -> dict:
    """
    XAgent Pay API 호출 공통 함수

    Args:
        method: HTTP 메서드 (GET, POST)
        endpoint: API 엔드포인트
        data: 요청 데이터 (POST인 경우)

    Returns:
        API 응답 데이터

    Raises:
        MCPToolError: API 호출 실패 시
    """
    url = f"{XAGENT_PAY_API_URL}{endpoint}"
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": MCP_API_KEY
    }

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, timeout=10)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=data, timeout=10)
        else:
            raise MCPToolError(f"지원하지 않는 HTTP 메서드: {method}")

        response.raise_for_status()
        return response.json()

    except requests.exceptions.RequestException as e:
        raise MCPToolError(f"API 호출 실패: {str(e)}")
    except json.JSONDecodeError:
        raise MCPToolError("API 응답이 유효한 JSON이 아닙니다")


@server.list_tools()
async def handle_list_tools() -> list[dict]:
    """사용 가능한 MCP 툴 목록 반환"""
    return [
        {
            "name": "create_payment",
            "description": "XRP 또는 RLUSD 결제 생성. 수신자 주소, 금액, 통화를 받아 결제를 생성합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "recipient_address": {
                        "type": "string",
                        "description": "수신자 XRP 주소 (r로 시작)"
                    },
                    "amount": {
                        "type": "number",
                        "description": "전송 금액 (통화 단위)"
                    },
                    "currency": {
                        "type": "string",
                        "enum": ["XRP", "RLUSD"],
                        "description": "통화 종류",
                        "default": "XRP"
                    }
                },
                "required": ["recipient_address", "amount"]
            }
        },
        {
            "name": "verify_payment",
            "description": "결제 트랜잭션 검증. 트랜잭션 해시로 결제 성공/실패 여부를 확인합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tx_hash": {
                        "type": "string",
                        "description": "검증할 트랜잭션 해시"
                    }
                },
                "required": ["tx_hash"]
            }
        },
        {
            "name": "check_trustline",
            "description": "RLUSD Trust Line 확인. 특정 주소가 RLUSD를 받을 수 있는지 확인합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "address": {
                        "type": "string",
                        "description": "확인할 XRP 주소"
                    }
                },
                "required": ["address"]
            }
        },
        {
            "name": "get_rates",
            "description": "지원 통화 및 수수료 정보 조회. 현재 지원하는 통화와 수수료율을 반환합니다.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[dict]:
    """
    MCP 툴 호출 처리

    Args:
        name: 툴 이름
        arguments: 툴 인자

    Returns:
        툴 실행 결과
    """
    try:
        if name == "create_payment":
            # 결제 생성 툴
            recipient_address = arguments.get("recipient_address")
            amount = arguments.get("amount")
            currency = arguments.get("currency", "XRP")

            if not recipient_address or not amount:
                raise MCPToolError("recipient_address와 amount는 필수 파라미터입니다.")

            # XAgent Pay API 호출
            result = await call_xagent_api(
                "POST",
                "/payment/create",
                {
                    "recipient_address": recipient_address,
                    "amount": float(amount),
                    "currency": currency
                }
            )

            return [{
                "success": result.get("success", False),
                "tx_hash": result.get("tx_hash"),
                "message": result.get("message"),
                "fee_amount": result.get("fee_amount"),
                "sent_amount": result.get("sent_amount"),
                "remaining_quota": result.get("remaining_quota")
            }]

        elif name == "verify_payment":
            # 결제 검증 툴
            tx_hash = arguments.get("tx_hash")

            if not tx_hash:
                raise MCPToolError("tx_hash는 필수 파라미터입니다.")

            # XAgent Pay API 호출
            result = await call_xagent_api(
                "GET",
                f"/payment/verify/{tx_hash}"
            )

            return [{
                "success": result.get("success", False),
                "verified": result.get("verified", False),
                "message": result.get("message")
            }]

        elif name == "check_trustline":
            # Trust Line 확인 툴
            address = arguments.get("address")

            if not address:
                raise MCPToolError("address는 필수 파라미터입니다.")

            # XAgent Pay API 호출
            result = await call_xagent_api(
                "GET",
                f"/payment/trustline/{address}"
            )

            return [{
                "address": result.get("address"),
                "has_rlUSD_trustline": result.get("has_rlUSD_trustline", False),
                "rlUSD_limit": result.get("rlUSD_limit"),
                "rlUSD_balance": result.get("rlUSD_balance"),
                "message": result.get("message")
            }]

        elif name == "get_rates":
            # 지원 통화 확인 툴
            # XAgent Pay API 호출
            result = await call_xagent_api(
                "GET",
                "/payment/rates"
            )

            return [{
                "supported_currencies": result.get("supported_currencies", {}),
                "default_currency": result.get("default_currency"),
                "fee_rate": result.get("fee_rate"),
                "message": result.get("message")
            }]

        else:
            raise MCPToolError(f"알 수 없는 툴: {name}")

    except MCPToolError as e:
        return [{
            "success": False,
            "error": str(e)
        }]
    except Exception as e:
        return [{
            "success": False,
            "error": f"툴 실행 중 오류 발생: {str(e)}"
        }]


async def main():
    """MCP 서버 메인 함수"""
    # 서버 실행 옵션 설정
    options = server.create_initialization_options()

    # stdio 서버 실행
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            options
        )


if __name__ == "__main__":
    asyncio.run(main())
