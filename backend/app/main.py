import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routes import ai, ingest, org, work
from .services import kestra, llm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Relay API", version="0.1.0",
              description="AI task manager: self-updating tasks, on-call agent, SOPs, feed and Ask.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
for r in (org.router, work.router, ai.router, ingest.router):
    app.include_router(r)


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/health")
def health():
    return {"ok": True, "gemini": llm.enabled(), "kestra": kestra.is_up()}
