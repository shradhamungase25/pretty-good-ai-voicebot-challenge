"""
server.py — the bridge that makes the actual voice conversation happen.

Flow:
  1. Twilio calls +1-805-439-8008 and connects a Media Stream (raw G.711
     u-law 8kHz audio over a WebSocket) to this server's /media-stream route.
  2. We open a second WebSocket to OpenAI's Realtime API and configure it
     with a "patient" persona for the requested scenario.
  3. Twilio's inbound audio (the clinic agent's voice) is forwarded directly
     to OpenAI (same codec — no transcoding needed).
  4. OpenAI's spoken response (the simulated patient's voice) is forwarded
     directly back to Twilio.
  5. We use OpenAI's server-side voice activity detection for turn-taking,
     and handle barge-in by clearing Twilio's playback buffer + canceling
     the in-flight OpenAI response when the agent starts talking over the
     patient (or vice versa).
  6. Transcripts (both sides, OpenAI's own ASR + its text output) are
     accumulated and written to transcripts/<call_id>.txt when the stream
     ends.

Twilio is also configured (see make_call.py) to record the raw call audio
server-side, which we download separately as the mp3/ogg deliverable — that
recording is the audio of record, this server is just the "brain".
"""

import asyncio
import base64
import json
import os
import time
from datetime import datetime

import websockets
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from scenarios import SCENARIOS, build_instructions

load_dotenv()

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
# gpt-4o-realtime-preview-* models and the beta wire protocol were removed by
# OpenAI on 2026-05-12. "gpt-realtime" is the current GA model alias.
REALTIME_MODEL = os.environ.get("OPENAI_REALTIME_MODEL", "gpt-realtime")
REALTIME_URL = f"wss://api.openai.com/v1/realtime?model={REALTIME_MODEL}"
TRANSCRIPT_DIR = os.path.join(os.path.dirname(__file__), "transcripts")

app = FastAPI()


@app.post("/outbound/twiml")
async def outbound_twiml(request: Request):
    """Twilio fetches this to learn what to do with the call we placed."""
    scenario_id = request.query_params.get("scenario", SCENARIOS[0]["id"])
    call_label = request.query_params.get("call_label", scenario_id)
    host = request.url.hostname
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
  <Connect>
    <Stream url="wss://{host}/media-stream">
      <Parameter name="scenario" value="{scenario_id}" />
      <Parameter name="call_label" value="{call_label}" />
    </Stream>
  </Connect>
