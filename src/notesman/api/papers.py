import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.api.deps import can_manage, current_user, require_manager
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
from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse

from notesman.api.keys import MissingKeys, missing_message, user_keys
from notesman.core.crypto import KeyVaultError
from notesman.core.usage import UsageCollector
from notesman.llm.openrouter import OpenRouterChat
from notesman.answer.generate import NoMaterial, generate_answer as run_generation
from notesman.core.config import get_settings
from notesman.db.base import get_session
from notesman.llm.gemini import EmbedError, GeminiEmbedder
from notesman.llm.openrouter import ChatError
from notesman.db.models import Paper, Question, Subject, UsageEvent, User

router = APIRouter(prefix="/v1", tags=["papers"])


def strip_cites(md: str) -> str:
    """Citations like [1] stay in the stored answer (the admin panel uses them) but never appear in a paper."""
    return re.sub(r"[ \t]?\[\d+\](?!\()", "", md)


def q_out(q: Question, admin: bool, cost: tuple[float, int] | None = None) -> QuestionOut:
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
        cost_usd=cost[0] if admin and cost else (0.0 if admin else None),
        cost_calls=cost[1] if admin and cost else (0 if admin else None),
    )


async def question_costs(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[float, int]]:
    if not ids:
        return {}
    rows = await db.execute(
        select(UsageEvent.question_id, func.sum(UsageEvent.cost_usd), func.count())
        .where(UsageEvent.question_id.in_(ids))
        .group_by(UsageEvent.question_id)
    )
    return {qid: (float(total or 0), n) for qid, total, n in rows}


async def q_out_admin(db: AsyncSession, q: Question) -> QuestionOut:
    return q_out(q, True, (await question_costs(db, [q.id])).get(q.id))


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


async def _guard_question(db: AsyncSession, user: User | None, q: Question) -> None:
    """Admin rights on the subject that owns this question."""
    paper = await db.get(Paper, q.paper_id)
    await require_manager(db, user, paper.subject_id)


async def _visible_questions(db: AsyncSession, paper_id: uuid.UUID, admin: bool) -> list[Question]:
    stmt = select(Question).where(Question.paper_id == paper_id).order_by(Question.position)
    if not admin:
        stmt = stmt.where(Question.status == "locked")
    return list((await db.execute(stmt)).scalars().all())


