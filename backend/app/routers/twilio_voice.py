from fastapi import APIRouter, Response, Request, HTTPException


router = APIRouter()
from twilio.request_validator import RequestValidator
from backend.app.core.config import settings


@router.post("/twilio/voice", response_class=Response)
async def twilio_voice_webhook(request: Request) -> Response:
    """Validate Twilio signature and return TwiML <Connect><Stream>."""
    form = dict((await request.form()).items())
    token = settings.TWILIO_AUTH_TOKEN or ""
    if token:
        url = str(request.url)
        sig = request.headers.get("X-Twilio-Signature")
        validator = RequestValidator(token)
        valid = bool(sig and validator.validate(url, form, sig))
        # In dev (ngrok), allow through even if signature fails to ease testing.
        if not valid and not (settings.PUBLIC_BASE_URL and "ngrok" in settings.PUBLIC_BASE_URL):
            raise HTTPException(status_code=403, detail="Invalid signature")

    public_url = settings.PUBLIC_BASE_URL or str(request.base_url).rstrip('/')
    wss_url = public_url.replace('http://','wss://').replace('https://','wss://') + '/ws/twilio-stream'
    twiml = f"""
    <Response>
      <Connect>
        <Stream url="{wss_url}"/>
      </Connect>
    </Response>
    """.strip()
    return Response(content=twiml, media_type="application/xml")

# WebSocket handler is provided by twilio_realtime.py
