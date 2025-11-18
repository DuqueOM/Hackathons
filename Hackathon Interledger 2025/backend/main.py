import os
import re
from collections import defaultdict, deque
from datetime import datetime, timedelta
from time import time
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv()

import bank_client
import nlu
import utils
from models import Base, LookupLog, PendingRequest, User, VerifyLog, Wallet
from twilio_client import check_verification, create_verification_whatsapp, lookup_phone

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

# create tables (simple approach)
Base.metadata.create_all(bind=engine)

OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
OTP_LOCK_MINUTES = int(os.getenv("OTP_LOCK_MINUTES", "5"))
RATE_LIMIT_WHATSAPP_PER_MINUTE = int(os.getenv("RATE_LIMIT_WHATSAPP_PER_MINUTE", "30"))
RATE_LIMIT_VERIFY_PER_MINUTE = int(os.getenv("RATE_LIMIT_VERIFY_PER_MINUTE", "10"))

_rate_limit_store = defaultdict(deque)


def _check_rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    now = time()
    dq = _rate_limit_store[key]
    while dq and dq[0] <= now - window_seconds:
        dq.popleft()
    if len(dq) >= limit:
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")
    dq.append(now)


def _get_or_create_user_by_phone(db, phone_e164: str) -> User:
    user = db.query(User).filter(User.phone == phone_e164).first()
    if not user:
        user = User(
            phone=phone_e164,
            name=None,
            verified=False,
            registration_timestamp=datetime.utcnow(),
        )
        db.add(user)
        db.commit()
    return user


def _ensure_user_not_locked(user: User) -> None:
    if user.otp_locked_until and user.otp_locked_until > datetime.utcnow():
        raise HTTPException(status_code=423, detail="otp_locked")


def _register_otp_result(db, user: User, status_val: Optional[str]) -> None:
    if not user:
        return
    if status_val == "approved":
        user.otp_failed_attempts = 0
        user.otp_locked_until = None
        user.verified = True
    else:
        current = user.otp_failed_attempts or 0
        current += 1
        user.otp_failed_attempts = current
        if current >= OTP_MAX_ATTEMPTS:
            user.otp_locked_until = datetime.utcnow() + timedelta(
                minutes=OTP_LOCK_MINUTES
            )
    db.commit()


app = FastAPI(title="Wallet WhatsApp Verify Minimal")


class VerifySendRequest(BaseModel):
    phone: str
    channel: str = "whatsapp"


class VerifyCheckRequest(BaseModel):
    phone: str
    code: str


class NLUParseRequest(BaseModel):
    text: str


class TransferRequest(BaseModel):
    user_id: str
    amount: float
    destination_account: str
    currency: Optional[str] = "MXN"
    concept: Optional[str] = "Transferencia WhatsApp"
    client_tx_id: Optional[str] = None