# ---- papers --------------------------------------------------------------------------
@router.post("/subjects/{subject_id}/papers", response_model=PaperMetaOut, status_code=201)
async def create_paper(
    subject_id: uuid.UUID,
    body: PaperIn,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    await require_manager(db, user, subject_id)
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
    admin = await can_manage(db, user, paper.subject_id)
    if not admin:
        subject = await db.get(Subject, paper.subject_id)
        if paper.archived_at or subject.archived_at:
            raise HTTPException(404, "Paper not found")
    qs = await _visible_questions(db, paper_id, admin)
    costs = await question_costs(db, [q.id for q in qs]) if admin else {}
    return PaperOut(
        id=paper.id, subject_id=paper.subject_id, title=paper.title,
        questions=[q_out(q, admin, costs.get(q.id)) for q in qs],
        cost_usd=sum(c for c, _ in costs.values()) if admin else None,
    )


@router.patch("/papers/{paper_id}", response_model=PaperMetaOut)
async def rename_paper(
    paper_id: uuid.UUID,
    body: PaperIn,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    paper = await _paper(db, paper_id)
    await require_manager(db, user, paper.subject_id)
    paper.title = body.title.strip()
    await db.commit()
    qs = await _visible_questions(db, paper_id, True)
    return PaperMetaOut(
        id=paper.id, title=paper.title,
        locked=sum(q.status == "locked" for q in qs), total=len(qs),
    )


async def _set_paper_archived(db: AsyncSession, user: User | None, paper_id: uuid.UUID, archived: bool):
    paper = await _paper(db, paper_id)
    await require_manager(db, user, paper.subject_id)
    paper.archived_at = datetime.now(UTC) if archived else None
    await db.commit()
    qs = await _visible_questions(db, paper_id, True)
    return PaperMetaOut(
        id=paper.id, title=paper.title,
        locked=sum(q.status == "locked" for q in qs), total=len(qs),
    )


@router.post("/papers/{paper_id}/archive", response_model=PaperMetaOut)
async def archive_paper(
    paper_id: uuid.UUID, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    return await _set_paper_archived(db, user, paper_id, True)


@router.post("/papers/{paper_id}/unarchive", response_model=PaperMetaOut)
async def unarchive_paper(
    paper_id: uuid.UUID, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    return await _set_paper_archived(db, user, paper_id, False)


@router.delete("/papers/{paper_id}", status_code=204)
async def delete_paper(
    paper_id: uuid.UUID, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    paper = await _paper(db, paper_id)
    await require_manager(db, user, paper.subject_id)
    await db.delete(paper)
    await db.commit()


@router.get("/papers/{paper_id}/export")
async def export_paper(
    paper_id: uuid.UUID,
    include_drafts: bool = Query(False),
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    paper = await _paper(db, paper_id)
    admin = await can_manage(db, user, paper.subject_id)
    if include_drafts and not admin:
        raise HTTPException(403, "Not allowed")
    if not admin and (paper.archived_at or (await db.get(Subject, paper.subject_id)).archived_at):
        raise HTTPException(404, "Paper not found")
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
@router.post("/papers/{paper_id}/questions", response_model=QuestionOut, status_code=201)
async def add_question(
    paper_id: uuid.UUID,
    body: QuestionIn,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    paper = await _paper(db, paper_id)
    await require_manager(db, user, paper.subject_id)
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
    return await q_out_admin(db, q)


@router.patch("/questions/{question_id}", response_model=QuestionOut)
async def edit_question(
    question_id: uuid.UUID,
    body: QuestionPatch,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    q = await _question(db, question_id)
    await _guard_question(db, user, q)
    if q.status == "locked":
        raise HTTPException(409, "Unlock the question before editing it")
    if body.prompt is not None:
        q.prompt = body.prompt.strip()
    if body.answer_md is not None:
        q.answer_md = body.answer_md
    await db.commit()
    return await q_out_admin(db, q)


@router.post("/questions/{question_id}/lock", response_model=QuestionOut)
async def lock_question(
    question_id: uuid.UUID, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    q = await _question(db, question_id)
    await _guard_question(db, user, q)
    if not q.answer_md.strip():
        raise HTTPException(409, "There is no answer to lock yet")
    q.status, q.previous_answer_md, q.locked_at = "locked", None, datetime.now(UTC)
    await db.commit()
    return await q_out_admin(db, q)


@router.post("/questions/{question_id}/unlock", response_model=QuestionOut)
async def unlock_question(
    question_id: uuid.UUID, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    q = await _question(db, question_id)
    await _guard_question(db, user, q)
    q.status, q.previous_answer_md, q.locked_at = "draft", q.answer_md, None
    await db.commit()
    return await q_out_admin(db, q)


@router.post("/questions/{question_id}/move", response_model=QuestionOut)
async def move_question(
    question_id: uuid.UUID,
    body: MoveIn,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    q = await _question(db, question_id)
    await _guard_question(db, user, q)
    others = [x for x in await _visible_questions(db, q.paper_id, True) if x.id != q.id]
    if body.before_id is None:
        q.position = key_between(others[-1].position if others else None, None)
    else:
        idx = next((i for i, x in enumerate(others) if x.id == body.before_id), None)
        if idx is None:
            raise HTTPException(422, "before_id is not in this paper")
        q.position = key_between(others[idx - 1].position if idx > 0 else None, others[idx].position)
    await db.commit()
    return await q_out_admin(db, q)


@router.post("/questions/{question_id}/generate", response_model=QuestionOut)
async def generate_answer(
    question_id: uuid.UUID,
    body: GenerateIn,
    request: Request,
    db: AsyncSession = Depends(get_session),
    user: User | None = Depends(current_user),
):
    q = await _question(db, question_id)
    await _guard_question(db, user, q)
    if request.app.state.qdrant_error:
        raise HTTPException(503, f"Search index unavailable: {request.app.state.qdrant_error}")

    if q.status == "locked":
        raise HTTPException(409, "Unlock the question before regenerating")
    paper = await db.get(Paper, q.paper_id)
    subject = await db.get(Subject, paper.subject_id)
    prompt, previous = q.prompt, q.answer_md
    subject_id, subject_name = subject.id, subject.name
    user_id = user.id  # read now: rollback() below expires ORM objects and they cannot reload in a finally
    # Only the signed-in admin's own keys are used, never anyone else's or a server-wide key.
    try:
        own = await user_keys(db, user_id, ("gemini", "openrouter"))
    except MissingKeys as e:
        raise HTTPException(400, missing_message(e)) from e
    except KeyVaultError as e:
        raise HTTPException(503, str(e)) from e
    await db.rollback()  # do not hold a DB transaction open during the model calls

    s = get_settings()
    usage = UsageCollector()
    emb = GeminiEmbedder(s, api_key=own["gemini"], usage=usage)
    chat = OpenRouterChat(s, api_key=own["openrouter"], usage=usage)
    try:
        draft = await run_generation(
            qd=request.app.state.qdrant,
            s=s,
            emb=emb,
            chat=chat,
            subject_id=subject_id,
            subject_name=subject_name,
            question=prompt,
            nudges=body.nudges,
            comment=body.comment,
            previous=previous,
            allow_unsourced=body.allow_unsourced,
        )
    except NoMaterial:
        raise HTTPException(
            422,
            {
                "code": "no_material",
                "message": "Nothing in this subject's files is relevant to this question. Upload material that "
                "covers it, reword the question, or answer anyway from general knowledge.",
            },
        ) from None
    except EmbedError as e:
        raise HTTPException(503, f"The embedding service is busy or failing, try again shortly. ({e})") from e
    except ChatError as e:
        raise HTTPException(502, f"The answer model failed: {e}") from e
    except (ResponseHandlingException, UnexpectedResponse) as e:
        raise HTTPException(503, f"The search index (Qdrant) is unreachable, try again shortly. ({type(e).__name__})") from e
    finally:
        await emb.aclose()
        await chat.aclose()
        # money was spent even if the generation failed, so always record it
        await usage.flush(user_id=user_id, subject_id=subject_id, question_id=question_id)

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
    return await q_out_admin(db, q)


@router.delete("/questions/{question_id}", status_code=204)
async def delete_question(
    question_id: uuid.UUID, db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)
):
    q = await _question(db, question_id)
    await _guard_question(db, user, q)
    if q.status == "locked":
        raise HTTPException(409, "Unlock the question before deleting it")
    await db.delete(q)
    await db.commit()
