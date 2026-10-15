from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

EMBED_DIM = 768


class Base(DeclarativeBase):
    type_annotation_map = {dict: JSONB, list: JSONB}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Org(Base, TimestampMixin):
    __tablename__ = "orgs"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    region: Mapped[str] = mapped_column(String(40), default="asia-south1")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "email"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), index=True)
    kind: Mapped[str] = mapped_column(String(10), default="human")  # human | agent
    title: Mapped[str | None] = mapped_column(String(200))
    initials: Mapped[str] = mapped_column(String(4))
    color: Mapped[str] = mapped_column(String(9), default="#3A3A3C")
    is_org_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    email_capture: Mapped[bool] = mapped_column(Boolean, default=True)
    # Consent to show personal wellbeing signals (after-hours work) to managers; workload is always visible.
    share_wellbeing: Mapped[bool] = mapped_column(Boolean, default=False)


class Team(Base, TimestampMixin):
    __tablename__ = "teams"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    short: Mapped[str] = mapped_column(String(4))
    color: Mapped[str] = mapped_column(String(9))
    handles: Mapped[str] = mapped_column(Text, default="")
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    # suggest = AI only suggests; draft = AI prepares work for approval; act = AI acts then tells
    autonomy: Mapped[str] = mapped_column(String(10), default="draft")
    task_seq: Mapped[int] = mapped_column(Integer, default=0)
    handles_embedding = mapped_column(Vector(EMBED_DIM), nullable=True)


class TeamMember(Base):
    __tablename__ = "team_members"
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role: Mapped[str] = mapped_column(String(10), default="member")  # admin | lead | member


class Resource(Base, TimestampMixin):
    """Anything a workflow touches: pipelines, tables, repos, sheets, inboxes, connections."""
    __tablename__ = "resources"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(40))
    owner_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    business_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)


class Lineage(Base):
    __tablename__ = "lineage"
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    upstream_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True)
    downstream_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True)


class Sop(Base, TimestampMixin):
    __tablename__ = "sops"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="draft")  # draft | published
    version: Mapped[int] = mapped_column(Integer, default=1)
    source_file: Mapped[str | None] = mapped_column(String(300))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class SopStep(Base):
    __tablename__ = "sop_steps"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    sop_id: Mapped[int] = mapped_column(ForeignKey("sops.id", ondelete="CASCADE"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(300))
    owner_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    owner_role: Mapped[str | None] = mapped_column(String(60))  # e.g. "hiring manager"
    evidence_type: Mapped[str] = mapped_column(String(12), default="manual")  # email|calendar|file|task|manual
    evidence_hint: Mapped[str] = mapped_column(Text, default="")
    due_offset_days: Mapped[int] = mapped_column(Integer, default=0)
    depends_on: Mapped[list[int]] = mapped_column(ARRAY(Integer), default=list)  # seq numbers
    needs_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")


class Project(Base, TimestampMixin):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str | None] = mapped_column(String(200))  # e.g. the new joiner's name
    sop_id: Mapped[int | None] = mapped_column(ForeignKey("sops.id", ondelete="SET NULL"))
    sop_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="active")
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Task(Base, TimestampMixin):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(20), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"), index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(12), default="feature")  # feature|bug|incident|review|request|chore|sop_step
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text, default="")
    description_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(10), default="todo")  # todo|doing|review|done
    priority: Mapped[str] = mapped_column(String(8), default="normal")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    estimate_min: Mapped[int | None] = mapped_column(Integer)
    actual_min: Mapped[int | None] = mapped_column(Integer)  # focused minutes spent, known for finished tasks
    expected_outcome: Mapped[str | None] = mapped_column(Text)
    outcome_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    # [{id, text, waiting_on, source, at, resolved_at}] — open blockers have no resolved_at
    blockers: Mapped[list] = mapped_column(JSONB, default=list)
    links: Mapped[list] = mapped_column(JSONB, default=list)  # [{kind, label, url, ref}]
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)


class WorkLog(Base, TimestampMixin):
    __tablename__ = "work_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    on_behalf_of_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(String(12))  # claude|cursor|codex|antigravity|git|email|calendar|meeting|oncall|manual|sop
    summary: Mapped[str] = mapped_column(Text)
    raw_ref: Mapped[str | None] = mapped_column(String(300))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict)
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)


class EmailRequest(Base, TimestampMixin):
    __tablename__ = "email_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    thread_id: Mapped[str] = mapped_column(String(200), index=True)
    from_addr: Mapped[str] = mapped_column(String(320))
    to_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    subject: Mapped[str] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attachments: Mapped[list] = mapped_column(JSONB, default=list)


