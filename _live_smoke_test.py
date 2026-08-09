"""
Live smoke test runner for AI Interview Agent.
Starts Uvicorn server, executes 3+ turns with a real candidate (CAND-001)
against the real Gemini API, prints raw JSON requests/responses, and shuts down server.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request

def run_smoke_test():
    # 1. Start uvicorn server in subprocess
    env = os.environ.copy()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )
    
    # Wait for server to start
    url = "http://127.0.0.1:8000/api/interview"
    ready = False
    for _ in range(30):
        time.sleep(0.5)
        try:
            # Check server up
            req = urllib.request.Request(url, data=json.dumps({"sessionId": "ping"}).encode("utf-8"), headers={"Content-Type": "application/json"})
            try:
                urllib.request.urlopen(req)
            except urllib.error.HTTPError as e:
                if e.code in (400, 422):
                    ready = True
                    break
        except Exception:
            pass

    if not ready:
        proc.kill()
        out, err = proc.communicate()
        print("Server failed to start:", out.decode(), err.decode())
        sys.exit(1)

    print("=== LIVE SMOKE TEST STARTED ===")
    
    with open("candidates.json") as f:
        cand001 = json.load(f)["candidates"][0]

    session_id = "live-smoke-test-session-001"

    # Turn 0: Start
    req_payload_0 = {
        "sessionId": session_id,
        "candidate": cand001
    }
    print("\n--- TURN 0 (START) REQUEST ---")
    print(json.dumps(req_payload_0, indent=2))

    req = urllib.request.Request(
        url,
        data=json.dumps(req_payload_0).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res_0 = urllib.request.urlopen(req)
    res_json_0 = json.loads(res_0.read().decode("utf-8"))
    print("\n--- TURN 0 (START) RESPONSE ---")
    print(json.dumps(res_json_0, indent=2))

    # Turn 1: Candidate answer 1
    answer_1 = (
        "In Python projects, I use pyenv to manage runtime versions and poetry for dependency isolation and lockfiles. "
        "I also set up ruff for linting, pytest for testing, and pre-commit hooks to enforce code quality before commits."
    )
    req_payload_1 = {
        "sessionId": session_id,
        "message": answer_1
    }
    print("\n--- TURN 1 REQUEST ---")
    print(json.dumps(req_payload_1, indent=2))

    req = urllib.request.Request(
        url,
        data=json.dumps(req_payload_1).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res_1 = urllib.request.urlopen(req)
    res_json_1 = json.loads(res_1.read().decode("utf-8"))
    print("\n--- TURN 1 RESPONSE ---")
    print(json.dumps(res_json_1, indent=2))

    # Turn 2: Candidate answer 2
    answer_2 = (
        "When generating vector embeddings, I use sentence-transformers or OpenAI text-embedding-3-small. "
        "I store the vectors in Qdrant or Pinecone, indexing them with HNSW for fast cosine similarity searches, "
        "and I always normalize vectors beforehand if using dot product."
    )
    req_payload_2 = {
        "sessionId": session_id,
        "message": answer_2
    }
    print("\n--- TURN 2 REQUEST ---")
    print(json.dumps(req_payload_2, indent=2))

    req = urllib.request.Request(
        url,
        data=json.dumps(req_payload_2).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res_2 = urllib.request.urlopen(req)
    res_json_2 = json.loads(res_2.read().decode("utf-8"))
    print("\n--- TURN 2 RESPONSE ---")
    print(json.dumps(res_json_2, indent=2))

    # Turn 3: Candidate answer 3
    answer_3 = (
        "For API integration in FastAPI, I structure routes asynchronously using async def, use Pydantic v2 schemas for "
        "strict request/response validation, handle auth via OAuth2 JWT tokens, and export Prometheus metrics for monitoring."
    )
    req_payload_3 = {
        "sessionId": session_id,
        "message": answer_3
    }
    print("\n--- TURN 3 REQUEST ---")
    print(json.dumps(req_payload_3, indent=2))

    req = urllib.request.Request(
        url,
        data=json.dumps(req_payload_3).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res_3 = urllib.request.urlopen(req)
    res_json_3 = json.loads(res_3.read().decode("utf-8"))
    print("\n--- TURN 3 RESPONSE ---")
    print(json.dumps(res_json_3, indent=2))

    print("\n=== LIVE SMOKE TEST COMPLETED SUCCESSFULLY ===")

    # Stop uvicorn process
    proc.terminate()
    proc.wait()

if __name__ == "__main__":
    run_smoke_test()
