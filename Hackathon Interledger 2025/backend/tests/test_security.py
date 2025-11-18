import main
import pytest
from fastapi import HTTPException
from models import Base, User
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def setup_in_memory_db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal


def test_rate_limit_exceeded_raises_http_exception():
    main._rate_limit_store.clear()
    key = "test-key"
    limit = 3

    # first `limit` calls should pass
    for _ in range(limit):
        main._check_rate_limit(key, limit)

    # next call within the same window should raise 429
    with pytest.raises(HTTPException) as exc:
        main._check_rate_limit(key, limit)
    assert exc.value.status_code == 429


def test_otp_lock_and_reset():
    SessionLocal = setup_in_memory_db()
    db = SessionLocal()

    user = User(phone="+521234567800")
    db.add(user)
    db.commit()
    db.refresh(user)

    # make the thresholds small for the test
    main.OTP_MAX_ATTEMPTS = 2
    main.OTP_LOCK_MINUTES = 1

    # first failed attempt: should increment counter but not lock yet
    main._register_otp_result(db, user, status_val="denied")
    db.refresh(user)
    assert user.otp_failed_attempts == 1
    assert user.otp_locked_until is None

    # second failed attempt: should lock the user
    main._register_otp_result(db, user, status_val="denied")
    db.refresh(user)
    assert user.otp_failed_attempts == 2
    assert user.otp_locked_until is not None

    with pytest.raises(HTTPException) as exc:
        main._ensure_user_not_locked(user)
    assert exc.value.status_code == 423

    # approved OTP should reset counters and lock
    main._register_otp_result(db, user, status_val="approved")
    db.refresh(user)
    assert user.otp_failed_attempts == 0
    assert user.otp_locked_until is None
    assert user.verified is True
