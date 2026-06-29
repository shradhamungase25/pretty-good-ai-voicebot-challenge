# QA Bug Report: AI Voice Receptionist (Pivot Point Orthopedics, via Pretty Good AI)

**Prepared by:** QA Testing (automated caller simulation)
**Subject:** End-to-end voice interaction testing of the AI receptionist agent
**Test type:** Black-box conversational testing via live outbound phone calls

---

## Executive Summary

Ten outbound test calls were placed to the AI receptionist across a range of
realistic patient scenarios — scheduling, rescheduling, cancellation,
medication refills, informational questions, and several deliberately
ambiguous or adversarial edge cases. The agent successfully completed
several non-trivial workflows, including a multi-turn rescheduling
conversation, and generally produced natural-sounding, understandable
speech.

However, testing surfaced a recurring **state-management problem**: the
agent frequently re-requests information the caller already provided
(names, phone numbers), and in at least one case confirmed a phone number
the caller never said at all. A "transfer to a representative" flow was
also found to be non-functional — it announces a transfer and then plays a
generic goodbye message instead of connecting anyone. These two issues
(unreliable slot retention and a broken transfer path) are the most
significant findings and are the ones most likely to frustrate or actively
mislead a real patient.

No issues found rose to the level of "the system is unusable" — most calls
did eventually reach a resolution — but the verification-loop and
hallucinated-number issues in particular should be addressed before this
agent is used with real patients, since both touch directly on getting a
caller's contact/identity information correct.

---

## Test Environment

- **Caller (test harness):** custom Python voice bot — Twilio (telephony) +
  OpenAI Realtime API (`gpt-realtime`, GA) acting as a simulated patient
  with a distinct persona/goal per call.
- **Target system:** Pretty Good AI's hosted voice agent for "Pivot Point
  Orthopedics," reached via the assessment's test line.
- **Call handling:** all calls placed sequentially from a single caller
  number; each call recorded (mp3) and transcribed with speaker labels
  (`AGENT` / `PATIENT`) via the Realtime API's own transcription events.
- **Sample size:** 10 calls, 1 per scenario below, each a full multi-turn
  conversation rather than a single question and hangup.

---

## Test Coverage

| # | Scenario |
|---|---|
| 1 | Appointment Scheduling |
| 2 | Appointment Rescheduling |
| 3 | Appointment Cancellation |
| 4 | Medication Refill |
| 5 | Insurance Questions |
| 6 | Hours and Location |
| 7 | Unclear Request |
| 8 | Multiple Intents |
| 9 | Barge-in / Interruptions |
| 10 | Unusual / Out-of-Scope Requests |

---

## Positive Findings

To keep this report balanced, the following held up well across testing and
should be preserved through any fixes below:

- Natural conversational tone and generally smooth, understandable voice
  quality.
- Solid handling of healthcare-specific workflows when state tracking
  didn't get in the way.
- Successfully completed a non-trivial, multi-turn rescheduling scenario
  end-to-end.
- Handled spoken interruptions reasonably gracefully — it noticed
  barge-in and yielded the floor rather than talking over the caller.
- Maintained context correctly across multiple turns in several calls (not
  universally — see Bug 1 — but it did work in a number of cases).
- Escalated to a transfer offer when genuinely unable to complete a
  request, rather than guessing (the transfer mechanism itself is broken —
  see Bug 5 — but the *decision* to offer one was often reasonable).

---

## Major Findings

### Bug 1: Verification loops — repeats requests for already-provided information

- **Severity:** High
- **Frequency:** Often
- **Description:** The agent asks the caller to spell their name or repeat
  their phone number multiple times, even immediately after the caller
  answered correctly.
- **Expected Behavior:** Once a piece of identifying information is
  captured for a call, it should be retained for the remainder of that call
  and only re-requested if speech recognition confidence was low or the
  caller corrected themselves.
