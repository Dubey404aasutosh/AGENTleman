"""
Script to execute a clean, on-topic Golden Path run for CAND-001.
"""

import json
import os
from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
from main import app
import session_store

def main():
    with open("candidates.json") as f:
        candidates_raw = json.load(f)["candidates"]
        cand_dict = {c["member"]["id"]: c for c in candidates_raw}

    sid = "clean-golden-path-cand001"
    with TestClient(app) as client:
        # Start
        r_start = client.post("/api/interview", json={"sessionId": sid, "candidate": cand_dict["CAND-001"]})
        res = r_start.json()
        print("=== TURN 0 (START) ===")
        print(f"Reply: {res['reply']}\n")

        # Map on-topic answers dynamically to topic titles
        on_topic_answers = {
            "Retrieval": "I built a query router in Python that routes structured queries to SQLite and semantic search to ChromaDB, merging results with reciprocal rank fusion.",
            "Observability": "I configured Prometheus metrics, structured JSON logging with structlog, and Grafana dashboards for API endpoint observability.",
            "Prompt Engineering": "I designed prompt templates using zero-shot and few-shot examples with clear output constraints for LLM formatting.",
            "Multi-Agent": "I implemented a multi-agent orchestration pattern using CrewAI where a supervisor agent delegates sub-tasks to specialized domain agents.",
            "Vector": "I set up a local ChromaDB instance with HNSW indexing and cosine similarity for fast vector retrieval.",
            "Backend": "I built an async FastAPI backend with Pydantic v2 schemas and session management stored in SQLite.",
            "Environment": "I use pyenv for Python version management and virtualenv for isolated dependency environments.",
        }

        turn_idx = 1
        while not res.get("done"):
            # Determine topic keyword from current question or fallback
            session = session_store.get(sid)
            curr_topic = session.plan[session.current_topic_index] if session else None
            answer = "I implemented core features using Python, FastAPI, and structured schemas following best practices."
            if curr_topic:
                for kw, ans in on_topic_answers.items():
                    if kw.lower() in curr_topic.title.lower():
                        answer = ans
                        break

            print(f"--- TURN {turn_idx} (Topic: Day {curr_topic.day} — {curr_topic.title}) ---")
            print(f"Candidate Answer: '{answer}'")

            r_turn = client.post("/api/interview", json={"sessionId": sid, "message": answer})
            res = r_turn.json()
            print(f"Interviewer Reply: {res['reply']}\n")

            if session_store.get(sid) and session_store.get(sid).evaluations:
                ev = session_store.get(sid).evaluations[-1]
                print(f"Evaluation: bucket='{ev.bucket}', rationale='{ev.rationale}'\n")

            turn_idx += 1

        print("=== FINAL GOLDEN PATH FEEDBACK ===")
        print(json.dumps(res["feedback"], indent=2))

if __name__ == "__main__":
    main()
