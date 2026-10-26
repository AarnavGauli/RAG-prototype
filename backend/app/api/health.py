from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text

from app import __version__
from app.context import AppContext
from app.errors import ProviderError
from app.schemas import HealthOut, ProviderStatus
from app.security import get_ctx, get_owner

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthOut)
def health(ctx: AppContext = Depends(get_ctx), _owner: str = Depends(get_owner)) -> HealthOut:
    # Depending on get_owner makes this the call that establishes the session cookie: the UI awaits it before issuing
    # any other request, so parallel first-visit requests cannot each mint a different session.
    try:
        with ctx.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    s = ctx.settings
    emb_ready, emb_detail = True, None
    if s.embedding_provider == "openai":
        try:
            ctx.embedder.check_ready()
        except ProviderError as exc:
            emb_ready, emb_detail = False, exc.message
    elif s.embedding_provider == "fastembed":
        emb_detail = "Local model; downloaded on first use." if not getattr(ctx.embedder, "dim", 0) else None
    elif s.embedding_provider == "hash":
        emb_detail = "Offline hashing embeddings (lower retrieval quality)."

    llm_ready, llm_detail = True, None
    try:
        ctx.llm.check_ready()
    except ProviderError as exc:
        llm_ready, llm_detail = False, exc.message

    return HealthOut(
        status="ok" if db_ok else "degraded",
        version=__version__,
        database=db_ok,
        indexed_chunks=ctx.vectors.count,
        embedding=ProviderStatus(
            provider=s.embedding_provider, model=ctx.embedder.model_id, ready=emb_ready, detail=emb_detail
        ),
        llm=ProviderStatus(provider=s.llm_provider, model=ctx.llm.model, ready=llm_ready, detail=llm_detail),
        limits={
            "max_upload_mb": s.max_upload_mb,
            "max_documents": s.max_documents,
            "max_question_chars": s.max_question_chars,
        },
    )