- **Actual Behavior:** The same prompt (e.g., "Can you spell your last name
  for me?") recurs two or three times in a single call despite a clear,
  correct answer being given each time.
- **Evidence:** Observed in Scheduling, Rescheduling, Medication Refill,
  Unclear Request, and Multiple Intents calls — see corresponding
  transcripts in `transcripts/`.
- **Suggested Improvement:** Audit how collected slot values are persisted
  across conversation turns. This pattern across many distinct flows
  suggests a shared state-tracking component rather than a per-flow scripting
  issue, which would be the more efficient place to fix it.

---

### Bug 2: Hallucinated phone numbers

- **Severity:** Critical
- **Frequency:** Sometimes
- **Description:** The agent confirms a phone number back to the caller
  that the caller never stated.
- **Expected Behavior:** The agent should only read back a phone number
  that was actually captured from the caller's speech in that call, and
  should ask for clarification rather than substitute a different number.
- **Actual Behavior:** On at least one call, the agent repeatedly confirmed
  the number 657-363-4165, which the caller had not provided.
- **Evidence:** Observed in at least one Scheduling-adjacent call — flagged
  here for follow-up rather than tied to a single transcript line, since it
  warrants a closer look at where that number is being read from.
- **Suggested Improvement:** This is treated as the most serious finding in
  this report, not because it broke a call outright, but because a wrong
  callback or refill-confirmation number is a real-world patient-contact
  risk, not just a conversational inconvenience. Worth checking whether a
  placeholder/test value is leaking into production responses, or whether
  the model is being allowed to fill in a number it isn't confident about
  rather than asking again.

---

### Bug 3: Premature escalation

- **Severity:** Medium
- **Frequency:** Sometimes
- **Description:** The agent transfers (or offers to transfer) the caller
  to a human representative for requests it appears capable of completing
  on its own, based on how other similar calls played out.
- **Expected Behavior:** Escalation should be reserved for requests genuinely
  outside the agent's scope or after a workflow has clearly failed, not as
  an early fallback for a request type it has handled successfully
  elsewhere.
- **Actual Behavior:** A request that other test calls completed
  successfully was, on a different call, escalated instead of attempted.
- **Evidence:** Observed in a subset of calls — most visible by comparing
  outcomes across calls with similar intents (e.g. two scheduling-type
  calls reaching different outcomes).
- **Suggested Improvement:** Worth checking whether escalation is being
  triggered by something brittle (a confidence threshold, a specific
  phrase, or an inconsistent lookup result) rather than a genuine
  capability gap. This overlaps with Bug 6 (inconsistent outcomes), and
  fixing the underlying state/lookup reliability may resolve both.

---

### Bug 4: `response_cancel_not_active` errors in call logs

- **Severity:** Low
- **Frequency:** Often
- **Description:** Internal Realtime-API error events appear repeatedly in
  call logs, indicating a cancel request was sent for a response that
  wasn't active.
- **Expected Behavior:** No error events during normal conversation flow;
  cancellation should only be requested when a response is genuinely in
  progress.
- **Actual Behavior:** The error appears frequently across many calls. In
  this round of testing it did **not** appear to disrupt the audible
  conversation or cause dropped turns — it shows up as log noise rather
  than a caller-facing symptom.
- **Evidence:** Present across most transcripts/logs in `transcripts/`.
- **Suggested Improvement:** Listed under Major Findings because of how
  frequently it appears, but it should be understood as an **internal
  implementation issue, not a conversational bug** — nothing in the audio
  itself indicated a problem to the caller. Worth fixing for log hygiene
  and to rule out any subtle audio-cutoff edge cases it might be masking,
  but it should not be weighted the same as the caller-facing issues above.

---

### Bug 5: "Fake transfer" — announced handoff does not connect anyone

- **Severity:** Critical
- **Frequency:** Sometimes
- **Description:** The agent tells the caller it is transferring them to a
  representative, then immediately plays a generic goodbye message and ends
  the call instead of connecting to anyone.
- **Expected Behavior:** A stated transfer should either complete a real
  handoff to a human/queue, or the agent should not claim to be
  transferring in the first place.
- **Actual Behavior:** Caller hears: *"I'll connect you to a
  representative,"* immediately followed by *"Hello, you've reached the
  Pretty Good AI test line. Goodbye."* The call then disconnects.
- **Evidence:** Observed in multiple calls where escalation was triggered
  (see also Bug 3) — see transcripts where a transfer is announced.
- **Suggested Improvement:** This is rated Critical because it actively
  misleads the caller about what's happening to their request — a patient
  who believes they're about to reach a person, and is instead hung up on,
  is a materially worse outcome than the agent simply saying it can't
  help. At minimum, the agent should not claim a transfer is occurring
  unless one is technically wired up; if a real transfer destination
  isn't available in this test environment, the agent's language should be
  changed to something honest, e.g. "I'm not able to transfer you to a
  representative right now."

---

## Minor Findings

### Bug 6: Greets the wrong patient

- **Severity:** Medium
- **Frequency:** Sometimes
- **Description:** The agent occasionally opens the call addressing the
  caller by a different patient's identity rather than asking who is
  calling.
- **Expected Behavior:** The agent should not assume a specific patient
  identity until it has actually confirmed who is calling.
- **Actual Behavior:** Caller is greeted as if they were a different,
  specific named patient.
- **Evidence:** Observed in a subset of calls at the greeting stage.
- **Suggested Improvement:** Default to an open, identity-neutral greeting
  and only reference a specific patient name after a successful lookup
  confirms it.

### Bug 7: Unexpected mixing of Spanish and English

- **Severity:** Low
- **Frequency:** Sometimes
- **Description:** A small number of calls included Spanish-language
  phrases mixed into an otherwise English conversation, with no clear
  trigger.
- **Expected Behavior / note on design limitation:** It's reasonable for a
  system to support a Spanish-language path (e.g. via a deliberate
  language-selection prompt). What's flagged here is specifically the
  *inconsistent, seemingly unprompted* mixing within a single call — if
  bilingual support is an intentional design choice, this finding is about
  its triggering logic, not the feature itself.
- **Actual Behavior:** Spanish phrases appeared mid-call without the
  caller requesting a language change.
- **Evidence:** Observed in a small number of calls.
- **Suggested Improvement:** Confirm whether language switching is meant
  to be caller-triggered, and if so, tighten the condition that's
  currently causing it to fire unprompted.

### Bug 8: Says goodbye before the interaction is actually finished

- **Severity:** Medium
- **Frequency:** Sometimes
- **Description:** The agent ends the call with a closing line while the
  caller still had an unresolved question or unfinished step.
- **Expected Behavior:** A closing/goodbye should only be used once the
  caller's request has been completed or explicitly declined, or after
  confirming the caller has nothing further.
- **Actual Behavior:** Call-ending language appears mid-task in some calls.
- **Evidence:** Observed in a subset of calls.
- **Suggested Improvement:** Gate closing statements behind an explicit
  "is there anything else I can help with?" confirmation step.

### Bug 9: Unnecessary prompt repetition (outside the verification-loop pattern)

- **Severity:** Low
- **Frequency:** Sometimes
- **Description:** Separate from Bug 1's identity-data loops, the agent
  sometimes re-reads the same general prompt or menu-style line without an
  obvious reason.
- **Expected Behavior:** Each prompt should generally be spoken once unless
  the caller didn't respond or asked for repetition.
- **Actual Behavior:** Identical or near-identical prompt lines recur
  within the same call.
- **Evidence:** Observed in a subset of calls.
- **Suggested Improvement:** Likely the same root cause as Bug 1 (turn
  state not being marked "complete"); worth confirming whether fixing one
  resolves the other.

---

## Recommendations

1. **Prioritize slot/state persistence** (Bug 1, and likely Bugs 3, 6, 9) —
   this is the most frequently recurring pattern across distinct call types
   and is the highest-leverage fix.
2. **Investigate the source of the hallucinated phone number** (Bug 2)
   before any real-patient use — this is a data-correctness issue, not
   just a conversational rough edge.
3. **Fix or honestly relabel the transfer flow** (Bug 5) — either wire up a
   real handoff destination or stop announcing one that doesn't exist.
4. **Treat the `response_cancel_not_active` errors as a code-quality cleanup
   item** (Bug 4) rather than a user-facing defect, but still worth fixing
   to rule out subtler downstream effects.
5. **Re-test Bugs 3 and 6 after the state-management fix**, since both may
   turn out to be symptoms of the same root cause rather than independent
   issues.

---

## Overall Assessment

The agent demonstrates a genuinely capable conversational core — natural
pacing, good audio quality, sensible handling of interruptions, and at
least one fully successful complex workflow. The issues found are real and
worth fixing before production use, but they cluster around a fairly narrow
set of root causes (state/slot retention, and the transfer integration)
rather than indicating a broadly unreliable system. Addressing the
state-management pattern behind Bugs 1, 3, 6, and 9, fixing or relabeling
the transfer flow (Bug 5), and tracking down the source of the hallucinated
phone number (Bug 2) would resolve the large majority of patient-facing
impact identified in this round of testing.