class StepProgress(Base, TimestampMixin):
    __tablename__ = "step_progress"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    sop_step_id: Mapped[int] = mapped_column(ForeignKey("sop_steps.id", ondelete="CASCADE"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    # pending | needs_confirmation | done | done_out_of_order | skipped
    status: Mapped[str] = mapped_column(String(20), default="pending")
    matched_log_id: Mapped[int | None] = mapped_column(ForeignKey("work_logs.id", ondelete="SET NULL"))
    confidence: Mapped[float | None] = mapped_column(Float)
    confirmed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Incident(Base, TimestampMixin):
    __tablename__ = "incidents"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(20))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    review_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("resources.id", ondelete="SET NULL"))
    namespace: Mapped[str] = mapped_column(String(200))
    flow_id: Mapped[str] = mapped_column(String(200))
    execution_id: Mapped[str] = mapped_column(String(100))
    # open | investigating | fix_proposed | verifying | resolved | needs_human
    status: Mapped[str] = mapped_column(String(14), default="open")
    severity: Mapped[str] = mapped_column(String(8), default="high")
    category: Mapped[str | None] = mapped_column(String(12))  # technical | business
    cause_kind: Mapped[str | None] = mapped_column(String(40))
    root_cause: Mapped[str | None] = mapped_column(Text)
    root_cause_title: Mapped[str | None] = mapped_column(String(300))
    confidence: Mapped[float | None] = mapped_column(Float)
    steps: Mapped[list] = mapped_column(JSONB, default=list)
    fix: Mapped[dict] = mapped_column(JSONB, default=dict)
    impact: Mapped[list] = mapped_column(JSONB, default=list)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    embedding = mapped_column(Vector(EMBED_DIM), nullable=True)


class FeedItem(Base, TimestampMixin):
    __tablename__ = "feed_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(12))  # needs|incident|stuck|win|decision|trend|invisible
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float, default=0)
    subject_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    actions: Mapped[list] = mapped_column(JSONB, default=list)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), index=True)


class Reaction(Base, TimestampMixin):
    __tablename__ = "reactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    feed_item_id: Mapped[int] = mapped_column(ForeignKey("feed_items.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))  # kudos | nudge | seen


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(300))
    target_type: Mapped[str | None] = mapped_column(String(30))
    target_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[str] = mapped_column(String(200), default="")


class Event(Base, TimestampMixin):
    """Work queue between the API and the worker (no RLS: the worker reads every org)."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(30))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RunnerRun(Base, TimestampMixin):
    """Log of warehouse model runs by the pipeline runner (no RLS: infrastructure table)."""
    __tablename__ = "runner_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(10))
    error: Mapped[str | None] = mapped_column(Text)
    sql: Mapped[str] = mapped_column(Text)
    execution_id: Mapped[str | None] = mapped_column(String(100))


class CalendarEvent(Base, TimestampMixin):
    __tablename__ = "calendar_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(10), default="meeting")  # meeting | focus | other
    source: Mapped[str] = mapped_column(String(10), default="calendar")  # calendar | relay
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    attendees: Mapped[list] = mapped_column(JSONB, default=list)


class DayPlan(Base, TimestampMixin):
    __tablename__ = "day_plans"
    __table_args__ = (UniqueConstraint("user_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    day: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD in the org's timezone
    summary: Mapped[str] = mapped_column(Text, default="")
    items: Mapped[list] = mapped_column(JSONB, default=list)
    focus_minutes: Mapped[int] = mapped_column(Integer, default=0)
    by_ai: Mapped[bool] = mapped_column(Boolean, default=False)


class Notification(Base, TimestampMixin):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # nudge|review|request|incident|kudos|health|meeting|fyi|question|blocker
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, default="")
    urgent: Mapped[bool] = mapped_column(Boolean, default=False)
    why: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(10), default="delivered")  # delivered | held | released | read
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id", ondelete="SET NULL"))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Meeting(Base, TimestampMixin):
    __tablename__ = "meetings"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    file_name: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(12), default="processing")  # processing | done | failed
    summary: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[dict] = mapped_column(JSONB, default=dict)
    error: Mapped[str | None] = mapped_column(Text)


class Standup(Base, TimestampMixin):
    __tablename__ = "standups"
    __table_args__ = (UniqueConstraint("team_id", "day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"))
    day: Mapped[str] = mapped_column(String(10))
    people: Mapped[list] = mapped_column(JSONB, default=list)
    by_ai: Mapped[bool] = mapped_column(Boolean, default=False)


class AgentDevice(Base, TimestampMixin):
    """A relay-agent install on someone's laptop, and which AI coding tools it can see."""
    __tablename__ = "agent_devices"
    __table_args__ = (UniqueConstraint("user_id", "hostname"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("orgs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    hostname: Mapped[str] = mapped_column(String(200))
    platform: Mapped[str] = mapped_column(String(60), default="")
    version: Mapped[str] = mapped_column(String(20), default="")
    # [{tool, label, found, sessions_7d, last_session_at}]
    tools: Mapped[list] = mapped_column(JSONB, default=list)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sessions_sent: Mapped[int] = mapped_column(Integer, default=0)


RLS_TABLES = [
    "users", "teams", "team_members", "resources", "lineage", "sops", "sop_steps", "projects", "tasks",
    "work_logs", "email_requests", "step_progress", "incidents", "feed_items", "reactions", "audit_log",
    "calendar_events", "day_plans", "notifications", "meetings", "standups", "agent_devices",
]

# Columns added after the first release; init_db adds them to existing databases.
ADDED_COLUMNS = [
    ("users", "share_wellbeing", "boolean DEFAULT false"),
    ("tasks", "started_at", "timestamptz"),
    ("tasks", "estimate_min", "integer"),
    ("tasks", "actual_min", "integer"),
    ("tasks", "expected_outcome", "text"),
    ("tasks", "outcome_by_ai", "boolean DEFAULT false"),
    ("tasks", "blockers", "jsonb DEFAULT '[]'::jsonb"),
]
