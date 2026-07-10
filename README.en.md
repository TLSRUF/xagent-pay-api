# XAgent Pay API

XRPL-based Payment API for AI Agents and Developers

## Overview

FastAPI-based XRPL (XRP Ledger) testnet payment server. Abstracts complex blockchain logic to enable easy integration of XRP and RLUSD payments for AI agents and applications.

- **Supported Currencies:** XRP, RLUSD (stablecoin)
- **Auth:** Issuable/revocable API keys with per-tier pricing and limits
- **Wallets:** Each API key gets a dedicated XRPL wallet auto-generated and funded on issuance (isolated per agent)
- **Observability:** Web usage dashboard, transaction history, cumulative fee tracking
- **Notifications:** Webhook callbacks on payment success/failure (signed + retried)

## Quick Start

```bash
# 1. Clone & install dependencies
pip install -r requirements.txt

# 2. Create .env file (copy from .env.example and fill in values)
cp .env.example .env
```

At minimum, fill in the following in `.env` to start the server:

```bash
SENDER_ADDRESS=your_testnet_XRP_address    # platform shared wallet (fallback for legacy keys)
SENDER_SECRET=your_secret_key
FEE_ACCOUNT=your_fee_account_address
XRPL_NODE=wss://s.altnet.rippletest.net:51233
ADMIN_API_KEY=a_strong_admin_key            # required for issuing/revoking API keys
```

