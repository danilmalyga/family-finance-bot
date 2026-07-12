"""add groceries weekly budget settings

Revision ID: 0002_groceries_weekly_budget
Revises: 0001_initial
Create Date: 2026-07-12
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_groceries_weekly_budget"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monthly_budgets",
        sa.Column(
            "groceries_weekly_limit",
            sa.Numeric(14, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "monthly_budgets",
        sa.Column(
            "groceries_week_start_weekday",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )
    op.alter_column("monthly_budgets", "groceries_weekly_limit", server_default=None)
    op.alter_column("monthly_budgets", "groceries_week_start_weekday", server_default=None)


def downgrade() -> None:
    op.drop_column("monthly_budgets", "groceries_week_start_weekday")
    op.drop_column("monthly_budgets", "groceries_weekly_limit")
