import bank_client


class DummyResponse:
    def __init__(self, data, status_code=200):
        self._data = data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("HTTP error in dummy response")

    def json(self):
        return self._data


class DummyClient:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, headers=None):
        return DummyResponse({"balance": 123.45})

    def post(self, url, headers=None, json=None):
        data = {
            "id": "tx-http-1",
            "payer_wallet_id": "wallet-1",
            "payee_wallet_id": None,
            "amount": json.get("amount", 0.0) if json else 0.0,
            "currency": json.get("currency", "MXN") if json else "MXN",
            "concept": (
                json.get("concept", "Transferencia WhatsApp")
                if json
                else "Transferencia WhatsApp"
            ),
            "status": "completed",
            "client_tx_id": json.get("client_tx_id") if json else None,
            "destination_account": json.get("destination_account") if json else None,
        }
        return DummyResponse(data)


def test_get_balance_http_mode_uses_external_api(monkeypatch):
    # Configure bank_client for http mode
    bank_client.BANK_CLIENT_MODE = "http"
    bank_client.BANK_API_BASE_URL = "https://bank.example.com"

    monkeypatch.setattr(bank_client, "_get_access_token", lambda: "fake-token")
    monkeypatch.setattr(bank_client, "_build_http_client", lambda: DummyClient())

    balance = bank_client.get_balance(db=None, user_id="user-1")
    assert balance == 123.45


def test_perform_transfer_http_mode_returns_tx_like_object(monkeypatch):
    bank_client.BANK_CLIENT_MODE = "http"
    bank_client.BANK_API_BASE_URL = "https://bank.example.com"

    monkeypatch.setattr(bank_client, "_get_access_token", lambda: "fake-token")
    monkeypatch.setattr(bank_client, "_build_http_client", lambda: DummyClient())

    tx = bank_client.perform_transfer(
        db=None,
        payer_user_id="user-1",
        amount=200.0,
        destination_account="012345678901234567",
        currency="MXN",
        concept="Test",
        client_tx_id="cli-http-1",
    )

    assert tx.id == "tx-http-1"
    assert tx.amount == 200.0
    assert tx.currency == "MXN"
    assert tx.client_tx_id == "cli-http-1"
    assert tx.destination_account == "012345678901234567"
