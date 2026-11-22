"""initial schema, recreated from sql/schema.sql

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-22
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

EMBEDDING_DIM = 384  # BAAI/bge-small-en-v1.5


def _timestamp(name, nullable=False):
    return sa.Column(
        name,
        sa.TIMESTAMP(timezone=True),
        server_default=None if nullable else sa.text("now()"),
        nullable=nullable,
    )


def upgrade():
    # 1. The extension comes first: Postgres must know the `vector` type before
    #    document_chunks.embedding can be declared with it.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Not indented: Postgres stores a function body verbatim.
    op.execute(
        """CREATE FUNCTION set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$"""
    )

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer, sa.Identity(always=False), primary_key=True),
        sa.Column("title", sa.String(50), nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("content", sa.Text, server_default=sa.text("''"), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name="documents_pkey"),
    )

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("document_id", sa.Integer, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("chunk_index", sa.Integer),
        _timestamp("created_at"),
        # pgvector.sqlalchemy.Vector is a UserDefinedType that renders VECTOR(384).
        sa.Column("embedding", Vector(EMBEDDING_DIM)),
        sa.PrimaryKeyConstraint("id", name="document_chunks_pkey"),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="document_chunks_document_id_fkey"
        ),
    )
    op.create_index("idx_document_chunks_document_id", "document_chunks", ["document_id"])

    op.create_table(
        "conversations",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        _timestamp("started_at"),
        _timestamp("ended_at", nullable=True),
        sa.PrimaryKeyConstraint("id", name="conversations_pkey"),
        sa.UniqueConstraint("session_id", name="conversations_session_id_key"),
        sa.CheckConstraint(
            "ended_at IS NULL OR ended_at >= started_at", name="conversations_check"
        ),
        sa.CheckConstraint(
            "status <> 'closed' OR ended_at IS NOT NULL", name="conversations_check1"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'closed')", name="conversations_status_check"
        ),
    )
    op.create_index("idx_conversations_status", "conversations", ["status"])

    op.create_table(
        "messages",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("conversation_id", sa.BigInteger, nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        _timestamp("created_at"),
        sa.PrimaryKeyConstraint("id", name="messages_pkey"),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="messages_conversation_id_fkey",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')", name="messages_role_check"
        ),
    )
    op.create_index(
        "idx_messages_conversation_created", "messages", ["conversation_id", "created_at"]
    )

    op.create_table(
        "unanswered_questions",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("normalized_question", sa.Text, nullable=False),
        sa.Column("frequency", sa.Integer, server_default=sa.text("1"), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("approved_answer", sa.Text),
        _timestamp("reviewed_at", nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.PrimaryKeyConstraint("id", name="unanswered_questions_pkey"),
        sa.CheckConstraint(
            "status <> 'resolved' OR approved_answer IS NOT NULL",
            name="unanswered_questions_check",
        ),
        sa.CheckConstraint("frequency >= 1", name="unanswered_questions_frequency_check"),
        sa.CheckConstraint(
            "status IN ('pending', 'reviewed', 'resolved', 'ignored')",
            name="unanswered_questions_status_check",
        ),
    )
    op.create_index(
        "idx_unanswered_questions_normalized",
        "unanswered_questions",
        ["normalized_question"],
        unique=True,
    )
    op.create_index("idx_unanswered_questions_status", "unanswered_questions", ["status"])

    for table in ("documents", "unanswered_questions"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
        )


def downgrade():
    # Dropping a table drops its indexes, constraints and triggers with it.
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("unanswered_questions")
    op.drop_table("document_chunks")
    op.drop_table("documents")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.execute("DROP EXTENSION IF EXISTS vector")
