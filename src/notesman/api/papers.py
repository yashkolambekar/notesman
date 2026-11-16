import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.api.deps import current_user, require_admin
from notesman.api.fractional import key_between
from notesman.api.schemas import (
    GenerateIn,
    MoveIn,
    PaperIn,
    PaperMetaOut,
    PaperOut,
    QuestionIn,
    QuestionOut,
    QuestionPatch,
)
from notesman.api.subjects import is_admin
from notesman.answer.generate import NoMaterial, generate_answer as run_generation
from notesman.core.config import get_settings
from notesman.db.base import get_session
from notesman.llm.gemini import EmbedError
from notesman.llm.openrouter import ChatError
from notesman.db.models import Paper, Question, Subject, User

router = APIRouter(prefix="/v1", tags=["papers"])


def strip_cites(md: str) -> str:
    """Citations like [1] stay in the stored answer (the admin panel uses them) but never appear in a paper."""
    return re.sub(r"[ \t]?\[\d+\](?!\()", "", md)


def q_out(q: Question, admin: bool) -> QuestionOut:
    return QuestionOut(
        id=q.id,
        position=q.position,
        prompt=q.prompt,
        answer_md=q.answer_md,
        status=q.status,
        syllabus_match=q.syllabus_match,
        sources=q.sources,
        previous_answer_md=q.previous_answer_md if admin else None,
        last_steer=q.last_steer if admin else None,
    )


async def _paper(db: AsyncSession, paper_id: uuid.UUID) -> Paper:
    paper = await db.get(Paper, paper_id)
    if paper is None:
        raise HTTPException(404, "Paper not found")
    return paper


async def _question(db: AsyncSession, question_id: uuid.UUID) -> Question:
    q = await db.get(Question, question_id)
    if q is None:
        raise HTTPException(404, "Question not found")
    return q


async def _visible_questions(db: AsyncSession, paper_id: uuid.UUID, admin: bool) -> list[Question]:
    stmt = select(Question).where(Question.paper_id == paper_id).order_by(Question.position)
    if not admin:
        stmt = stmt.where(Question.status == "locked")
    return list((await db.execute(stmt)).scalars().all())


# ---- papers --------------------------------------------------------------------------
@router.post("/subjects/{subject_id}/papers", response_model=PaperMetaOut, status_code=201, dependencies=[Depends(require_admin)])
async def create_paper(subject_id: uuid.UUID, body: PaperIn, db: AsyncSession = Depends(get_session)):
    if await db.get(Subject, subject_id) is None:
        raise HTTPException(404, "Subject not found")
    paper = Paper(subject_id=subject_id, title=body.title.strip())
    db.add(paper)
    await db.commit()
    return PaperMetaOut(id=paper.id, title=paper.title, locked=0, total=0)


