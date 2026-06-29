# Architecture

This bot uses Twilio for telephony and OpenAI's Realtime API as the single
"brain" for the simulated patient — instead of chaining separate
speech-to-text, LLM, and text-to-speech services. Twilio places an outbound
call to the test line and connects a bidirectional Media Stream (raw G.711
u-law audio over a WebSocket) to a small FastAPI server (`server.py`). That
server opens a second WebSocket to OpenAI's Realtime API and pipes audio
directly between the two — Twilio's inbound audio (the clinic agent's voice)
goes straight into OpenAI's input buffer, and OpenAI's generated speech (the
patient's voice) goes straight back out to Twilio, with no intermediate
transcoding since both sides use the same 8kHz u-law codec. Turn-taking is
handled by OpenAI's server-side voice activity detection rather than a fixed
silence timer, and on `speech_started` events we clear Twilio's outbound
audio buffer and cancel any in-flight OpenAI response so the two sides don't
talk over each other indefinitely — this also produces realistic barge-in
behavior for the scenario designed to test it. A real-time, single-model
speech-to-speech approach was chosen specifically because the grading
criteria treat conversational lucidity (natural pacing, sensible turn-taking)
as the #1 priority — a chained ASR→LLM→TTS pipeline adds latency and
seams at every handoff that make a bot sound robotic, which is the opposite
of what's being tested here.

The "patient" identity, goal, and personality for each call come from
`scenarios.py`, which defines ~12 distinct scenarios (scheduling,
rescheduling, canceling, refills — including an edge case around a
controlled substance, hours/insurance questions, a deliberately vague
opener, an intentional barge-in, and a multi-intent call) and turns each into
a system prompt rather than a literal script, so the model improvises
naturally in response to whatever the clinic's agent actually says. Calls
are placed and orchestrated by `make_call.py` / `run_batch.py` via the
Twilio REST API, one at a time from a single caller number as required.
Twilio records the raw call audio server-side (downloaded afterward as the
mp3 deliverable), while the transcript is built independently inside
`server.py` from OpenAI's own input transcription (Whisper, for the agent's
side) and its output transcript events (for the patient's side) — giving a
labeled, speaker-attributed transcript without a separate transcription
pass.
