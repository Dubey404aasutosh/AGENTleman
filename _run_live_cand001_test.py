"""
Script to execute Golden Path CAND-001 live run to verify Day 29 title correctness.
"""

import json
from dotenv import load_dotenv
load_dotenv()

from fastapi.testclient import TestClient
from main import app

def main():
    with open("candidates.json") as f:
        candidates_raw = json.load(f)["candidates"]
        cand_dict = {c["member"]["id"]: c for c in candidates_raw}

    sid = "live-cand001-title-check"
    with TestClient(app) as client:
        res_start = client.post("/api/interview", json={"sessionId": sid, "candidate": cand_dict["CAND-001"]}).json()

        answers = [
            "I use pyenv and poetry for Python environment management.",
            "I choose sentence-transformers for vector embeddings and store them in Qdrant.",
            "I use HNSW index with cosine distance and payload filtering in Qdrant.",
            "I combine BM25 sparse vectors with dense embeddings using reciprocal rank fusion.",
            "I use Pydantic v2 schemas and async FastAPI routes for high performance.",
            "I set up Prometheus metrics, structured JSON logging with structlog, and Jaeger tracing.",
            "I configure Docker multi-stage builds and deploy to Kubernetes using Helm charts.",
            "I built a capstone multi-agent RAG system with human-in-the-loop review."
        ]
        res_turn = res_start
        for ans in answers:
            if res_turn.get("done"):
                break
            res_turn = client.post("/api/interview", json={"sessionId": sid, "message": ans}).json()

        print("\n=== FINAL CAND-001 RESPONSE (done=True) ===")
        print(json.dumps(res_turn, indent=2))

if __name__ == "__main__":
    main()
