"""Baseline relational schema for replayd.

Revision ID: 0001
Revises:
Create Date: 2026-06-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "exchanges",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("parent_run_id", sa.String(), nullable=True),
        sa.Column("origin", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("started_at", sa.String(), nullable=False),
        sa.Column("ended_at", sa.String(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("method", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("query", sa.String(), nullable=True),
        sa.Column("request_headers", sa.Text(), nullable=False),
        sa.Column("request_body_hash", sa.String(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=False),
        sa.Column("response_headers", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("usage", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(), nullable=True),
        sa.Column("response_body_hash", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_exchanges_created_at", "exchanges", ["created_at"], unique=False)
    op.create_index("idx_exchanges_run_id", "exchanges", ["run_id"], unique=False)

    op.create_table(
        "regression_tests",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("baseline_run_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("mode", sa.String(), server_default="exact", nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "test_results",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("test_id", sa.String(), nullable=False),
        sa.Column("run_at", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("total_steps", sa.Integer(), nullable=False),
        sa.Column("matched_steps", sa.Integer(), nullable=False),
        sa.Column("first_divergent_step_index", sa.Integer(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("candidate_run_id", sa.String(), nullable=True),
        sa.Column("step_diffs", sa.Text(), server_default="[]", nullable=False),
        sa.ForeignKeyConstraint(["test_id"], ["regression_tests.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_test_results_test_id_run_at",
        "test_results",
        ["test_id", "run_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_test_results_test_id_run_at", table_name="test_results")
    op.drop_table("test_results")
    op.drop_table("regression_tests")
    op.drop_index("idx_exchanges_run_id", table_name="exchanges")
    op.drop_index("idx_exchanges_created_at", table_name="exchanges")
    op.drop_table("exchanges")
