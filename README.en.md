# XAgent Pay API

XRPL-based Payment API for AI Agents and Developers

## Overview

FastAPI-based XRPL (XRP Ledger) testnet payment server. Abstracts complex blockchain logic to enable easy integration of XRP and RLUSD payments for AI agents and applications.

**Supported Currencies:** XRP, RLUSD (Stablecoin)

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment variables (.env file)
SENDER_ADDRESS=your_testnet_XRP_address
SENDER_SECRET=your_secret_key
FEE_ACCOUNT=your_fee_account_address
XRPL_NODE=wss://s.altnet.rippletest.net:51233
RLUSD_ISSUER=rMxCKbEDwqr76QuheSUMdEGf4B9xJ8m5De
```

Testnet account: [XRPL Faucet](https://xrpl.org/xrp-testnet-faucet.html)

## Running the Server

```bash
# Development mode
python main.py

# Production
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

- API: http://localhost:8000
- Swagger Docs: http://localhost:8000/docs

## API Usage

All requests require API key authentication. Include `X-API-Key` header in your requests.

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

**Before RLUSD Payment:** Recipient must set up a trust line for RLUSD tokens first.

**Response:**
```json
{
  "success": true,
  "tx_hash": "transaction_hash",
  "fee_amount": 0.1,
  "sent_amount": 9.9
}
```

### Verify Payment

```bash
curl "http://localhost:8000/payment/verify/{tx_hash}" \
  -H "X-API-Key: your_api_key"
```

### Check Status

```bash
curl "http://localhost:8000/payment/status/{tx_hash}" \
  -H "X-API-Key: your_api_key"
```

### Check Supported Currencies

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

### x402 Payment

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

### Authentication Errors

| Code | Description |
|------|-------------|
| 401 | Missing or invalid API key |
| 403 | Insufficient API key permissions |

## Fee Structure

| Type | Rate |
|------|------|
| Application Fee | 1% |
| Network Fee | 0.00001 XRP (XRPL base) |

**Example:** 100 XRP or 100 RLUSD payment
- Fee: 1 (in respective currency)
- Sent Amount: 99 (in respective currency)

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
# Check RLUSD trust line for specific address
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

**Response (Trust Line Exists):**
```json
{
  "address": "rExampleAddress...",
  "has_rlUSD_trustline": true,
  "rlUSD_limit": 1000.0,
  "rlUSD_balance": 50.0,
  "message": "RLUSD trust line is set up."
}
```

### Trust Line Error

```bash
# Attempt RLUSD payment (recipient without trust line)
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
  "detail": "Recipient has not set up a trust line for RLUSD tokens. Please instruct the recipient to set up a trust line first."
}
```

**Solution:** Share the trust line setup guide above with the recipient.

## Roadmap

- [x] x402 token support
- [x] RLUSD (stablecoin) support
- [ ] Additional IOU token support
- [ ] Mainnet deployment
- [ ] Webhook notifications
- [ ] Batch payments

## Security

**Currently testnet-only.** Mainnet deployment requires security hardening:
- Authentication/authorization system
- Rate limiting
- Encrypted secret key storage

## License

MIT License

## GitHub Repository

This project is managed on GitHub. Please submit bug reports and feature requests via Issues.

---

Contact: [GitHub Issues](https://github.com/TLSRUF/xagent-pay-api/issues)
