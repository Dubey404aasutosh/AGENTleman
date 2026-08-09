"""
Script to execute Problem 2: Live Resilience test with 5x 'I don't know' against real Gemini API (gemini-3.6-flash).
"""

import json
import os
from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
from main import app
import session_store

def main():
    print(f"USING PRIMARY MODEL FROM ENV: {os.environ.get('GEMINI_PRIMARY_MODEL')}")
    print(f"USING FALLBACK MODEL FROM ENV: {os.environ.get('GEMINI_FALLBACK_MODEL')}")

    with open("candidates.json") as f:
        candidates_raw = json.load(f)["candidates"]
        cand_dict = {c["member"]["id"]: c for c in candidates_raw}

    sid = "live-resilience-cand002"
    with TestClient(app) as client:
        # Start
        r_start = client.post("/api/interview", json={"sessionId": sid, "candidate": cand_dict["CAND-002"]})
        print("\n=== START RESPONSE (TURN 0) ===")
        print(json.dumps(r_start.json(), indent=2))

        for turn_idx in range(1, 9):
            session_before = session_store.get(sid)
            print(f"\n--- Sending Turn {turn_idx}: 'I don't know' ---")
            r_turn = client.post("/api/interview", json={"sessionId": sid, "message": "I don't know"})
            res = r_turn.json()
            print(f"Response Turn {turn_idx}:")
            print(json.dumps(res, indent=2))

            session_after = session_store.get(sid)
            if session_after and session_after.evaluations:
                latest_eval = session_after.evaluations[-1]
                print(f"-> Turn {turn_idx} Evaluation: bucket='{latest_eval.bucket}', rationale='{latest_eval.rationale}'")
                print(f"-> session.using_fallback: {session_after.using_fallback}")

            if res.get("done"):
                print("\n=== INTERVIEW COMPLETED (done=True) ===")
                print(f"Total questions asked: {session_after.questions_asked}")
                print(f"Covered days: {session_after.covered_days}")
                print(f"Covered modules count: {len({t.module_n for t in session_after.plan if t.day in session_after.covered_days})}")
                break

if __name__ == "__main__":
    main()
