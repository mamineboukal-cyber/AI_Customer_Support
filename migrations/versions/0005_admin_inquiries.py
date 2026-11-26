"""admin_inquiries (a conversation waiting for an admin's answer) and conversations.phone_number

Revision ID: 0005_admin_inquiries
Revises: 0004_source_name_stem
Create Date: 2026-11-26

unanswered_questions stays the ledger: one row per distinct normalized question, with
its frequency and approved_answer. admin_inquiries records each conversation that is
waiting for one of those questions to be answered: waiting -> answered (the admin's raw
answer, not the approved one) -> delivered (sent back to the customer).

ON DELETE:
- conversation_id CASCADE: without the conversation there is nobody to deliver to, and
  messages already cascade the same way. Deleting a conversation erases the customer's
  data; the question and its frequency stay in the ledger.
- unanswered_question_id RESTRICT: a ledger row cannot be deleted while customers are
  waiting on it; their inquiries must be resolved or moved to another row first.

conversations.phone_number holds the customer's WhatsApp number (personal data). It is
not unique: one customer can have several conversations.

Downgrade drops admin_inquiries and phone_number with their data; that cannot be undone.
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_admin_inquiries"
down_revision = "0004_source_name_stem"
branch_labels = None
depends_on = None


def _timestamp(name, nullable=False):
    return sa.Column(
        name,
        sa.TIMESTAMP(timezone=True),
        server_default=None if nullable else sa.text("now()"),
        nullable=nullable,
    )


def upgrade():
    op.add_column("conversations", sa.Column("phone_number", sa.Text))
    op.create_index("idx_conversations_phone_number", "conversations", ["phone_number"])

    op.create_table(
        "admin_inquiries",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("unanswered_question_id", sa.BigInteger, nullable=False),
        sa.Column("conversation_id", sa.BigInteger, nullable=False),
        sa.Column("status", sa.String(20), server_default="waiting", nullable=False),
        sa.Column("admin_answer", sa.Text),
        _timestamp("answered_at", nullable=True),
        _timestamp("delivered_at", nullable=True),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("id", name="admin_inquiries_pkey"),
        sa.ForeignKeyConstraint(
            ["unanswered_question_id"],
            ["unanswered_questions.id"],
            name="admin_inquiries_unanswered_question_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="admin_inquiries_conversation_id_fkey",
            ondelete="CASCADE",
        ),
        # The same conversation cannot wait twice for the same question.
        sa.UniqueConstraint(
            "unanswered_question_id",
            "conversation_id",
            name="admin_inquiries_question_conversation_key",
        ),
        sa.CheckConstraint(
            "status IN ('waiting', 'answered', 'delivered')",
            name="admin_inquiries_status_check",
        ),
        sa.CheckConstraint(
            "status = 'waiting' OR (admin_answer IS NOT NULL AND answered_at IS NOT NULL)",
            name="admin_inquiries_answered_check",
        ),
        sa.CheckConstraint(
            "status <> 'delivered' OR delivered_at IS NOT NULL",
            name="admin_inquiries_delivered_check",
        ),
    )
    op.create_index("idx_admin_inquiries_status", "admin_inquiries", ["status"])
    # The unique constraint covers lookups by question; this one covers the CASCADE from
    # conversations and "anything to deliver to this conversation?".
    op.create_index(
        "idx_admin_inquiries_conversation_id", "admin_inquiries", ["conversation_id"]
    )


def downgrade():
    # Dropping the table drops its indexes and constraints with it.
    op.drop_table("admin_inquiries")
    op.drop_index("idx_conversations_phone_number", table_name="conversations")
    op.drop_column("conversations", "phone_number")