@router.get("/papers/{paper_id}", response_model=PaperOut)
async def get_paper(
    paper_id: uuid.UUID,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    paper = await _paper(db, paper_id)
    admin = is_admin(user)
    qs = await _visible_questions(db, paper_id, admin)
    return PaperOut(
        id=paper.id, subject_id=paper.subject_id, title=paper.title,
        questions=[q_out(q, admin) for q in qs],
    )


@router.patch("/papers/{paper_id}", response_model=PaperMetaOut, dependencies=[Depends(require_admin)])
async def rename_paper(paper_id: uuid.UUID, body: PaperIn, db: AsyncSession = Depends(get_session)):
    paper = await _paper(db, paper_id)
    paper.title = body.title.strip()
    await db.commit()
    qs = await _visible_questions(db, paper_id, True)
    return PaperMetaOut(
        id=paper.id, title=paper.title,
        locked=sum(q.status == "locked" for q in qs), total=len(qs),
    )


@router.delete("/papers/{paper_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_paper(paper_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    await db.delete(await _paper(db, paper_id))
    await db.commit()


@router.get("/papers/{paper_id}/export")
async def export_paper(
    paper_id: uuid.UUID,
    include_drafts: bool = Query(False),
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    paper = await _paper(db, paper_id)
    admin = is_admin(user)
    if include_drafts and not admin:
        raise HTTPException(403, "Not allowed")
    qs = await _visible_questions(db, paper_id, admin and include_drafts)
    parts = [f"# {paper.title}\n"]
    for i, q in enumerate(qs, 1):
        parts.append(f"## {i}. {q.prompt}\n\n{strip_cites(q.answer_md).strip()}\n")
    parts.append("---\nMade with Notesman\n")
    slug = re.sub(r"[^a-z0-9]+", "-", paper.title.lower()).strip("-") or "paper"
    return PlainTextResponse(
        "\n".join(parts),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.md"'},
    )


# ---- questions -----------------------------------------------------------------------
@router.post("/papers/{paper_id}/questions", response_model=QuestionOut, status_code=201, dependencies=[Depends(require_admin)])
async def add_question(paper_id: uuid.UUID, body: QuestionIn, db: AsyncSession = Depends(get_session)):
    await _paper(db, paper_id)
    last = (
        await db.execute(
            select(Question.position)
            .where(Question.paper_id == paper_id)
            .order_by(Question.position.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    q = Question(paper_id=paper_id, position=key_between(last, None), prompt=body.prompt.strip())
    db.add(q)
    await db.commit()
    return q_out(q, True)


@router.patch("/questions/{question_id}", response_model=QuestionOut, dependencies=[Depends(require_admin)])
async def edit_question(question_id: uuid.UUID, body: QuestionPatch, db: AsyncSession = Depends(get_session)):
    q = await _question(db, question_id)
    if q.status == "locked":
        raise HTTPException(409, "Unlock the question before editing it")
    if body.prompt is not None:
        q.prompt = body.prompt.strip()
    if body.answer_md is not None:
        q.answer_md = body.answer_md
    await db.commit()
    return q_out(q, True)


@router.post("/questions/{question_id}/lock", response_model=QuestionOut, dependencies=[Depends(require_admin)])
async def lock_question(question_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    q = await _question(db, question_id)
    if not q.answer_md.strip():
        raise HTTPException(409, "There is no answer to lock yet")
    q.status, q.previous_answer_md, q.locked_at = "locked", None, datetime.now(UTC)
    await db.commit()
    return q_out(q, True)


@router.post("/questions/{question_id}/unlock", response_model=QuestionOut, dependencies=[Depends(require_admin)])
async def unlock_question(question_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    q = await _question(db, question_id)
    q.status, q.previous_answer_md, q.locked_at = "draft", q.answer_md, None
    await db.commit()
    return q_out(q, True)


@router.post("/questions/{question_id}/move", response_model=QuestionOut, dependencies=[Depends(require_admin)])
async def move_question(question_id: uuid.UUID, body: MoveIn, db: AsyncSession = Depends(get_session)):
    q = await _question(db, question_id)
    others = [x for x in await _visible_questions(db, q.paper_id, True) if x.id != q.id]
    if body.before_id is None:
        q.position = key_between(others[-1].position if others else None, None)
    else:
        idx = next((i for i, x in enumerate(others) if x.id == body.before_id), None)
        if idx is None:
            raise HTTPException(422, "before_id is not in this paper")
        q.position = key_between(others[idx - 1].position if idx > 0 else None, others[idx].position)
    await db.commit()
    return q_out(q, True)


@router.post("/questions/{question_id}/generate", response_model=QuestionOut, dependencies=[Depends(require_admin)])
async def generate_answer(
    question_id: uuid.UUID, body: GenerateIn, request: Request, db: AsyncSession = Depends(get_session)
):
    emb, chat = request.app.state.embedder, request.app.state.chat
    if emb is None or chat is None:
        raise HTTPException(503, "Set GEMINI_API_KEY and OPENROUTER_API_KEY to generate answers")
    if request.app.state.qdrant_error:
        raise HTTPException(503, f"Search index unavailable: {request.app.state.qdrant_error}")

    q = await _question(db, question_id)
    if q.status == "locked":
        raise HTTPException(409, "Unlock the question before regenerating")
    paper = await db.get(Paper, q.paper_id)
    subject = await db.get(Subject, paper.subject_id)
    prompt, previous = q.prompt, q.answer_md
    subject_id, subject_name = subject.id, subject.name
    await db.rollback()  # do not hold a DB transaction open during the model calls

    try:
        draft = await run_generation(
            qd=request.app.state.qdrant,
            s=get_settings(),
            emb=emb,
            chat=chat,
            subject_id=subject_id,
            subject_name=subject_name,
            question=prompt,
            nudges=body.nudges,
            comment=body.comment,
            previous=previous,
        )
    except NoMaterial:
        raise HTTPException(
            422,
            "Nothing in this subject's files is relevant to this question. Upload material that covers it, "
            "or reword the question.",
        ) from None
    except EmbedError as e:
        raise HTTPException(503, f"The embedding service is busy or failing, try again shortly. ({e})") from e
    except ChatError as e:
        raise HTTPException(502, f"The answer model failed: {e}") from e

    q = await _question(db, question_id)
    if q.status == "locked":  # locked by someone while we were generating
        raise HTTPException(409, "The question was locked while generating; nothing was changed")
    if q.answer_md.strip():
        q.previous_answer_md = q.answer_md
    q.answer_md = draft.answer_md
    q.sources = draft.sources
    q.syllabus_match = draft.syllabus_match
    q.last_steer = {"nudges": body.nudges, "comment": body.comment} if (body.nudges or body.comment) else None
    q.model = draft.model
    await db.commit()
    await db.refresh(q)
    return q_out(q, True)


@router.delete("/questions/{question_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_question(question_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    q = await _question(db, question_id)
    if q.status == "locked":
        raise HTTPException(409, "Unlock the question before deleting it")
    await db.delete(q)
    await db.commit()
