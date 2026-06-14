"""SQLAlchemy schema for the replayd relational index."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, MetaData, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

metadata = MetaData()


class Base(DeclarativeBase):
    metadata = metadata


class OrganizationRow(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class ProjectRow(Base):
    __tablename__ = "projects"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_projects_org_id_slug"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("organizations.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (Index("idx_users_email", "email", unique=True),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    email: Mapped[str] = mapped_column(String, nullable=False)
    subject: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class MembershipRow(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("org_id", "user_id", name="uq_memberships_org_id_user_id"),
        Index("idx_memberships_user_id", "user_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("organizations.id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)


class InvitationRow(Base):
    __tablename__ = "invitations"
    __table_args__ = (Index("idx_invitations_email_status", "email", "status"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    org_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("organizations.id"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    token: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    invited_by_user_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id"),
        nullable=False,
    )
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    accepted_at: Mapped[str | None] = mapped_column(String, nullable=True)
    expires_at: Mapped[str] = mapped_column(String, nullable=False)


class ProjectIngestKeyRow(Base):
    __tablename__ = "project_ingest_keys"
    __table_args__ = (
        Index("idx_project_ingest_keys_key_hash", "key_hash"),
        Index("idx_project_ingest_keys_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("projects.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    key_prefix: Mapped[str] = mapped_column(String, nullable=False)
    key_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    last_used_at: Mapped[str | None] = mapped_column(String, nullable=True)
    revoked_at: Mapped[str | None] = mapped_column(String, nullable=True)


class ExchangeRow(Base):
    __tablename__ = "exchanges"
    __table_args__ = (
        Index("idx_exchanges_created_at", "created_at"),
        Index("idx_exchanges_run_id", "run_id"),
        Index("idx_exchanges_project_id", "project_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("projects.id"),
        nullable=True,
    )
    run_id: Mapped[str] = mapped_column(String, nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    origin: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    ended_at: Mapped[str] = mapped_column(String, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[str] = mapped_column(String, nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    query: Mapped[str | None] = mapped_column(String, nullable=True)
    request_headers: Mapped[str] = mapped_column(Text, nullable=False)
    request_body_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_headers: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    usage: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str | None] = mapped_column(String, nullable=True)
    response_body_hash: Mapped[str | None] = mapped_column(String, nullable=True)


class RegressionTestRow(Base):
    __tablename__ = "regression_tests"
    __table_args__ = (Index("idx_regression_tests_project_id", "project_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(
        String,
        ForeignKey("projects.id"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    baseline_run_id: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    mode: Mapped[str] = mapped_column(String, nullable=False, server_default="exact")


class TestResultRow(Base):
    __tablename__ = "test_results"
    __table_args__ = (
        Index("idx_test_results_test_id_run_at", "test_id", "run_at"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    test_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("regression_tests.id"),
        nullable=False,
    )
    run_at: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    matched_steps: Mapped[int] = mapped_column(Integer, nullable=False)
    first_divergent_step_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    candidate_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    step_diffs: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
