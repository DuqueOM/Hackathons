import os, asyncio, json, re
from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from datetime import datetime
from twilio.twiml.messaging_response import MessagingResponse

load_dotenv()

from models import Base, User, Wallet, Transaction, LookupLog, VerifyLog, PendingRequest
from twilio_client import lookup_phone, create_verification_whatsapp, check_verification
import utils

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

# create tables (simple approach)
Base.metadata.create_all(bind=engine)

app = FastAPI(title="Wallet WhatsApp Verify Minimal")

def send_whatsapp_response(text: str):
    tw = MessagingResponse()
    tw.message(text)
    return PlainTextResponse(content=str(tw), media_type="text/xml")

@app.post("/webhook/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    # validate Twilio signature for security
    await utils.validate_twilio_request(request)
    form = await request.form()
    from_number = form.get('From')
    body = (form.get('Body') or '').strip()
    if from_number and from_number.startswith('whatsapp:'):
        raw_phone = from_number.replace('whatsapp:', '')
    else:
        raw_phone = from_number

    try:
        phone_e164 = utils.to_e164(raw_phone, region='MX')
    except Exception:
        return send_whatsapp_response('Número inválido. Asegúrate de usar tu número registrado.')

    db = SessionLocal()

    # If the user is replying CONFIRMAR <code>
    m = re.match(r'^\s*confirmar\s+(\d{4,8})\s*$', body, re.I)
    if m:
        code = m.group(1)
        try:
            chk = check_verification(phone_e164, code)
        except Exception as e:
            return send_whatsapp_response('Error verificando código. Intenta nuevamente.')
        vlog = VerifyLog(user_id=None, phone=phone_e164, verify_sid=getattr(chk, 'sid', None), channel=getattr(chk, 'channel', None), status=getattr(chk, 'status', None), raw_response=chk.__dict__)
        db.add(vlog)
        db.commit()
        if getattr(chk, 'status', None) == 'approved':
            pr = db.query(PendingRequest).filter(PendingRequest.phone == phone_e164, PendingRequest.status == 'pending').order_by(PendingRequest.created_at.asc()).first()
            if not pr:
                return send_whatsapp_response('Verificación OK, pero no encontré ninguna solicitud pendiente.')
            pr.status = 'approved'
            db.commit()
            background_tasks.add_task(execute_pending_request, pr.id)
            return send_whatsapp_response('Código correcto ✅. Ejecutando tu solicitud. Te aviso cuando termine.')
        else:
            return send_whatsapp_response('Código incorrecto o expirado. Pide uno nuevo escribiendo: INICIAR')
    # else: new request
    user = db.query(User).filter(User.phone == phone_e164).first()
    if not user:
        user = User(phone=phone_e164, name=None, verified=False, registration_timestamp=datetime.utcnow())
        db.add(user)
        db.commit()
    pr = PendingRequest(user_id=user.id, phone=phone_e164, message_text=body, status='pending', created_at=datetime.utcnow())
    db.add(pr)
    db.commit()
    # background lookup + verify
    background_tasks.add_task(process_lookup_and_verify, phone_e164, user.id, pr.id)
    return send_whatsapp_response('Recibí tu mensaje. Para proteger tu cuenta, te envié un código por WhatsApp. Responde: CONFIRMAR <código>')

def process_lookup_and_verify(phone, user_id, pending_id):
    db = SessionLocal()
    try:
        try:
            lookup = lookup_phone(phone, fields='line_type_intelligence,carrier')
            raw = lookup.__dict__
            line_type = getattr(lookup, 'line_type_intelligence', None)
        except Exception as e:
            l = LookupLog(user_id=user_id, phone=phone, line_type=None, raw_response={'error': str(e)}, created_at=datetime.utcnow())
            db.add(l)
            db.commit()
            line_type = None
        else:
            l = LookupLog(user_id=user_id, phone=phone, line_type=line_type, raw_response=raw, created_at=datetime.utcnow())
            db.add(l)
            db.commit()
        try:
            v = create_verification_whatsapp(phone)
            vlog = VerifyLog(user_id=user_id, phone=phone, verify_sid=v.sid, channel='whatsapp', status='pending', raw_response={'sid': v.sid}, created_at=datetime.utcnow())
            db.add(vlog)
            db.commit()
        except Exception as e:
            vlog = VerifyLog(user_id=user_id, phone=phone, verify_sid=None, channel='whatsapp', status='error', raw_response={'error': str(e)}, created_at=datetime.utcnow())
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
        action_text = (pr.message_text or '').lower()
        result_text = ''
        if 'saldo' in action_text or 'balance' in action_text:
            wallet = db.query(Wallet).filter(Wallet.user_id == pr.user_id).first()
            bal = wallet.balance if wallet else 0.0
            result_text = f'Tu saldo es: {bal:.2f} MXN'
        elif action_text.startswith('enviar') or 'transferir' in action_text:
            import re
            m = re.search(r'(\d+(?:\.\d{1,2})?)', action_text)
            if not m:
                result_text = 'No pude detectar el monto. Escribe: ENVIAR 100.00 a CLABE 123...'
            else:
                amount = float(m.group(1))
                m2 = re.search(r'(\d{14,18})', action_text)
                if not m2:
                    result_text = 'No pude detectar la CLABE destino. Inclúyela en el mensaje.'
                else:
                    clabe = m2.group(1)
                    result_text = f'Transferencia simulada: {amount:.2f} MXN a CLABE {clabe} — STATUS: ejecutada (simulada).'
        else:
            result_text = "No entendí la solicitud. Ejemplos: 'Saldo' o 'Enviar 100 a 012345678901234567'."
        pr.status = 'executed'
        db.commit()
        print('Execution result for', pending_id, result_text)
    finally:
        db.close()