def send_whatsapp_response(text: str):
    tw = MessagingResponse()
    tw.message(text)
    return PlainTextResponse(content=str(tw), media_type="text/xml")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    # validate Twilio signature for security
    await utils.validate_twilio_request(request)
    form = await request.form()
    from_number = form.get("From")
    body = (form.get("Body") or "").strip()
    if from_number and from_number.startswith("whatsapp:"):
        raw_phone = from_number.replace("whatsapp:", "")
    else:
        raw_phone = from_number

    try:
        phone_e164 = utils.to_e164(raw_phone, region="MX")
    except Exception:
        return send_whatsapp_response(
            "Número inválido. Asegúrate de usar tu número registrado."
        )

    db = SessionLocal()

    # Rate limit per phone number for inbound webhook
    if raw_phone:
        try:
            phone_for_rl = utils.to_e164(raw_phone, region="MX")
            _check_rate_limit(f"wa:{phone_for_rl}", RATE_LIMIT_WHATSAPP_PER_MINUTE)
        except Exception:
            pass

    # If the user is replying CONFIRMAR <code>
    m = re.match(r"^\s*confirmar\s+(\d{4,8})\s*$", body, re.I)
    if m:
        code = m.group(1)
        try:
            user = _get_or_create_user_by_phone(db, phone_e164)
            _ensure_user_not_locked(user)
            chk = check_verification(phone_e164, code)
        except Exception:
            return send_whatsapp_response(
                "Error verificando código. Intenta nuevamente."
            )
        vlog = VerifyLog(
            user_id=None,
            phone=phone_e164,
            verify_sid=getattr(chk, "sid", None),
            channel=getattr(chk, "channel", None),
            status=getattr(chk, "status", None),
            raw_response=chk.__dict__,
        )
        db.add(vlog)
        db.commit()

        status_val = getattr(chk, "status", None)
        _register_otp_result(db, user, status_val)

        if status_val == "approved":
            pr = (
                db.query(PendingRequest)
                .filter(
                    PendingRequest.phone == phone_e164,
                    PendingRequest.status == "pending",
                )
                .order_by(PendingRequest.created_at.asc())
                .first()
            )
            if not pr:
                return send_whatsapp_response(
                    "Verificación OK, pero no encontré ninguna solicitud pendiente."
                )
            pr.status = "approved"
            db.commit()
            background_tasks.add_task(execute_pending_request, pr.id)
            return send_whatsapp_response(
                "Código correcto ✅. Ejecutando tu solicitud. Te aviso cuando termine."
            )
        else:
            return send_whatsapp_response(
                "Código incorrecto o expirado. Pide uno nuevo escribiendo: INICIAR"
            )
    # else: new request
    user = _get_or_create_user_by_phone(db, phone_e164)
    pr = PendingRequest(
        user_id=user.id,
        phone=phone_e164,
        message_text=body,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(pr)
    db.commit()
    # background lookup + verify
    background_tasks.add_task(process_lookup_and_verify, phone_e164, user.id, pr.id)
    return send_whatsapp_response(
        "Recibí tu mensaje. Para proteger tu cuenta, te envié un código por WhatsApp. Responde: CONFIRMAR <código>"
    )


def process_lookup_and_verify(phone, user_id, pending_id):
    db = SessionLocal()
    try:
        try:
            lookup = lookup_phone(phone, fields="line_type_intelligence,carrier")
            raw = lookup.__dict__
            line_type = getattr(lookup, "line_type_intelligence", None)
        except Exception as e:
            l = LookupLog(
                user_id=user_id,
                phone=phone,
                line_type=None,
                raw_response={"error": str(e)},
                created_at=datetime.utcnow(),
            )
            db.add(l)
            db.commit()
            line_type = None
        else:
            l = LookupLog(
                user_id=user_id,
                phone=phone,
                line_type=line_type,
                raw_response=raw,
                created_at=datetime.utcnow(),
            )
            db.add(l)
            db.commit()
        try:
            v = create_verification_whatsapp(phone)
            vlog = VerifyLog(
                user_id=user_id,
                phone=phone,
                verify_sid=v.sid,
                channel="whatsapp",
                status="pending",
                raw_response={"sid": v.sid},
                created_at=datetime.utcnow(),
            )
            db.add(vlog)
            db.commit()
        except Exception as e:
            vlog = VerifyLog(
                user_id=user_id,
                phone=phone,
                verify_sid=None,
                channel="whatsapp",
                status="error",
                raw_response={"error": str(e)},
                created_at=datetime.utcnow(),
            )
            db.add(vlog)
            db.commit()
    finally:
        db.close()


def execute_pending_request(pending_id):
    db = SessionLocal()
    try:
        pr = db.query(PendingRequest).filter(PendingRequest.id == pending_id).first()
        if not pr:
            return
        parsed = nlu.parse_text(pr.message_text or "")
        intent = (parsed.get("intent") or {}).get("name")
        entities = parsed.get("entities") or {}
        result_text = ""

        if intent == nlu.INTENT_CONSULTAR_SALDO:
            wallet = db.query(Wallet).filter(Wallet.user_id == pr.user_id).first()
            bal = wallet.balance if wallet else 0.0
            result_text = f"Tu saldo es: {bal:.2f} MXN"
        elif intent == nlu.INTENT_TRANSFERIR:
            amount = entities.get("amount")
            dest = entities.get("destination_account")
            if amount is None or not dest:
                result_text = (
                    "No pude detectar monto o cuenta destino. "
                    "Ejemplo: 'Transferir 100.00 a 012345678901234567'."
                )
            else:
                client_tx_id = (
                    (pr.metadata or {}).get("client_tx_id") if pr.metadata else None
                )
                if not client_tx_id:
                    client_tx_id = f"wa-{pr.id}"
                try:
                    tx = bank_client.perform_transfer(
                        db,
                        payer_user_id=pr.user_id,
                        amount=float(amount),
                        destination_account=str(dest),
                        client_tx_id=client_tx_id,
                    )
                    result_text = (
                        f"Transferencia de {tx.amount:.2f} {tx.currency} "
                        f"a cuenta {tx.destination_account} completada."
                    )
                except bank_client.InsufficientFundsError:
                    result_text = "Saldo insuficiente para completar la transferencia."
        else:
            result_text = "No entendí la solicitud. Ejemplos: 'Saldo' o 'Enviar 100 a 012345678901234567'."
        pr.status = "executed"
        db.commit()
        print("Execution result for", pending_id, result_text)
    finally:
        db.close()


@app.post("/api/v1/verify/send")
async def api_verify_send(payload: VerifySendRequest):
    try:
        phone_e164 = utils.to_e164(payload.phone, region="MX")
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_phone_number")

    db = SessionLocal()
    try:
        _check_rate_limit(f"verify_send:{phone_e164}", RATE_LIMIT_VERIFY_PER_MINUTE)
        v = create_verification_whatsapp(phone_e164)
        vlog = VerifyLog(
            user_id=None,
            phone=phone_e164,
            verify_sid=v.sid,
            channel=payload.channel,
            status="pending",
            raw_response={"sid": v.sid},
            created_at=datetime.utcnow(),
        )
        db.add(vlog)
        db.commit()
        return {"status": "pending", "sid": v.sid}
    except Exception:
        raise HTTPException(status_code=400, detail="verification_send_failed")
    finally:
        db.close()


@app.post("/api/v1/verify/check")
async def api_verify_check(payload: VerifyCheckRequest):
    try:
        phone_e164 = utils.to_e164(payload.phone, region="MX")
    except Exception:
        raise HTTPException(status_code=400, detail="invalid_phone_number")

    db = SessionLocal()
    try:
        _check_rate_limit(f"verify_check:{phone_e164}", RATE_LIMIT_VERIFY_PER_MINUTE)
        user = _get_or_create_user_by_phone(db, phone_e164)
        _ensure_user_not_locked(user)
        chk = check_verification(phone_e164, payload.code)
        status_val = getattr(chk, "status", None)
        vlog = VerifyLog(
            user_id=None,
            phone=phone_e164,
            verify_sid=getattr(chk, "sid", None),
            channel=getattr(chk, "channel", None) or "whatsapp",
            status=status_val,
            raw_response=chk.__dict__,
            created_at=datetime.utcnow(),
        )
        db.add(vlog)
        db.commit()

        _register_otp_result(db, user, status_val)

        if status_val == "approved":
            return {"status": status_val, "approved": True}
        else:
            return {"status": status_val, "approved": False}
    except Exception:
        raise HTTPException(status_code=400, detail="verification_check_failed")
    finally:
        db.close()


@app.post("/api/v1/nlu/parse")
async def api_nlu_parse(payload: NLUParseRequest):
    return nlu.parse_text(payload.text)


@app.get("/api/v1/accounts/{user_id}/balance")
async def api_get_balance(user_id: str):
    db = SessionLocal()
    try:
        balance = bank_client.get_balance(db, user_id)
        return {"user_id": user_id, "balance": balance, "currency": "MXN"}
    finally:
        db.close()


@app.post("/api/v1/transfers")
async def api_create_transfer(payload: TransferRequest):
    db = SessionLocal()
    try:
        requires_2fa = bank_client.is_2fa_required(payload.amount)
        try:
            tx = bank_client.perform_transfer(
                db,
                payer_user_id=payload.user_id,
                amount=payload.amount,
                destination_account=payload.destination_account,
                currency=payload.currency or "MXN",
                concept=payload.concept or "Transferencia WhatsApp",
                client_tx_id=payload.client_tx_id,
            )
        except bank_client.InsufficientFundsError:
            raise HTTPException(status_code=400, detail="insufficient_funds")
        return {
            "id": tx.id,
            "status": tx.status,
            "requires_2fa": requires_2fa,
            "amount": tx.amount,
            "currency": tx.currency,
        }
    finally:
        db.close()
