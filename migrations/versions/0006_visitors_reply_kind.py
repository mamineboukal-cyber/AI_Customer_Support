"""visitors (anonymous browsers), conversations.visitor_id, messages.reply_kind

Revision ID: 0006_visitors_reply_kind
Revises: 0005_admin_inquiries
Create Date: 2026-11-28

visitors: one row per anonymous browser. The id is always created by the server
(gen_random_uuid()) and returned by POST /chat; the browser only stores and resends it.
One visitor has many conversations. conversations.visitor_id is nullable: rows from
before this revision have no visitor. ON DELETE SET NULL: forgetting a visitor keeps
its conversations, they just become anonymous again.

messages.reply_kind: what kind of reply an assistant message was, so statistics can
count by kind and day without comparing reply texts:
- normal:  an answer (also the admin's answer delivered later by app.rag.admin_answers)
- inquiry: the "we will check and come back to you" promise (an inquiry was recorded)
- handoff: handed to a human agent
- error:   the technical-problem message
NULL for user and system messages, required for assistant messages (both CHECKs).
Existing assistant rows are backfilled from their text: the two fixed server messages
below (as they are worded at this revision) become handoff and error, everything else
normal. Past inquiry promises cannot be told apart from answers and stay normal.

Downgrade drops visitors, visitor_id and reply_kind with their data; that cannot be undone.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_visitors_reply_kind"
down_revision = "0005_admin_inquiries"
branch_labels = None
depends_on = None

# Frozen copies of app.rag.answer.HANDOFF_MESSAGE / ERROR_MESSAGE at this revision:
# a migration must not change meaning when the app's texts change later.
HANDOFF_TEXT = "I don't know. Let me connect you to a human agent."
ERROR_TEXT = "Sorry, we are having a technical problem. Let me connect you to a human agent."


def upgrade():
    op.create_table(
        "visitors",
        sa.Column(
            "id", postgresql.UUID, server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="visitors_pkey"),
    )

    op.add_column("conversations", sa.Column("visitor_id", postgresql.UUID))
    op.create_foreign_key(
        "conversations_visitor_id_fkey",
        "conversations",
        "visitors",
        ["visitor_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # A visitor's conversations, and the SET NULL when a visitor is deleted.
    op.create_index("idx_conversations_visitor_id", "conversations", ["visitor_id"])

    op.add_column("messages", sa.Column("reply_kind", sa.String(20)))
    op.execute(
        sa.text(
            "UPDATE messages SET reply_kind = CASE "
            "WHEN content = :handoff THEN 'handoff' "
            "WHEN content = :error THEN 'error' "
            "ELSE 'normal' END "
            "WHERE role = 'assistant'"
        ).bindparams(handoff=HANDOFF_TEXT, error=ERROR_TEXT)
    )
    op.create_check_constraint(
        "messages_reply_kind_check",
        "messages",
        "reply_kind IN ('normal', 'inquiry', 'handoff', 'error')",
    )
    op.create_check_constraint(
        "messages_reply_kind_role_check",
        "messages",
        "(role = 'assistant') = (reply_kind IS NOT NULL)",
    )


def downgrade():
    # Dropping a column drops the CHECK constraints and indexes that use it.
    op.drop_column("messages", "reply_kind")
    op.drop_index("idx_conversations_visitor_id", table_name="conversations")
    op.drop_constraint("conversations_visitor_id_fkey", "conversations", type_="foreignkey")
    op.drop_column("conversations", "visitor_id")
    op.drop_table("visitors")
