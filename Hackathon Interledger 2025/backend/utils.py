import phonenumbers
from twilio.request_validator import RequestValidator
import os
from fastapi import HTTPException

TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
validator = RequestValidator(TWILIO_AUTH_TOKEN)

def to_e164(number: str, region="MX"):
    try:
        p = phonenumbers.parse(number, region)
        if not phonenumbers.is_valid_number(p):
            raise ValueError("invalid number")
        return phonenumbers.format_number(p, phonenumbers.PhoneNumberFormat.E164)
    except Exception as e:
        raise

async def validate_twilio_request(request):
    signature = request.headers.get("X-Twilio-Signature") or request.headers.get("x-twilio-signature")
    if not signature:
        raise HTTPException(status_code=403, detail="missing twilio signature")
    form = await request.form()
    url = str(request.url)
    if not validator.validate(url, dict(form), signature):
        raise HTTPException(status_code=403, detail="invalid twilio signature")
