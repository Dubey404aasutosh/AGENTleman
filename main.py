"""
Main FastAPI application module (Component 5.7, Phase 5).
Exposes POST /api/interview route and manages lifespan state loading.
"""

import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from models import InterviewRequest, InterviewResponse, SessionState
import planner
import turn_engine
import session_store
import llm_client

curriculum_data: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global curriculum_data
    with open("curriculum.json") as f:
        curriculum_data = json.load(f)
    llm_client.init_client(api_key=os.environ["GEMINI_API_KEY"])
    yield


app = FastAPI(title="AI Interview Agent", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.exception_handler(HTTPException)
async def http_exc_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail if isinstance(exc.detail, dict) else {"error": "ERROR", "detail": str(exc.detail)},
    )

@app.exception_handler(ValueError)
async def value_error_handler(request, exc):
    return JSONResponse(status_code=500, content={"error": "INTERNAL_ERROR", "detail": str(exc)})


@app.post("/api/interview", response_model=InterviewResponse, response_model_exclude_none=True)
async def interview(request: InterviewRequest):
    # CASE 1 — START (candidate present)
    if request.candidate is not None:
        plan, tone = planner.build_plan(request.candidate, curriculum_data)
        session = SessionState(
            session_id=request.sessionId, candidate=request.candidate,
            plan=plan, candidate_tone=tone,
        )
        session_store.set(request.sessionId, session)      # overwrite = idempotent reset (Decision #14 sibling)
        reply = turn_engine.generate_first_question(session)
        return InterviewResponse(reply=reply, done=False)

    # CASE 2 — TURN (message present)
    if request.message is not None:
        session = session_store.get(request.sessionId)
        if session is None:
            raise HTTPException(status_code=400, detail={
                "error": "INVALID_SESSION",
                "detail": "Session not found. Send candidate data to start a new interview.",
            })
        if session.is_done:
            raise HTTPException(status_code=400, detail={
                "error": "SESSION_COMPLETE",
                "detail": "Interview already completed for this session.",
            })
        return turn_engine.process_turn(session, request.message)

    # CASE 3 — MALFORMED (neither candidate nor message)
    raise HTTPException(status_code=400, detail={
        "error": "BAD_REQUEST",
        "detail": "Include 'candidate' to start or 'message' to continue.",
    })
