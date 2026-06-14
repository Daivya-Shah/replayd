"""Team invitations for organization membership."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("token", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("invited_by_user_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("accepted_at", sa.String(), nullable=True),
        sa.Column("expires_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_invitations_email_status",
        "invitations",
        ["email", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_invitations_email_status", table_name="invitations")
    op.drop_table("invitations")
