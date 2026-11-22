"""documents: source_name (unique) and content_hash for per-file ingestion

Revision ID: 0002_document_source
Revises: 0001_initial
Create Date: 2026-11-22

source_name is the ingested file's name and identifies the document (same name =
update). content_hash is the sha256 hex digest of its text (same hash = skip).
Both are NOT NULL: on a table that already has rows this migration would fail and
need a backfill step; the new database starts empty, so none is written here.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_document_source"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("documents", sa.Column("source_name", sa.Text, nullable=False))
    op.add_column("documents", sa.Column("content_hash", sa.CHAR(64), nullable=False))
    op.create_unique_constraint("documents_source_name_key", "documents", ["source_name"])


def downgrade():
    op.drop_constraint("documents_source_name_key", "documents", type_="unique")
    op.drop_column("documents", "content_hash")
    op.drop_column("documents", "source_name")