</Response>"""
    return Response(content=twiml, media_type="text/xml")


@app.websocket("/media-stream")
async def media_stream(websocket: WebSocket):
    await websocket.accept()

    state = {
        "stream_sid": None,
        "scenario": SCENARIOS[0],
        "call_label": "call",
        "transcript": [],          # list of (speaker, text)
        "current_agent_text": "",
        "current_patient_text": "",
        "started_at": time.time(),
        "response_active": False,  # tracks whether OpenAI currently has a
                                    # response in flight, so we only send
                                    # response.cancel when there's actually
                                    # something to cancel.
    }

    async with websockets.connect(
        REALTIME_URL,
        extra_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
        },
        max_size=None,
    ) as oai_ws:

        async def configure_session(scenario: dict):
            await oai_ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    # GA requires an explicit session type ("realtime" for a
                    # speech-to-speech agent session, vs "transcription").
                    "type": "realtime",
                    # "modalities" was renamed "output_modalities" in GA.
                    "output_modalities": ["audio"],
                    "instructions": build_instructions(scenario),
                    # Audio config moved from flat top-level fields
                    # (input_audio_format / output_audio_format / voice /
                    # input_audio_transcription / turn_detection) into a
                    # nested "audio.input" / "audio.output" object in GA.
                    # Format strings also changed: "g711_ulaw" -> the
                    # structured {"type": "audio/pcmu"} object (Twilio's
                    # codec is G.711 u-law, which OpenAI now calls pcmu).
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcmu"},
                            "transcription": {"model": "whisper-1"},
                            "turn_detection": {
                                "type": "server_vad",
                                "threshold": 0.5,
                                "prefix_padding_ms": 300,
                                "silence_duration_ms": 500,
                            },
                        },
                        "output": {
                            "format": {"type": "audio/pcmu"},
                            "voice": scenario.get("voice", "alloy"),
                        },
                    },
                },
            }))
            # Kick the patient off so they speak first, like a real caller
            # would once the line connects (clinic agent usually greets first
            # in practice, so we just wait — comment out the next block if
            # your target IVR expects the caller to speak first).

        async def twilio_to_openai():
            try:
                async for raw in websocket.iter_text():
                    msg = json.loads(raw)
                    event = msg.get("event")

                    if event == "start":
                        state["stream_sid"] = msg["start"]["streamSid"]
                        params = msg["start"].get("customParameters", {})
                        scenario_id = params.get("scenario", SCENARIOS[0]["id"])
                        state["scenario"] = next(
                            (s for s in SCENARIOS if s["id"] == scenario_id), SCENARIOS[0]
                        )
                        state["call_label"] = params.get("call_label", scenario_id)
                        await configure_session(state["scenario"])

                    elif event == "media":
                        audio_b64 = msg["media"]["payload"]
                        await oai_ws.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": audio_b64,
                        }))

                    elif event == "stop":
                        break
            except WebSocketDisconnect:
                pass
            finally:
                await oai_ws.close()

        async def openai_to_twilio():
            async for raw in oai_ws:
                event = json.loads(raw)
                etype = event.get("type")

                # "response.audio.delta" was renamed "response.output_audio.delta" in GA.
                if etype == "response.output_audio.delta":
                    if state["stream_sid"]:
                        await websocket.send_text(json.dumps({
                            "event": "media",
                            "streamSid": state["stream_sid"],
                            "media": {"payload": event["delta"]},
                        }))

                elif etype == "input_audio_buffer.speech_started":
                    # Agent (the "other side") started talking — if the
                    # patient is mid-sentence, stop their audio + cancel the
                    # in-flight response so we don't talk over each other
                    # forever. This is also how we capture genuine barge-in
                    # behavior on the patient's side for the barge_in scenario.
                    if state["stream_sid"]:
                        await websocket.send_text(json.dumps({
                            "event": "clear",
                            "streamSid": state["stream_sid"],
                        }))
                    # Only cancel if a response is actually in flight —
                    # sending response.cancel with nothing active is exactly
                    # what was producing the response_cancel_not_active
                    # errors flooding every transcript.
                    if state["response_active"]:
                        try:
                            await oai_ws.send(json.dumps({"type": "response.cancel"}))
                        except Exception:
                            pass
                        state["response_active"] = False

                elif etype == "response.created":
                    state["response_active"] = True

                elif etype in ("response.done", "response.cancelled"):
                    state["response_active"] = False

                elif etype == "conversation.item.input_audio_transcription.completed":
                    # Unchanged in GA — same event name as beta.
                    # This is the OTHER side of the call (the clinic agent),
                    # transcribed by OpenAI's ASR on the input audio.
                    text = event.get("transcript", "").strip()
                    if text:
                        state["transcript"].append(("AGENT", text))

                elif etype == "response.output_audio_transcript.done":
                    # This is OUR simulated patient's spoken line. Renamed
                    # from "response.audio_transcript.done" in GA.
                    text = event.get("transcript", "").strip()
                    if text:
                        state["transcript"].append(("PATIENT", text))

                elif etype == "error":
                    state["transcript"].append(("SYSTEM_ERROR", json.dumps(event)))

        try:
            await asyncio.gather(twilio_to_openai(), openai_to_twilio())
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            _write_transcript(state)


def _write_transcript(state: dict):
    os.makedirs(TRANSCRIPT_DIR, exist_ok=True)
    label = state["call_label"]
    path = os.path.join(TRANSCRIPT_DIR, f"{label}.txt")
    duration = round(time.time() - state["started_at"], 1)
    with open(path, "w") as f:
        f.write(f"# Call: {label}\n")
        f.write(f"# Scenario: {state['scenario']['id']} — {state['scenario']['title']}\n")
        f.write(f"# Timestamp: {datetime.utcnow().isoformat()}Z\n")
        f.write(f"# Duration (stream-open time): {duration}s\n\n")
        for speaker, text in state["transcript"]:
            f.write(f"{speaker}: {text}\n")
    print(f"[transcript written] {path}")


@app.get("/health")
async def health():
    return {"status": "ok"}