Need a testnet account? Get one from the [XRPL Faucet](https://xrpl.org/xrp-testnet-faucet.html).

```bash
# 3. Run the server
python main.py
# or
uvicorn main:app --host 0.0.0.0 --port 8000

# Production (see "Known Limitations" below — currently designed for a single worker)
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
```

- API: http://localhost:8000
- Swagger Docs: http://localhost:8000/docs
- Usage Dashboard: http://localhost:8000/dashboard

```bash
# 4. Issue your first API key (run once with the admin key)
curl -X POST "http://localhost:8000/admin/keys" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your_admin_key" \
  -d '{"name": "my-first-agent", "tier": "free"}'
```

The `api_key` in the response is what you'll use as `X-API-Key` for every other request. **It is only shown once, in this response** — store it securely. The `wallet_address` in the same response is the dedicated XRPL wallet auto-created and funded for this key.

## Pricing

| Tier | Price | Monthly Request Limit | Transaction Fee Rate |
|---|---|---|---|
| Free | $0 | 100 | 1% |
| Pro | $49/mo | Unlimited | 0.15% |
| Enterprise | Custom | Unlimited | Custom (volume-based) |

- The Pro tier's $49/month subscription is **not** billed by this API directly — it's handled by a separate SaaS billing layer.
- This API only enforces the **per-transaction fee rate**.
- For Enterprise, a custom `fee_rate` can be set at key issuance to override the tier default.
- The currently active fee rates per tier can always be checked via `GET /payment/rates`.

## Authentication — Issuing / Listing / Revoking API Keys

Key issuance and revocation are admin-only (`X-Admin-Key` header). All other endpoints use the issued key (`X-API-Key` header).

```bash
# Issue a key (includes automatic dedicated wallet creation)
curl -X POST "http://localhost:8000/admin/keys" \
  -H "Content-Type: application/json" \
  -H "X-Admin-Key: your_admin_key" \
  -d '{"name": "customer-a-bot", "tier": "pro"}'

# List keys (plaintext key is never exposed after issuance)
curl "http://localhost:8000/admin/keys" -H "X-Admin-Key: your_admin_key"

# Revoke a key
curl -X POST "http://localhost:8000/admin/keys/{key_id}/revoke" \
  -H "X-Admin-Key: your_admin_key"
```

| Code | Description |
|------|-------------|
| 401 | Missing API key |
| 403 | Invalid or revoked API key |
| 429 | Monthly tier limit exceeded |
| 503 | Admin API disabled (`ADMIN_API_KEY` not set) |

## Wallet Management (Multi-Agent)

When an API key is issued, a **dedicated XRPL wallet is automatically generated and funded** via the testnet faucet. From then on, all payments made with that key are sent from its own wallet rather than the platform's shared wallet — so multiple agents paying concurrently never collide on the same XRPL sequence number.

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

`dedicated: false` means either dedicated wallet creation/funding failed (e.g. testnet faucet rate limit) or this is a legacy key migrated from `.env`'s `API_KEYS`, both of which fall back to sharing the platform's wallet.

## Payment API

All payment endpoints require the `X-API-Key` header.

### Create Payment

**XRP Payment:**
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

**RLUSD Payment:**
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

⚠️ **Before RLUSD Payment:** Recipient must set up a trust line for RLUSD tokens first.

**Response:** (fee rate depends on the API key's tier — example below is Pro tier)
```json
{
  "success": true,
  "tx_hash": "transaction_hash",
  "fee_amount": 0.015,
  "fee_rate": 0.0015,
  "sent_amount": 9.985,
  "remaining_quota": null
}
```

### Verify Payment / Check Status

```bash
curl "http://localhost:8000/payment/verify/{tx_hash}" -H "X-API-Key: your_api_key"
curl "http://localhost:8000/payment/status/{tx_hash}" -H "X-API-Key: your_api_key"
```

### Check Supported Currencies & Fee Rates (no auth required)

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

## Usage Dashboard

Open http://localhost:8000/dashboard in a browser and enter an API key to see tier, this month's request count/remaining quota, cumulative fees per currency, recent transactions, and wallet address/balance — all on one screen.

The same data is also available via API:

```bash
# quota + cumulative fees + recent transactions (same data the dashboard page fetches)
curl "http://localhost:8000/usage/dashboard" -H "X-API-Key: your_api_key"

# transaction history only
curl "http://localhost:8000/usage/transactions?limit=50" -H "X-API-Key: your_api_key"

# quota only
curl "http://localhost:8000/usage/info" -H "X-API-Key: your_api_key"
```

## Rate Limiting

- **Free:** `429 Too Many Requests` after 100 requests/month
- **Pro / Enterprise:** Unlimited requests (billed via per-transaction fee instead)
- The limit is configurable via the `FREE_MONTHLY_LIMIT` environment variable

## Webhook Notifications

Sends `payment.success` / `payment.failed` events to a URL you register whenever a payment succeeds or fails. On failure, retries up to 3 times at 2s/10s/60s intervals.

```bash
# Register (a new signing secret is issued each time — only shown in this response)
curl -X PUT "http://localhost:8000/webhook" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_key" \
  -d '{"url": "https://your-server.com/xagent-webhook"}'

# Check current config
curl "http://localhost:8000/webhook" -H "X-API-Key: your_api_key"

# Remove
curl -X DELETE "http://localhost:8000/webhook" -H "X-API-Key: your_api_key"
```

On your receiving server, verify authenticity using the `X-XAgent-Signature: sha256=<hmac>` header:

```python
import hmac, hashlib

expected = hmac.new(webhook_secret.encode(), request_body, hashlib.sha256).hexdigest()
is_valid = hmac.compare_digest(expected, received_signature.removeprefix("sha256="))
```

Internal/private IPs (localhost, internal networks, etc.) cannot be registered as webhook URLs — blocked to prevent SSRF.

## x402 Payment

HTTP 402 Payment Required standard for AI agents

```bash
# 1. Request payment-required resource
curl "http://localhost:8000/data/market-info"
# → 402 Payment Required + payment info headers

# 2. Create x402 payment
curl -X POST "http://localhost:8000/x402/create-payment" \
  -H "X-API-Key: your_api_key"

# 3. Get access token
curl -X POST "http://localhost:8000/x402/pay" \
  -H "Content-Type: application/json" \
  -d '{"tx_hash": "transaction_hash"}'

# 4. Access resource with token
curl "http://localhost:8000/data/market-info" \
  -H "X-Payment-Token: access_token"
```

## RLUSD Trust Line Setup Guide

### What is a Trust Line?

A trust line is a credit limit you set to allow receiving IOU tokens (like RLUSD) on XRPL. You must set up a trust line for each token issuer.

### Setting Up Trust Line

#### 1. Using Xaman Wallet (Recommended)

```
1. Access Xaman wallet (https://xaman.app)
2. Go to testnet settings → "I want to add a trust line"
3. Enter the following information:
   - Currency: USD
   - Issuer: rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De
4. Set trust line limit (e.g., 1000)
5. Confirm and add
```

#### 2. Using XRPL Explorer

```
1. Access XRPL Testnet Explorer (https://testnet.xrpl.org)
2. Search for your wallet address
3. Go to "Trust Lines" tab → "Add Trust Line"
4. Currency: USD, Issuer: rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De
5. Set limit and add
```

### Check Trust Line

```bash
curl "http://localhost:8000/payment/trustline/{address}" \
  -H "X-API-Key: your_api_key"
```

**Response (No Trust Line):**
```json
{
  "address": "rExampleAddress...",
  "has_rlUSD_trustline": false,
  "rlUSD_limit": null,
  "rlUSD_balance": null,
  "message": "RLUSD trust line is not set up."
}
```

### Trust Line Error

If the recipient hasn't set up a trust line, an RLUSD payment returns:

```json
{
  "detail": "Recipient has not set up a trust line for RLUSD tokens. Please instruct the recipient to set up a trust line first."
}
```

**Solution:** Share the trust line setup guide above with the recipient.

## MCP Server (Claude AI Integration)

XAgent Pay API provides an MCP server that enables Claude AI to directly use payment tools.

### Installation and Setup

```bash
# Start XAgent Pay API server
python main.py

# Start MCP server (in a separate terminal)
python mcp_server.py
```

Set the API key MCP should use in `.env`:

```bash
MCP_API_KEY=your_api_key
```

### Claude Desktop Configuration

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

### Available MCP Tools

- **get_rates** — Get supported currencies and fee info
- **create_payment** — Create XRP/RLUSD payment
- **verify_payment** — Verify payment transaction
- **check_trustline** — Check RLUSD Trust Line

### Demo

Real result from Claude AI directly sending 1 XRP:
- Recipient: rM9SpkNUPUygwTcE7baTYTeZWP6BwhKePK
- Amount sent: 0.99 XRP
- Fee: 0.01 XRP (1%)
- TX Hash: CB2AC710B2EA8E335FB7EBEB258306CE96C30C0F09ABD728087C6099AC28D9AB

## Roadmap

- [x] x402 token support
- [x] RLUSD (stablecoin) support
- [x] MCP server support (Claude AI integration)
- [x] Issuable/revocable API keys with per-tier auth
- [x] Usage dashboard
- [x] Rate limiting + multi-wallet management
- [x] Webhook notifications
- [ ] Additional IOU token support
- [ ] Mainnet deployment
- [ ] Batch payments

## Known Limitations

- API key/transaction/webhook config are currently stored as JSON files. This is safe for a single process (`--workers 1`); scaling out to multiple workers/instances requires migrating to SQLite or similar (see [TODO_MIGRATION.md](TODO_MIGRATION.md) for details).
- Currently testnet-only. Mainnet deployment requires additional security review.

## Security

⚠️ **Currently testnet-only.** For mainnet, additionally review:
- Encrypted storage for secrets (`SENDER_SECRET`, wallet seeds)
- Migrating API key/admin key storage to SQLite with stronger access control
- Hardening the webhook SSRF guard (private/loopback IPs are currently blocked) against DNS rebinding

## License

MIT License

## GitHub Repository

This project is managed on GitHub. Please submit bug reports and feature requests via Issues.

---

Contact: [GitHub Issues](https://github.com/TLSRUF/xagent-pay-api/issues)
