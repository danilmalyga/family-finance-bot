"""add groceries weekly budget settings

Revision ID: 0002_groceries_weekly_budget
Revises: 0001_initial
Create Date: 2026-07-12
"""

from alembic import op

revision = "0002_groceries_weekly_budget"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE monthly_budgets
        ADD COLUMN IF NOT EXISTS groceries_weekly_limit NUMERIC(14, 2) NOT NULL DEFAULT 0
        """
    )
    op.execute(
        """
        ALTER TABLE monthly_budgets
        ADD COLUMN IF NOT EXISTS groceries_week_start_weekday INTEGER NOT NULL DEFAULT 1
        """
    )
    op.execute("ALTER TABLE monthly_budgets ALTER COLUMN groceries_weekly_limit DROP DEFAULT")
    op.execute("ALTER TABLE monthly_budgets ALTER COLUMN groceries_week_start_weekday DROP DEFAULT")


def downgrade() -> None:
    op.drop_column("monthly_budgets", "groceries_week_start_weekday")
    op.drop_column("monthly_budgets", "groceries_weekly_limit")
