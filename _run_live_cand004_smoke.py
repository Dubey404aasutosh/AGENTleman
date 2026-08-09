"""
Script to execute a live cold-start smoke test for CAND-004 (David Miller).
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

    sid = "live-smoke-cand004"
    with TestClient(app) as client:
        # Start
        r_start = client.post("/api/interview", json={"sessionId": sid, "candidate": cand_dict["CAND-004"]})
        res = r_start.json()
        print("=== CAND-004 COLD-START SMOKE TEST ===")
        print("=== TURN 0 (START) ===")
        print(f"Interviewer Reply: {res['reply']}\n")

        answers = [
            "I used sentence-transformers in Python with cosine similarity to evaluate semantic overlap across candidate submissions.",
            "I set up a local ChromaDB instance with HNSW indexing and metadata filtering for fast vector retrieval.",
            "I built an end-to-end RAG pipeline using hybrid BM25 and vector search with reranking.",
            "I wrote structured system prompts with few-shot examples and schema output constraints.",
            "I built an async FastAPI backend with Pydantic v2 validation and SQLite session state.",
            "I used Docker containers and Docker Compose to containerize microservices for deployment.",
            "I set up Prometheus metrics and Grafana dashboards to monitor endpoint latency and errors.",
            "I implemented CrewAI supervisor agents delegating tasks to specialized worker sub-agents.",
            "I created MCP server tools in Python using fastmcp for standardized LLM tool execution.",
            "I completed the final capstone project demonstrating end-to-end integration and evaluation."
        ]

        turn_idx = 1
        for answer in answers:
            if res.get("done"):
                break
            print(f"--- TURN {turn_idx} ---")
            print(f"Candidate Answer: '{answer}'")

            r_turn = client.post("/api/interview", json={"sessionId": sid, "message": answer})
            res = r_turn.json()
            print(f"Interviewer Reply: {res['reply']}\n")

            if res.get("done"):
                print("=== FINAL FEEDBACK ===")
                print(json.dumps(res.get("feedback"), indent=2))
                break
            turn_idx += 1

if __name__ == "__main__":
    main()
