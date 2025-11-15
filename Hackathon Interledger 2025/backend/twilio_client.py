import os
from twilio.rest import Client

API_KEY = os.getenv("TWILIO_API_KEY")
API_SECRET = os.getenv("TWILIO_API_KEY_SECRET")
ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
VERIFY_SERVICE_SID = os.getenv("VERIFY_SERVICE_SID")

# Use API Key + Secret for production safety
twilio_client = Client(API_KEY, API_SECRET, ACCOUNT_SID)

def lookup_phone(phone: str, fields: str = "line_type_intelligence,carrier"):
    return twilio_client.lookups.v2.phone_numbers(phone).fetch(fields=fields)

def create_verification_whatsapp(phone: str):
    return twilio_client.verify.services(VERIFY_SERVICE_SID).verifications.create(
        to=f"whatsapp:{phone}",
        channel="whatsapp"
    )

def check_verification(phone: str, code: str):
    return twilio_client.verify.services(VERIFY_SERVICE_SID).verification_checks.create(
        to=f"whatsapp:{phone}",
        code=code
    )
