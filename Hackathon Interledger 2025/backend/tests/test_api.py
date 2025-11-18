import main
from fastapi.testclient import TestClient
from models import Base, User, Wallet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def setup_sqlite_db():
    engine = create_engine(
        "sqlite:///./test_api.db", connect_args={"check_same_thread": False}
    )
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    # Re-wire main's engine/session for tests
    main.engine = engine
    main.SessionLocal = SessionLocal
    return SessionLocal


def get_client():
    setup_sqlite_db()
    client = TestClient(main.app)
    return client


def test_nlu_parse_endpoint():
    client = get_client()
    resp = client.post("/api/v1/nlu/parse", json={"text": "Consultar saldo"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["intent"]["name"] == "consultar_saldo"


def test_balance_endpoint():
    client = get_client()
    # para este endpoint no es necesario que exista el usuario de antemano
    user_id = "user-test-balance"
    resp = client.get(f"/api/v1/accounts/{user_id}/balance")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == user_id
    assert data["currency"] == "MXN"


def test_transfer_endpoint_creates_transaction():
    SessionLocal = setup_sqlite_db()
    db = SessionLocal()

    user = User(phone="+521234000000")
    db.add(user)
    db.commit()
    db.refresh(user)

    wallet = Wallet(user_id=user.id, balance=1000.0)
    db.add(wallet)
    db.commit()

    client = TestClient(main.app)

    payload = {
        "user_id": user.id,
        "amount": 200.0,
        "destination_account": "012345678901234567",
        "client_tx_id": "e2e-1",
    }
    resp = client.post("/api/v1/transfers", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "completed"
    assert data["amount"] == 200.0
