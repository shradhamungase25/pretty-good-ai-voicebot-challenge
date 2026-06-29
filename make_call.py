"""
make_call.py — place ONE outbound call to the test line for a given scenario,
wait for it to finish, then download the call recording.

Usage:
    python make_call.py schedule_simple call-01

This requires server.py to already be running and reachable at
PUBLIC_SERVER_URL (e.g. an ngrok https URL) — Twilio needs to fetch TwiML
from it and stream audio to it for the duration of the call.
"""

import os
import sys
import time

import requests
from dotenv import load_dotenv
from twilio.rest import Client

from scenarios import SCENARIOS

load_dotenv()

ACCOUNT_SID = os.environ["TWILIO_ACCOUNT_SID"]
AUTH_TOKEN = os.environ["TWILIO_AUTH_TOKEN"]
CALLER_NUMBER = os.environ["TWILIO_CALLER_NUMBER"]   # the single number you'll report in the submission form
TARGET_NUMBER = os.environ.get("TARGET_NUMBER", "+18054398008")
PUBLIC_SERVER_URL = os.environ["PUBLIC_SERVER_URL"].rstrip("/")  # e.g. https://abc123.ngrok.app
RECORDINGS_DIR = os.path.join(os.path.dirname(__file__), "recordings")

client = Client(ACCOUNT_SID, AUTH_TOKEN)


def place_call(scenario_id: str, call_label: str, poll_interval: int = 5, timeout: int = 240):
    if scenario_id not in {s["id"] for s in SCENARIOS}:
        valid = ", ".join(s["id"] for s in SCENARIOS)
        raise SystemExit(f"Unknown scenario '{scenario_id}'. Valid options: {valid}")

    twiml_url = f"{PUBLIC_SERVER_URL}/outbound/twiml?scenario={scenario_id}&call_label={call_label}"
    print(f"Calling {TARGET_NUMBER} from {CALLER_NUMBER} | scenario={scenario_id} label={call_label}")

    call = client.calls.create(
        to=TARGET_NUMBER,
        from_=CALLER_NUMBER,
        url=twiml_url,
        record=True,
        recording_channels="dual",
        machine_detection="Disable",
    )

    print(f"Call SID: {call.sid} — waiting for it to complete...")
    elapsed = 0
    while elapsed < timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval
        call = client.calls(call.sid).fetch()
        print(f"  status={call.status} ({elapsed}s elapsed)")
        if call.status in ("completed", "busy", "failed", "no-answer", "canceled"):
            break

    if call.status != "completed":
        print(f"WARNING: call ended with status '{call.status}', not 'completed'.")

    _download_recording(call.sid, call_label)
    return call


def _download_recording(
    call_sid: str,
    call_label: str,
    metadata_max_wait: int = 60,
    metadata_poll_interval: int = 5,
    media_retries: int = 5,
    media_retry_delay: int = 4,
):
    """
    Recording retrieval happens in two independent stages, because Twilio
    creates the Recording *resource* (metadata) when the call ends, but the
    actual *media file* (mp3/wav) can take a bit longer to finish processing.
    Racing straight to the .mp3 URL right after call.status == "completed"
    is what was producing the 404 — this has nothing to do with the OpenAI
    side of the bridge, which has already finished and written its
    transcript by this point.
    """
    os.makedirs(RECORDINGS_DIR, exist_ok=True)

    recording = _wait_for_recording_metadata(call_sid, call_label, metadata_max_wait, metadata_poll_interval)
    if recording is None:
        print(
            f"[{call_label}] No Recording resource appeared for call {call_sid} within "
            f"{metadata_max_wait}s. This means recording was never created — double-check "
            f"that record=True is actually being sent (it is, in this code) and that your "
            f"Twilio account/region doesn't have call recording disabled or restricted. "
            f"The voice conversation itself is unaffected by this; check "
            f"transcripts/{call_label}.txt to confirm the call went fine."
        )
        return None

    print(f"[{call_label}] Recording resource found: sid={recording.sid} status={recording.status}")

    result = _fetch_recording_media(recording, call_label, retries=media_retries, retry_delay=media_retry_delay)
    if result is None:
        print(
            f"[{call_label}] Recording resource exists (status={recording.status}) but no "
            f"media file (mp3/wav) could be downloaded after {media_retries} attempts per "
            f"format. It may still be processing — try re-running just the download later, "
            f"e.g.: python -c \"from make_call import _download_recording; "
            f"_download_recording('{call_sid}', '{call_label}')\""
        )
        return None

    ext, content = result
    out_path = os.path.join(RECORDINGS_DIR, f"{call_label}.{ext}")
    with open(out_path, "wb") as f:
        f.write(content)
    print(f"[{call_label}] Recording saved to {out_path} ({len(content)} bytes, format={ext})")
    return out_path


def _wait_for_recording_metadata(call_sid: str, call_label: str, max_wait: int, poll_interval: int):
    """Poll the Recordings list for this call until one shows up and is marked
    'completed', rather than trusting whatever's first in the list immediately
    after the call ends (it may still say 'processing' or 'in-progress')."""
    elapsed = 0
    last_seen = None
    while elapsed <= max_wait:
        recordings = client.calls(call_sid).recordings.list()
        if recordings:
            last_seen = recordings[0]
            completed = [r for r in recordings if r.status == "completed"]
            if completed:
                return completed[0]
            print(f"[{call_label}] recording {last_seen.sid} status='{last_seen.status}', waiting...")
        else:
            print(f"[{call_label}] no Recording resource yet ({elapsed}s elapsed)...")
        time.sleep(poll_interval)
        elapsed += poll_interval
    # Timed out waiting for "completed" — return whatever we last saw (if
    # anything) so the media-fetch retry loop gets a chance anyway.
    return last_seen


def _fetch_recording_media(recording, call_label: str, formats=("mp3", "wav"), retries: int = 5, retry_delay: int = 4):
    """Try each accepted format, retrying on 404 (still transcoding) before
    giving up. Returns (extension, content_bytes) or None."""
    base_uri = recording.uri.rsplit(".", 1)[0]  # strip the trailing ".json"
    for fmt in formats:
        media_url = f"https://api.twilio.com{base_uri}.{fmt}"
        for attempt in range(1, retries + 1):
            resp = requests.get(media_url, auth=(ACCOUNT_SID, AUTH_TOKEN))
            if resp.status_code == 200:
                return fmt, resp.content
            if resp.status_code == 404:
                print(f"[{call_label}] {fmt} not ready yet (404), attempt {attempt}/{retries}")
                time.sleep(retry_delay)
                continue
            # Any other error (403, 5xx, etc.) — log and move to next format
            # rather than retrying something that won't fix itself.
            print(f"[{call_label}] unexpected status {resp.status_code} fetching {fmt}: {resp.text[:200]}")
            break
    return None


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python make_call.py <scenario_id> <call_label>")
        print("Scenarios:", ", ".join(s["id"] for s in SCENARIOS))
        sys.exit(1)
    place_call(sys.argv[1], sys.argv[2])
