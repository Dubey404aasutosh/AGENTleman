"""
Live verification for CAND-016 and CAND-011.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from models import CandidateProfile
from planner import build_plan

def main():
    with open("candidates.json") as f:
        candidates_raw = json.load(f)["candidates"]
        cand_dict = {c["member"]["id"]: c for c in candidates_raw}
        curriculum = json.load(open("curriculum.json"))

    # Print Plan Dumps first
    c16 = CandidateProfile.model_validate(cand_dict["CAND-016"])
    plan16, tone16 = build_plan(c16, curriculum)
    print("=== CAND-016 PLAN DUMP ===")
    print(f"Tone: {tone16}")
    print(f"Total topics: {len(plan16)}")
    diagnostic_count = sum(1 for t in plan16 if t.depth.value == "diagnostic")
    print(f"Diagnostic topics count (capped at 2): {diagnostic_count}")
    for t in plan16:
        print(f"  Day {t.day}: {t.title} (depth={t.depth.value})")

    c11 = CandidateProfile.model_validate(cand_dict["CAND-011"])
    plan11, tone11 = build_plan(c11, curriculum)
    print("\n=== CAND-011 PLAN DUMP ===")
    print(f"Tone: {tone11}")
    print(f"Total topics: {len(plan11)}")
    for t in plan11:
        print(f"  Day {t.day}: {t.title} (depth={t.depth.value})")

    # Now run live Uvicorn start call for both candidates
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    url = "http://127.0.0.1:8000/api/interview"
    time.sleep(2)

    try:
        # Start CAND-016
        print("\n=== LIVE START CALL FOR CAND-016 ===")
        req16 = urllib.request.Request(
            url,
            data=json.dumps({"sessionId": "live-cand-016", "candidate": cand_dict["CAND-016"]}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        res16 = json.loads(urllib.request.urlopen(req16).read().decode("utf-8"))
        print(json.dumps(res16, indent=2))

        # Start CAND-011
        print("\n=== LIVE START CALL FOR CAND-011 ===")
        req11 = urllib.request.Request(
            url,
            data=json.dumps({"sessionId": "live-cand-011", "candidate": cand_dict["CAND-011"]}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        res11 = json.loads(urllib.request.urlopen(req11).read().decode("utf-8"))
        print(json.dumps(res11, indent=2))
    finally:
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    main()
