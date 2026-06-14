"""Multi-tenant schema: organizations, projects, users, ingest keys."""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from replayd.tenancy import (
    DEFAULT_ORG_ID,
    DEFAULT_ORG_NAME,
    DEFAULT_ORG_SLUG,
    DEFAULT_PROJECT_ID,
    DEFAULT_PROJECT_NAME,
    DEFAULT_PROJECT_SLUG,
)

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEFAULT_CREATED_AT = "2026-06-13T00:00:00+00:00"


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )

    op.create_table(
        "projects",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "slug", name="uq_projects_org_id_slug"),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_users_email", "users", ["email"], unique=True)

    op.create_table(
        "memberships",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("org_id", sa.String(), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("org_id", "user_id", name="uq_memberships_org_id_user_id"),
    )
    op.create_index("idx_memberships_user_id", "memberships", ["user_id"], unique=False)

    op.create_table(
        "project_ingest_keys",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("project_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("key_prefix", sa.String(), nullable=False),
        sa.Column("key_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("last_used_at", sa.String(), nullable=True),
        sa.Column("revoked_at", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_project_ingest_keys_key_hash",
        "project_ingest_keys",
        ["key_hash"],
        unique=False,
    )
    op.create_index(
        "idx_project_ingest_keys_project_id",
        "project_ingest_keys",
        ["project_id"],
        unique=False,
    )

    with op.batch_alter_table("exchanges", schema=None) as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_exchanges_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
        )
        batch_op.create_index("idx_exchanges_project_id", ["project_id"], unique=False)

    with op.batch_alter_table("regression_tests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(), nullable=True))
        batch_op.create_foreign_key(
            "fk_regression_tests_project_id_projects",
            "projects",
            ["project_id"],
            ["id"],
        )
        batch_op.create_index(
            "idx_regression_tests_project_id",
            ["project_id"],
            unique=False,
        )

    organizations = sa.table(
        "organizations",
        sa.column("id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("created_at", sa.String()),
    )
    projects = sa.table(
        "projects",
        sa.column("id", sa.String()),
        sa.column("org_id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("created_at", sa.String()),
    )
    op.bulk_insert(
        organizations,
        [
            {
                "id": DEFAULT_ORG_ID,
                "name": DEFAULT_ORG_NAME,
                "slug": DEFAULT_ORG_SLUG,
                "created_at": _DEFAULT_CREATED_AT,
            }
        ],
    )
    op.bulk_insert(
        projects,
        [
            {
                "id": DEFAULT_PROJECT_ID,
                "org_id": DEFAULT_ORG_ID,
                "name": DEFAULT_PROJECT_NAME,
                "slug": DEFAULT_PROJECT_SLUG,
                "created_at": _DEFAULT_CREATED_AT,
            }
        ],
    )

    op.execute(
        sa.text(
            "UPDATE exchanges SET project_id = :project_id WHERE project_id IS NULL"
        ).bindparams(project_id=DEFAULT_PROJECT_ID)
    )
    op.execute(
        sa.text(
            "UPDATE regression_tests SET project_id = :project_id "
            "WHERE project_id IS NULL"
        ).bindparams(project_id=DEFAULT_PROJECT_ID)
    )


def downgrade() -> None:
    with op.batch_alter_table("regression_tests", schema=None) as batch_op:
        batch_op.drop_index("idx_regression_tests_project_id")
        batch_op.drop_constraint(
            "fk_regression_tests_project_id_projects",
            type_="foreignkey",
        )
        batch_op.drop_column("project_id")

    with op.batch_alter_table("exchanges", schema=None) as batch_op:
        batch_op.drop_index("idx_exchanges_project_id")
        batch_op.drop_constraint("fk_exchanges_project_id_projects", type_="foreignkey")
        batch_op.drop_column("project_id")

    op.drop_index("idx_project_ingest_keys_project_id", table_name="project_ingest_keys")
    op.drop_index("idx_project_ingest_keys_key_hash", table_name="project_ingest_keys")
    op.drop_table("project_ingest_keys")
    op.drop_index("idx_memberships_user_id", table_name="memberships")
    op.drop_table("memberships")
    op.drop_index("idx_users_email", table_name="users")
    op.drop_table("users")
    op.drop_table("projects")
    op.drop_table("organizations")
