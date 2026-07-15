"""add purchase advisor persona

Revision ID: 0003_purchase_advisor_persona
Revises: 0002_groceries_weekly_budget
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_purchase_advisor_persona"
down_revision = "0002_groceries_weekly_budget"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "families",
        sa.Column(
            "purchase_advisor_persona",
            sa.String(length=64),
            nullable=False,
            server_default="future_self",
        ),
    )
    op.alter_column("families", "purchase_advisor_persona", server_default=None)


def downgrade() -> None:
    op.drop_column("families", "purchase_advisor_persona")
