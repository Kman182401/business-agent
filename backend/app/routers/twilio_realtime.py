import asyncio
import base64
import json
import audioop
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websockets.client import connect as ws_connect

from backend.app.core.config import settings


router = APIRouter()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


@router.websocket("/ws/twilio-stream")
async def realtime_bridge(websocket: WebSocket) -> None:
    # Single WS used for Twilio Media Streams <-> OpenAI Realtime audio.
    await websocket.accept()

    model = settings.REALTIME_MODEL
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        # Dev fallback: keep socket alive if no API key.
        try:
            while True:
                _ = await websocket.receive_text()
        except WebSocketDisconnect:
            return

    url = f"wss://api.openai.com/v1/realtime?model={model}"
    headers = [("Authorization", f"Bearer {api_key}")]

    # State for rate conversion and basic VAD
    up_state: Optional[tuple] = None    # 8k -> 16k
    down_state: Optional[tuple] = None  # 16k -> 8k

    # Naive VAD thresholds (tune live as needed)
    SILENCE_MS = 700
    MIN_SPEECH_MS = 1200
    RMS_THRESH = 200

    async with ws_connect(url, extra_headers=headers, max_size=None) as ai_ws:
        # Session settings + greeting so the caller hears something immediately
        await ai_ws.send(json.dumps({
            "type": "session.update",
            "session": {
                "instructions": (
                    "You are the front-desk assistant for Demo Bistro. "
                    "Be concise, friendly, and confirm reservation details: date, time, party size, name, and phone."
                ),
                "voice": "verse"
            }
        }))
        await ai_ws.send(json.dumps({"type": "response.create"}))

        import time
        last_voice_ts = time.monotonic()
        speech_started_ts: Optional[float] = None

        async def pump_twilio_to_ai():
            nonlocal up_state, last_voice_ts, speech_started_ts
            while True:
                raw = await websocket.receive_text()
                evt = json.loads(raw)
                et = evt.get("event")
                if et == "media":
                    mulaw = _b64d(evt["media"]["payload"])
                    pcm16_8k = audioop.ulaw2lin(mulaw, 2)
                    pcm16_16k, up_state = audioop.ratecv(pcm16_8k, 2, 1, 8000, 16000, up_state)
                    await ai_ws.send(json.dumps({
                        "type": "input_audio_buffer.append",
                        "audio": _b64(pcm16_16k),
                    }))

                    # Simple VAD on 8k PCM
                    now = time.monotonic()
                    rms = audioop.rms(pcm16_8k, 2)
                    if rms > RMS_THRESH:
                        last_voice_ts = now
                        speech_started_ts = speech_started_ts or now
                    else:
                        if speech_started_ts and (now - speech_started_ts) * 1000 >= MIN_SPEECH_MS \
                           and (now - last_voice_ts) * 1000 >= SILENCE_MS:
                            await ai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                            await ai_ws.send(json.dumps({"type": "response.create"}))
                            speech_started_ts = None
                elif et == "stop":
                    # Defensive finalize on stream end
                    await ai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    await ai_ws.send(json.dumps({"type": "response.create"}))

        async def pump_ai_to_twilio():
            nonlocal down_state
            async for raw in ai_ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                # Extract audio payload(s) — formats vary slightly
                audio_b64 = (
                    (msg.get("delta") or {}).get("audio")
                    or (msg.get("audio") or {}).get("data")
                )
                if not audio_b64:
                    continue
                pcm16_16k = _b64d(audio_b64)
                pcm16_8k, down_state = audioop.ratecv(pcm16_16k, 2, 1, 16000, 8000, down_state)
                mulaw = audioop.lin2ulaw(pcm16_8k, 2)
                await websocket.send_text(json.dumps({
                    "event": "media",
                    "media": {"payload": _b64(mulaw)},
                }))

        try:
            await asyncio.gather(pump_twilio_to_ai(), pump_ai_to_twilio())
        except WebSocketDisconnect:
            return
