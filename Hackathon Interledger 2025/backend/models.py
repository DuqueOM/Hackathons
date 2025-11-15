from sqlalchemy import Column, String, Integer, Float, DateTime, Boolean, JSON, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

Base = declarative_base()

def gen_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=gen_uuid)
    name = Column(String)
    phone = Column(String, unique=True, index=True)
    interledger_wallet_id = Column(String, nullable=True)
    wa_user_id = Column(String, nullable=True)
    clabe = Column(String, nullable=True)
    verified = Column(Boolean, default=False)
    password = Column(String, nullable=True)
    registration_timestamp = Column(DateTime, default=datetime.utcnow)

class Wallet(Base):
    __tablename__ = "wallets"
    id = Column(String, primary_key=True, default=gen_uuid)
    interledger_wallet_id = Column(String, unique=True, nullable=True)
    user_id = Column(String, ForeignKey("users.id"))
    balance = Column(Float, default=0.0)
    clabe = Column(String, nullable=True)
    pin_hash = Column(String, nullable=True)
    state_context = Column(String, nullable=True)
    currency = Column(String, default="MXN")
    account_address = Column(String, nullable=True)
    registration_timestamp = Column(DateTime, default=datetime.utcnow)

class Transaction(Base):
    __tablename__ = "transactions"
    id = Column(String, primary_key=True, default=gen_uuid)
    payer_wallet_id = Column(String, ForeignKey("wallets.id"))
    payee_wallet_id = Column(String, nullable=True)
    amount = Column(Float)
    currency = Column(String, default="MXN")
    concept = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="pending")
    preferred_method = Column(String, nullable=True)

class LookupLog(Base):
    __tablename__ = "lookups"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    phone = Column(String, index=True)
    line_type = Column(String, nullable=True)
    risk_score = Column(Float, nullable=True)
    sim_swap = Column(JSON, nullable=True)
    raw_response = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

class VerifyLog(Base):
    __tablename__ = "verify_logs"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    phone = Column(String, index=True)
    verify_sid = Column(String)
    channel = Column(String)
    status = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    raw_response = Column(JSON)

class PendingRequest(Base):
    __tablename__ = "pending_requests"
    id = Column(String, primary_key=True, default=gen_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=True)
    phone = Column(String, index=True)
    message_text = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="pending")  # pending, approved, executed, cancelled
    metadata = Column(JSON, nullable=True)
