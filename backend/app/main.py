import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routes import ai, ingest, org, people, work
from .services import llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Relay API", version="0.1.0",
              description="AI chief of staff: self-updating tasks, My Day, Focus Guard, Team Health, meetings, on-call agent, SOPs, feed and Ask.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for r in (org.router, work.router, ai.router, people.router, ingest.router):
    app.include_router(r)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health():
    return {"ok": True, "gemini": llm.enabled(), "models": llm.model_names()}
