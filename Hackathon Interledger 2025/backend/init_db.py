"""Simple DB init script.

Creates all tables and can optionally seed a demo user/wallet.

Usage:
  python init_db.py

Reads DATABASE_URL from the environment (see .env/.env.example).
"""

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

from models import Base, User, Wallet


load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set. Configure your .env file.")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)


def init_db(seed_demo: bool = True) -> None:
    Base.metadata.create_all(bind=engine)

    if not seed_demo:
        return

    db = SessionLocal()
    try:
        # create a demo user + wallet if not exists
        phone = "+521234567890"
        user = db.query(User).filter(User.phone == phone).first()
        if not user:
            user = User(phone=phone, name="Demo User", verified=False)
            db.add(user)
            db.commit()
            db.refresh(user)

        wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
        if not wallet:
            wallet = Wallet(user_id=user.id, balance=1000.0)
            db.add(wallet)
            db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    init_db(seed_demo=True)
    print("DB initialized and demo user created (if missing)")
