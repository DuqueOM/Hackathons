import bank_client
from models import Base, User, Wallet
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def setup_in_memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal


def test_get_balance_creates_wallet_if_missing():
    SessionLocal = setup_in_memory_db()
    db = SessionLocal()
    user = User(phone="+521234567890")
    db.add(user)
    db.commit()
    db.refresh(user)

    balance = bank_client.get_balance(db, user.id)
    assert balance == 0.0


def test_perform_transfer_and_idempotency():
    SessionLocal = setup_in_memory_db()
    db = SessionLocal()

    user = User(phone="+521234567891")
    db.add(user)
    db.commit()
    db.refresh(user)

    wallet = Wallet(user_id=user.id, balance=1000.0)
    db.add(wallet)
    db.commit()

    client_tx_id = "tx-123"
    tx1 = bank_client.perform_transfer(
        db,
        payer_user_id=user.id,
        amount=100.0,
        destination_account="012345678901234567",
        client_tx_id=client_tx_id,
    )

    tx2 = bank_client.perform_transfer(
        db,
        payer_user_id=user.id,
        amount=100.0,
        destination_account="012345678901234567",
        client_tx_id=client_tx_id,
    )

    assert tx1.id == tx2.id


def test_insufficient_funds_raises():
    SessionLocal = setup_in_memory_db()
    db = SessionLocal()

    user = User(phone="+521234567892")
    db.add(user)
    db.commit()
    db.refresh(user)

    wallet = Wallet(user_id=user.id, balance=10.0)
    db.add(wallet)
    db.commit()

    try:
        bank_client.perform_transfer(
            db,
            payer_user_id=user.id,
            amount=100.0,
            destination_account="012345678901234567",
        )
    except bank_client.InsufficientFundsError:
        pass
    else:
        raise AssertionError("Expected InsufficientFundsError")
