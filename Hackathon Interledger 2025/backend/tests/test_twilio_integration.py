import re

import main
import responses
from fastapi.testclient import TestClient


@responses.activate
def test_verify_send_uses_twilio_verify_api():
    # Mock Twilio Verify endpoint
    pattern = re.compile(r"https://verify\.twilio\.com/v2/Services/.*/Verifications")
    responses.add(
        responses.POST,
        pattern,
        json={"sid": "VEXXXXXXXXXXXXXXXXXXXXXXXXXXXX", "status": "pending"},
        status=201,
    )

    client = TestClient(main.app)

    resp = client.post(
        "/api/v1/verify/send",
        json={"phone": "+521234567890"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert "sid" in data
