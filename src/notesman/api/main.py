from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import text

from notesman.api import admin, auth, papers, subjects
from notesman.api.origin import OriginCheck
from notesman.api.security import origin_of
from notesman.core.config import get_settings
from notesman.db.base import engine
from notesman.llm.gemini import GeminiEmbedder
from notesman.llm.openrouter import OpenRouterChat
from notesman.retrieval.qdrant import ensure_collection, make_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.qdrant = make_client(s)
    try:
        await ensure_collection(app.state.qdrant, s)
        app.state.qdrant_error = None
    except Exception as e:  # keep the API up so /health can explain what is wrong
        app.state.qdrant_error = str(e)
    # Answer generation needs both keys; without them the endpoint answers 503 with a clear message.
    app.state.embedder = GeminiEmbedder(s) if s.gemini_api_key else None
    app.state.chat = OpenRouterChat(s) if s.openrouter_api_key else None
    yield
    for c in (app.state.embedder, app.state.chat):
        if c:
            await c.aclose()
    await app.state.qdrant.close()
    await engine.dispose()


app = FastAPI(title="Notesman", lifespan=lifespan)

_s = get_settings()
if not _s.session_secret:
    raise RuntimeError("SESSION_SECRET is not set")
SESSION_COOKIE = "notesman_session"
# Added first = innermost: OriginCheck runs inside SessionMiddleware.
app.add_middleware(OriginCheck, allowed_origin=origin_of(_s.public_base_url), cookie_name=SESSION_COOKIE)
app.add_middleware(
    SessionMiddleware,
    secret_key=_s.session_secret,
    session_cookie=SESSION_COOKIE,
    max_age=60 * 60 * 24 * 30,
    same_site="lax",
    https_only=_s.public_base_url.startswith("https://"),
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(subjects.router)
app.include_router(papers.router)


@app.get("/health")
async def health():
    s = get_settings()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        db = "ok"
    except Exception as e:
        db = str(e)[:200]
    return {
        "status": "ok" if app.state.qdrant_error is None and db == "ok" else "degraded",
        "qdrant": app.state.qdrant_error or "ok",
        "postgres": db,
        "collection": s.qdrant_collection,
        "embed_model": s.embed_model,
        "embed_dim": s.embed_dim,
        "gemini_key_set": bool(s.gemini_api_key),
        "openrouter_key_set": bool(s.openrouter_api_key),
    }
