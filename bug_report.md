# Bug Report — Pivot Point Orthopedics Agent (via PGAI test line)

Findings from 17 automated test calls. Each entry describes behavior of the
*clinic's AI agent* on the other end of the line — not our caller bot.
Severity reflects patient-facing impact (a real caller hanging up frustrated,
being misrouted, or getting a wrong answer).

---

### Bug 1: Re-asks for information already provided (DOB, name spelling, phone number)

**Severity:** High
**Calls:** multiple — see transcripts in `transcripts/`
**Details:** After the caller gives their date of birth ("March 12, 1985"), the
agent asks "Could you provide your full date of birth?" and then asks again a
third time, with no acknowledgment that an answer was given. The same pattern
shows up for spelling a last name and for a phone number already stated.
**Why it matters:** This is the single most patient-facing-frustrating bug —
a real caller would assume they weren't heard and likely hang up or ask for a
human. It suggests the agent isn't persisting slot values across turns
reliably, or is re-triggering the same collection step regardless of state.

---

### Bug 2: Agent assumes every caller is "Alex"

**Severity:** Medium
**Calls:** start of nearly every call
**Details:** The agent opens with "Am I speaking with Alex?" regardless of
who is calling, including clearly new/unknown callers.
**Why it matters:** For any caller who isn't Alex, this is confusing and
unprofessional out of the gate. It should default to an open-ended "who am I
speaking with today," only naming a specific patient after an actual
record lookup confirms identity.

---

### Bug 3: Loses context mid-call ("are you calling for yourself?" asked twice, etc.)

**Severity:** High
**Calls:** multiple
**Details:** Questions already answered earlier in the same call (e.g.
whether the caller is booking for themselves) get asked again later in the
same conversation, not just within a single slot like Bug 1.
**Why it matters:** Same root experience as Bug 1 but broader — it implies
conversation state isn't reliably carried across the whole call, not just
within one collection step.

---

### Bug 4: Booking flow loops instead of progressing

**Severity:** High
**Calls:** several scheduling scenarios
**Details:** Instead of moving name → DOB → lookup → scheduling →
confirmation, the agent cycles: spell name → confirm name → DOB → DOB again →
spell last name → spell last name again → phone → phone again, without ever
reaching booking.
**Why it matters:** Calls that should take 1–2 minutes never reach the
actual task. This is likely the same underlying state bug as #1/#3 plus a
state-machine that doesn't have a clear "step completed, advance" condition.

---

### Bug 5: "Transfer to a representative" doesn't actually transfer — call just disconnects

**Severity:** High
**Calls:** several
**Details:** Agent says "I'll connect you to a representative," then
immediately plays "Hello, you've reached the Pretty Good AI test line.
Goodbye" and the call ends.
**Why it matters:** A real caller expecting a human handoff is silently
dropped instead. Either the transfer target/SIP redirect is misconfigured,
or the "transfer" line is a dead-end script with no real destination behind
it. This should either complete a real transfer or be replaced with an
honest "I'm not able to transfer you right now, but here's what I can do
instead" message.

---

### Bug 6: Inconsistent / non-deterministic booking outcomes for similar inputs

**Severity:** Medium
**Calls:** several
**Details:** Some scheduling calls reach a successful booking; structurally
similar calls instead hit "you already have an appointment," "birthday
doesn't match," or "cannot continue, connecting to a representative" with no
apparent difference in caller input.
**Why it matters:** Unpredictable failure modes on near-identical inputs
suggest either a flaky lookup/validation step or non-deterministic LLM
behavior driving a step that should be deterministic (e.g. a DB lookup).

---

### Bug 7: Multi-intent calls (hours question → then booking) get stuck

**Severity:** Medium
**Calls:** `multi_intent` scenario calls
**Details:** Agent answers the hours question fine, but loses the thread
when the caller pivots to booking afterward, and the booking sub-flow
stalls.
**Why it matters:** Real callers very often ask two things in one call;
failing to switch intents while retaining context (e.g. already-stated name)
forces them to repeat everything.

---

### Bug 8: Barge-in occasionally drops info spoken just before the interruption

**Severity:** Low–Medium
**Calls:** `barge_in` scenario calls
**Details:** When the caller talks over the agent, information stated in
that overlapping speech is sometimes lost rather than captured.
**Why it matters:** Less severe than the other state bugs since it only
affects the interrupted utterance, but it compounds Bug 1/3 — caller has to
repeat themselves again.

---

### Bug 9: Greeting plays as 2–3 disjointed messages instead of one

**Severity:** Low
**Calls:** several
**Details:** "This call may be recorded..." / "Thanks for calling..." /
"Part of Pretty Good AI..." play as separate, oddly-paced messages rather
than one smooth greeting.
**Why it matters:** Minor polish issue but it's the very first impression of
the call and reads as broken/robotic before the conversation even starts.

---

### Bug 10: Spanish-language prompt appears inconsistently

**Severity:** Low
**Calls:** a subset of calls
**Details:** Some calls open with a "Para Español, oprima..." prompt; most
don't, with no obvious trigger differentiating the two.
**Why it matters:** Inconsistent language-routing behavior — should be
either always-on or driven by a deliberate signal (e.g. caller area code),
not seemingly random.

---

*(Two issues from earlier internal testing notes —
`response_cancel_not_active` errors and recording-download 404s — were
issues in our own caller bot's code, not the clinic agent, and have since
been fixed in `server.py` / `make_call.py`. They're omitted here since this
report is specifically about the clinic agent's behavior.)*
