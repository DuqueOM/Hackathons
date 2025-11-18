"""Mock banking API client.

This module simulates a core banking / open banking API. In a real
scenario, this would:
- Authenticate with OAuth2 (client credentials) against the bank.
- Use TLS (and optionally mTLS) to connect to the bank's API.

For now, it uses in-process SQLAlchemy models to simulate balances and
transfers. This keeps the demo self-contained while allowing us to
later swap to a real HTTP client.

TODO: For production, move secrets (client_id, client_secret, token_url)
      to environment variables loaded from .env.
"""

from __future__ import annotations

import os
from typing import Optional

import httpx
from models import Transaction, Wallet
from sqlalchemy.orm import Session

TRANSFER_2FA_THRESHOLD = float(os.getenv("TRANSFER_2FA_THRESHOLD", "1000"))
BANK_CLIENT_MODE = os.getenv("BANK_CLIENT_MODE", "local").lower()

BANK_API_BASE_URL = os.getenv("BANK_API_BASE_URL", "")
BANK_API_TOKEN_URL = os.getenv("BANK_API_TOKEN_URL", "")
BANK_API_CLIENT_ID = os.getenv("BANK_API_CLIENT_ID", "")
BANK_API_CLIENT_SECRET = os.getenv("BANK_API_CLIENT_SECRET", "")
BANK_API_SCOPE = os.getenv("BANK_API_SCOPE", "")
BANK_API_TLS_CERT = os.getenv("BANK_API_TLS_CERT")
BANK_API_TLS_KEY = os.getenv("BANK_API_TLS_KEY")
BANK_API_TLS_CA = os.getenv("BANK_API_TLS_CA")


class InsufficientFundsError(Exception):
    pass


class DuplicateTransactionError(Exception):
    pass


def get_balance(db: Session, user_id: str) -> float:
    if BANK_CLIENT_MODE == "http":
        if not BANK_API_BASE_URL:
            raise RuntimeError("BANK_API_BASE_URL not configured")
        token = _get_access_token()
        url = f"{BANK_API_BASE_URL.rstrip('/')}/accounts/{user_id}/balance"
        with _build_http_client() as client:
            resp = client.get(url, headers={"Authorization": f"Bearer {token}"})
        resp.raise_for_status()
        data = resp.json()
        return float(data.get("balance", 0.0))

    wallet = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if not wallet:
        # create an empty wallet for demo
        wallet = Wallet(user_id=user_id, balance=0.0)
        db.add(wallet)
        db.commit()
        db.refresh(wallet)
    return float(wallet.balance or 0.0)


def perform_transfer(
    db: Session,
    payer_user_id: str,
    amount: float,
    destination_account: str,
    currency: str = "MXN",
    concept: str = "Transferencia WhatsApp",
    client_tx_id: Optional[str] = None,
) -> Transaction:
    """Perform a transfer.

    In "local" mode this is simulated using the SQLAlchemy models and
    idempotency is handled via the client_tx_id field. In "http" mode
    it calls an external bank API using OAuth2 client credentials.
    """

    if BANK_CLIENT_MODE == "http":
        if not BANK_API_BASE_URL:
            raise RuntimeError("BANK_API_BASE_URL not configured")
        token = _get_access_token()
        url = f"{BANK_API_BASE_URL.rstrip('/')}/transfers"
        payload = {
            "payer_user_id": payer_user_id,
            "amount": amount,
            "destination_account": destination_account,
            "currency": currency,
            "concept": concept,
            "client_tx_id": client_tx_id,
        }
        with _build_http_client() as client:
            resp = client.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=payload,
            )
        resp.raise_for_status()
        data = resp.json()
        # For simplicity we return a Transaction-like object using the
        # response fields when in HTTP mode.
        tx = Transaction(
            id=data.get("id"),
            payer_wallet_id=data.get("payer_wallet_id"),
            payee_wallet_id=data.get("payee_wallet_id"),
            amount=data.get("amount", amount),
            currency=data.get("currency", currency),
            concept=data.get("concept", concept),
            status=data.get("status", "completed"),
            client_tx_id=data.get("client_tx_id", client_tx_id),
            destination_account=data.get("destination_account", destination_account),
        )
        return tx

    if client_tx_id:
        existing = (
            db.query(Transaction)
            .filter(Transaction.client_tx_id == client_tx_id)
            .first()
        )
        if existing:
            return existing

    wallet = db.query(Wallet).filter(Wallet.user_id == payer_user_id).first()
    if not wallet:
        raise InsufficientFundsError("wallet_not_found")

    if (wallet.balance or 0.0) < amount:
        raise InsufficientFundsError("insufficient_funds")

    wallet.balance = float(wallet.balance) - float(amount)

    tx = Transaction(
        payer_wallet_id=wallet.id,
        payee_wallet_id=None,
        amount=amount,
        currency=currency,
        concept=concept,
        status="completed",
        client_tx_id=client_tx_id,
        destination_account=destination_account,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def is_2fa_required(amount: float) -> bool:
    return float(amount) >= TRANSFER_2FA_THRESHOLD


def _build_http_client() -> httpx.Client:
    verify: bool | str = True
    if BANK_API_TLS_CA:
        verify = BANK_API_TLS_CA
    cert = None
    if BANK_API_TLS_CERT and BANK_API_TLS_KEY:
        cert = (BANK_API_TLS_CERT, BANK_API_TLS_KEY)
    return httpx.Client(verify=verify, cert=cert, timeout=10.0)


def _get_access_token() -> str:
    if not (BANK_API_TOKEN_URL and BANK_API_CLIENT_ID and BANK_API_CLIENT_SECRET):
        raise RuntimeError("Bank OAuth2 client credentials not configured")

    data = {"grant_type": "client_credentials"}
    if BANK_API_SCOPE:
        data["scope"] = BANK_API_SCOPE

    resp = httpx.post(
        BANK_API_TOKEN_URL,
        data=data,
        auth=(BANK_API_CLIENT_ID, BANK_API_CLIENT_SECRET),
        timeout=10.0,
        verify=BANK_API_TLS_CA or True,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("No access_token in bank OAuth2 response")
    return token
