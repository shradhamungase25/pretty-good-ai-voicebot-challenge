# PGAI Voice Bot - AI Engineering Challenge

An automated voice bot that calls Pretty Good AI's test line
(`+1-805-439-8008`) as a simulated patient, has a real spoken conversation
with their agent, and saves a recording + speaker-labeled transcript of each
call. See `ARCHITECTURE.md` for how it works and why.

## Prerequisites

- Python 3.10+
- A Twilio account with a phone number that can make outbound calls
  ([console.twilio.com](https://console.twilio.com))
- An OpenAI API key with access to the Realtime API
  ([platform.openai.com](https://platform.openai.com))
- [ngrok](https://ngrok.com) (or any way to expose a local port over HTTPS) —
  Twilio needs a public URL to fetch TwiML from and stream audio to

## Setup

1. Clone this repo and install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and fill in your real values:

   ```bash
   cp .env.example .env
   ```

   - `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` — from the Twilio console
   - `TWILIO_CALLER_NUMBER` — the single Twilio number you'll use for every
     test call (this is the number you report in the submission form)
   - `OPENAI_API_KEY` — needs Realtime API access
   - `TARGET_NUMBER` — leave as `+18054398008` (the assessment's test line)
   - `PUBLIC_SERVER_URL` — filled in during step 4, below

3. In one terminal, start the media-bridge server:

   ```bash
   uvicorn server:app --host 0.0.0.0 --port 8000
   ```

4. In a second terminal, expose it publicly and copy the HTTPS URL ngrok
   gives you into `PUBLIC_SERVER_URL` in `.env`:

   ```bash
   ngrok http 8000
   ```

## Run

Once steps 1–4 above are done, run all scenarios with a single command:

```bash
python run_batch.py
```

This places one outbound call per scenario defined in `scenarios.py`
(12 by default — comfortably over the 10-call minimum), waits for each to
fully finish before starting the next, and writes:

- `transcripts/call-XX-<scenario>.txt` — speaker-labeled transcript
- `recordings/call-XX-<scenario>.mp3` — full call audio

To run a subset (e.g. while iterating):

```bash
python run_batch.py schedule_simple refill_simple barge_in
```

To place a single one-off call:

```bash
python make_call.py schedule_simple my-test-call
```

## Project layout

```
server.py        # FastAPI app: Twilio Media Stream <-> OpenAI Realtime bridge
make_call.py     # Places one outbound call via Twilio REST API, downloads the recording
run_batch.py     # Runs all (or selected) scenarios sequentially — the "one command"
scenarios.py     # Patient personas/goals for each test call
transcripts/     # Output: per-call transcripts
recordings/      # Output: per-call mp3 recordings
bug_report.md    # Findings from reviewing the calls
ARCHITECTURE.md  # Design write-up
```

## Notes

- Calls are placed strictly one at a time from a single caller number, per
  the assessment rules.
- Turn-taking and barge-in are handled by OpenAI's server-side voice
  activity detection (see `ARCHITECTURE.md`), not a scripted timer.
- If a call fails to connect cleanly (e.g. `no-answer`, `failed`), just
  re-run that one scenario with `make_call.py`.
