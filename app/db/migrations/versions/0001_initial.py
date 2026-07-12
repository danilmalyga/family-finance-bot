"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-12
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    uuid = postgresql.UUID(as_uuid=True)
    jsonb = postgresql.JSONB(astext_type=sa.Text())
    op.create_table(
        "families",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        *timestamps(),
    )
    op.create_table(
        "users",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=False),
        sa.Column("family_id", uuid, sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("telegram_user_id", name="uq_users_telegram_user_id"),
    )
    op.create_table(
        "categories",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("family_id", uuid, sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("parent_id", uuid, sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("monthly_limit", sa.Numeric(14, 2)),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("family_id", "code", name="uq_categories_family_code"),
    )
    op.create_table(
        "receipts",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("family_id", uuid, sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("telegram_file_id", sa.String(255), nullable=False),
        sa.Column("telegram_file_unique_id", sa.String(255), nullable=False),
        sa.Column("file_hash", sa.String(128), nullable=False),
        sa.Column("raw_ocr_text", sa.Text(), nullable=False),
        sa.Column("parsed_json", jsonb, nullable=False),
        sa.Column("merchant", sa.String(255)),
        sa.Column("receipt_date", sa.Date()),
        sa.Column("total", sa.Numeric(14, 2)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("telegram_file_unique_id", name="uq_receipts_file_unique_id"),
        sa.UniqueConstraint("file_hash", name="uq_receipts_file_hash"),
    )
    op.create_table(
        "transactions",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("family_id", uuid, sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", uuid, sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("merchant", sa.String(255)),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("receipt_id", uuid, sa.ForeignKey("receipts.id", ondelete="SET NULL")),
        sa.Column("external_hash", sa.String(128)),
        sa.Column("ai_confidence", sa.Numeric(4, 3)),
        *timestamps(),
    )
    op.create_index("ix_transactions_external_hash", "transactions", ["external_hash"])
    op.create_table(
        "transaction_items",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("transaction_id", uuid, sa.ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("quantity", sa.Numeric(14, 3), nullable=False),
        sa.Column("unit_price", sa.Numeric(14, 2)),
        sa.Column("total_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("category_id", uuid, sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "monthly_budgets",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("family_id", uuid, sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("planned_income", sa.Numeric(14, 2), nullable=False),
        sa.Column("savings_target", sa.Numeric(14, 2), nullable=False),
        sa.Column("minimum_reserve", sa.Numeric(14, 2), nullable=False),
        sa.Column("salary_day", sa.Integer()),
        sa.Column("groceries_weekly_limit", sa.Numeric(14, 2), nullable=False),
        sa.Column("groceries_week_start_weekday", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        *timestamps(),
        sa.UniqueConstraint("family_id", "year", "month", name="uq_budget_family_month"),
    )
    op.create_table(
        "recurring_payments",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("family_id", uuid, sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("category_id", uuid, sa.ForeignKey("categories.id", ondelete="SET NULL")),
        sa.Column("payment_day", sa.Integer()),
        sa.Column("frequency", sa.String(32), nullable=False),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("next_payment_date", sa.Date()),
        *timestamps(),
    )
    op.create_table(
        "financial_goals",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("family_id", uuid, sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("target_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("current_amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("target_date", sa.Date()),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *timestamps(),
    )
    op.create_table(
        "wishlist_items",
        sa.Column("id", uuid, primary_key=True),
        sa.Column("family_id", uuid, sa.ForeignKey("families.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", uuid, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("price", sa.Numeric(14, 2), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("desired_date", sa.Date()),
        sa.Column("recommended_purchase_date", sa.Date()),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("decision_snapshot", jsonb),
        *timestamps(),
    )


def downgrade() -> None:
    for table in [
        "wishlist_items",
        "financial_goals",
        "recurring_payments",
        "monthly_budgets",
        "transaction_items",
        "transactions",
        "receipts",
        "categories",
        "users",
        "families",
    ]:
        op.drop_table(table)
