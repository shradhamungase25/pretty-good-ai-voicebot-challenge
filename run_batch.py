"""
run_batch.py — the "single command after setup" entry point.

Places one call per scenario in scenarios.py (12 by default, satisfying the
10-call minimum with room for a couple to not go perfectly), waits for each
to fully complete before starting the next (per submission rules: only one
number is used, calls are sequential not concurrent), and leaves transcripts/
and recordings/ populated.

Run server.py + ngrok separately first (see README), then:

    python run_batch.py

Optionally limit to specific scenarios:

    python run_batch.py schedule_simple refill_simple barge_in
"""

import sys
import time

from make_call import place_call
from scenarios import SCENARIOS

GAP_BETWEEN_CALLS_SECONDS = 10


def main():
    requested_ids = sys.argv[1:] or [s["id"] for s in SCENARIOS]
    by_id = {s["id"]: s for s in SCENARIOS}

    results = []
    for i, scenario_id in enumerate(requested_ids, start=1):
        if scenario_id not in by_id:
            print(f"Skipping unknown scenario '{scenario_id}'")
            continue
        call_label = f"call-{i:02d}-{scenario_id}"
        print(f"\n=== [{i}/{len(requested_ids)}] {call_label} ===")
        try:
            call = place_call(scenario_id, call_label)
            results.append((call_label, call.status))
        except Exception as e:
            print(f"ERROR on {call_label}: {e}")
            results.append((call_label, f"error: {e}"))

        if i < len(requested_ids):
            time.sleep(GAP_BETWEEN_CALLS_SECONDS)

    print("\n=== Batch summary ===")
    for label, status in results:
        print(f"{label}: {status}")


if __name__ == "__main__":
    main()
