"""FastAPI server: serves the web UI and streams agent events over Server-Sent Events.

The Agent SDK has no web layer of its own. Each browser session gets an AgentSession, owned by a dedicated
background task, because a ClaudeSDKClient must stay in the async context where it was connected. Requests talk
to that task through queues.

  uv run uvicorn server.app:app --port 8000
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ahdc_agent.agent import AgentSession
from ahdc_agent.db import ROOT

WEB = ROOT / "web"


class SessionWorker:
    """Owns one AgentSession for its whole life and runs questions one at a time."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.ready = asyncio.Event()
        self.error: BaseException | None = None
        self.session: AgentSession | None = None
        self.busy = False
        self.task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        try:
            async with AgentSession() as session:
                self.session = session
                self.ready.set()
                while (item := await self.inbox.get()) is not None:
                    question, out = item
                    try:
                        async for ev in session.ask(question):
                            await out.put(ev)
                    except Exception as e:  # report, keep the session alive
                        await out.put({"type": "error", "message": f"Agent error: {e}"})
                    finally:
                        await out.put(None)
        except BaseException as e:
            self.error = e
            self.ready.set()
            raise

    async def ask(self, question: str) -> AsyncIterator[dict[str, Any]]:
        await self.ready.wait()
        if self.error:
            yield {"type": "error", "message": f"Could not start the agent: {self.error}"}
            return
        out: asyncio.Queue = asyncio.Queue()
        await self.inbox.put((question, out))
        while (ev := await out.get()) is not None:
            yield ev

    async def close(self) -> None:
        await self.inbox.put(None)
        try:
            await asyncio.wait_for(self.task, timeout=10)
        except (asyncio.TimeoutError, Exception):
            self.task.cancel()


workers: dict[str, SessionWorker] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await asyncio.gather(*(w.close() for w in workers.values()), return_exceptions=True)


app = FastAPI(title="AHDC Data Explorer", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")


class Ask(BaseModel):
    question: str


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.post("/api/session")
async def new_session() -> dict[str, str]:
    sid = uuid.uuid4().hex[:12]
    workers[sid] = SessionWorker()
    return {"session": sid}


@app.post("/api/session/{sid}/close")
async def close_session(sid: str) -> dict[str, bool]:
    w = workers.pop(sid, None)
    if w:
        asyncio.create_task(w.close())
    return {"closed": w is not None}


@app.post("/api/session/{sid}/ask")
async def ask(sid: str, body: Ask) -> StreamingResponse:
    w = workers.get(sid)
    if w is None:
        raise HTTPException(404, "Unknown session")
    if w.busy:
        raise HTTPException(409, "This session is still answering the previous question")
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Empty question")

    async def stream() -> AsyncIterator[str]:
        w.busy = True
        try:
            async for ev in w.ask(question):
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
        finally:
            w.busy = False

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/session/{sid}/trace/{turn}")
async def raw_trace(sid: str, turn: int) -> JSONResponse:
    """The raw Agent SDK messages for one turn: what the 'raw trace' link opens."""
    w = workers.get(sid)
    if not w or not w.session or not (1 <= turn <= len(w.session.state.turns)):
        raise HTTPException(404, "No such turn")
    t = w.session.state.turns[turn - 1]
    return JSONResponse({"session_id": w.session.session_id, "turn": turn, "question": t.question,
                         "messages": t.raw_messages})
