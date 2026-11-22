"""What the service has cost. Per-course totals are public, the full breakdown is for admins only."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from notesman.api.deps import current_user
from notesman.api.keys import require_key_owner
from notesman.db.base import get_session
from notesman.db.models import Course, Paper, Question, Subject, UsageEvent, User

router = APIRouter(prefix="/v1", tags=["usage"])


class AdminSpend(BaseModel):
    name: str
    cost_usd: float


class CourseSpend(BaseModel):
    total_usd: float
    by_admin: list[AdminSpend]
    papers: int
    questions: int
    embed_calls: int
    chat_calls: int
    input_tokens: int  # embedding tokens are estimated (see Spending page)
    output_tokens: int


@router.get("/courses/{course_id}/spend", response_model=CourseSpend)
async def course_spend(course_id: uuid.UUID, db: AsyncSession = Depends(get_session)):
    """Public on purpose: what this course has cost and which admins paid it. Display names only (never emails),
    and nothing per question."""
    if await db.get(Course, course_id) is None:
        raise HTTPException(404, "Course not found")
    rows = await db.execute(
        select(User.name, User.email, func.sum(UsageEvent.cost_usd))
        .select_from(UsageEvent)
        .join(Subject, Subject.id == UsageEvent.subject_id)
        .outerjoin(User, User.id == UsageEvent.user_id)
        .where(Subject.course_id == course_id)
        .group_by(User.id, User.name, User.email)
        .order_by(func.sum(UsageEvent.cost_usd).desc())
    )
    by_admin = [
        AdminSpend(name=name or (email.split("@")[0] if email else "Former admin"), cost_usd=float(c or 0))
        for name, email, c in rows
    ]
    calls = (
        await db.execute(
            select(
                func.count().filter(UsageEvent.kind == "embed"),
                func.count().filter(UsageEvent.kind == "chat"),
                func.coalesce(func.sum(UsageEvent.input_tokens), 0),
                func.coalesce(func.sum(UsageEvent.output_tokens), 0),
            )
            .join(Subject, Subject.id == UsageEvent.subject_id)
            .where(Subject.course_id == course_id)
        )
    ).one()
    papers = await db.scalar(
        select(func.count()).select_from(Paper).join(Subject, Subject.id == Paper.subject_id).where(Subject.course_id == course_id)
    )
    questions = await db.scalar(
        select(func.count())
        .select_from(Question)
        .join(Paper, Paper.id == Question.paper_id)
        .join(Subject, Subject.id == Paper.subject_id)
        .where(Subject.course_id == course_id)
    )
    return CourseSpend(
        total_usd=sum(a.cost_usd for a in by_admin), by_admin=by_admin, papers=papers or 0, questions=questions or 0,
        embed_calls=calls[0], chat_calls=calls[1], input_tokens=int(calls[2]), output_tokens=int(calls[3]),
    )


class Bucket(BaseModel):
    label: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class RecentCall(BaseModel):
    at: datetime
    purpose: str
    model: str
    cost_usd: float
    estimated: bool
    subject: str | None
    question: str | None
    admin: str | None


class UsageOut(BaseModel):
    scope: str  # "own" or "all"
    total_usd: float
    estimated_usd: float  # part of the total that is estimated rather than reported by the provider
    by_purpose: list[Bucket]
    by_subject: list[Bucket]
    by_day: list[Bucket]
    by_admin: list[Bucket]  # superadmin only
    recent: list[RecentCall]


def _buckets(rows) -> list[Bucket]:
    return [
        Bucket(label=str(label), calls=n, input_tokens=int(ti or 0), output_tokens=int(to or 0), cost_usd=float(c or 0))
        for label, n, ti, to, c in rows
    ]


@router.get("/me/usage", response_model=UsageOut)
async def my_usage(db: AsyncSession = Depends(get_session), user: User | None = Depends(current_user)):
    """Admins see what their own keys spent. The superadmin sees everyone's, split per admin."""
    await require_key_owner(db, user)
    everyone = user.role == "superadmin"
    mine = [] if everyone else [UsageEvent.user_id == user.id]

    def agg(*group):
        return (
            select(*group, func.count(), func.sum(UsageEvent.input_tokens), func.sum(UsageEvent.output_tokens),
                   func.sum(UsageEvent.cost_usd))
            .where(*mine)
            .group_by(*group)
        )

    total = await db.scalar(select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(*mine))
    est = await db.scalar(
        select(func.coalesce(func.sum(UsageEvent.cost_usd), 0)).where(*mine, UsageEvent.estimated.is_(True))
    )
    by_purpose = _buckets(await db.execute(agg(UsageEvent.purpose).order_by(func.sum(UsageEvent.cost_usd).desc())))

    subj_rows = await db.execute(
        select(func.coalesce(Subject.name, "(deleted subject)"), func.count(), func.sum(UsageEvent.input_tokens),
               func.sum(UsageEvent.output_tokens), func.sum(UsageEvent.cost_usd))
        .select_from(UsageEvent)
        .outerjoin(Subject, Subject.id == UsageEvent.subject_id)
        .where(*mine)
        .group_by(Subject.name)
        .order_by(func.sum(UsageEvent.cost_usd).desc())
    )
    since = datetime.now(UTC) - timedelta(days=30)
    day = func.date(UsageEvent.created_at)
    day_rows = await db.execute(agg(day).where(UsageEvent.created_at >= since).order_by(day.desc()))

    by_admin: list[Bucket] = []
    if everyone:
        by_admin = _buckets(
            await db.execute(
                select(func.coalesce(User.name, User.email, "(removed user)"), func.count(),
                       func.sum(UsageEvent.input_tokens), func.sum(UsageEvent.output_tokens), func.sum(UsageEvent.cost_usd))
                .select_from(UsageEvent)
                .outerjoin(User, User.id == UsageEvent.user_id)
                .group_by(User.name, User.email)
                .order_by(func.sum(UsageEvent.cost_usd).desc())
            )
        )

    recent_rows = await db.execute(
        select(UsageEvent, Subject.name, Question.prompt, User.name, User.email)
        .outerjoin(Subject, Subject.id == UsageEvent.subject_id)
        .outerjoin(Question, Question.id == UsageEvent.question_id)
        .outerjoin(User, User.id == UsageEvent.user_id)
        .where(*mine)
        .order_by(UsageEvent.created_at.desc())
        .limit(50)
    )
    recent = [
        RecentCall(
            at=e.created_at, purpose=e.purpose, model=e.model, cost_usd=float(e.cost_usd), estimated=e.estimated,
            subject=sname, question=(prompt[:80] if prompt else None), admin=(uname or email) if everyone else None,
        )
        for e, sname, prompt, uname, email in recent_rows
    ]
    return UsageOut(
        scope="all" if everyone else "own", total_usd=float(total), estimated_usd=float(est),
        by_purpose=by_purpose, by_subject=_buckets(subj_rows), by_day=_buckets(day_rows), by_admin=by_admin, recent=recent,
    )
