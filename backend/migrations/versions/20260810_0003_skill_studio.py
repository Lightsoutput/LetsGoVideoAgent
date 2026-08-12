"""add Skill Studio tables

Revision ID: 20260810_0003
Revises: 20260809_0002
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0003"
down_revision: str | None = "20260809_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "skills",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=63), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("active_version", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_skills_status", "skills", ["status"])

    op.create_table(
        "skill_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_skill_versions_status", "skill_versions", ["status"])
    op.create_index("ix_skill_versions_trace_id", "skill_versions", ["trace_id"])
    op.create_index(
        "ix_skill_versions_skill_version",
        "skill_versions",
        ["skill_id", "version"],
        unique=True,
    )

    op.create_table(
        "skill_bindings",
        sa.Column("video_id", sa.String(length=36), nullable=False),
        sa.Column("skill_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["video_id"], ["videos.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skills.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("video_id"),
    )
    op.create_index("ix_skill_bindings_skill_id", "skill_bindings", ["skill_id"])


def downgrade() -> None:
    op.drop_table("skill_bindings")
    op.drop_table("skill_versions")
    op.drop_table("skills")
