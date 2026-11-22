"""documents: source_name must be lowercase (file names are case-insensitive identities)

Revision ID: 0003_source_name_lowercase
Revises: 0002_document_source
Create Date: 2026-11-22

Ingestion stores source_name lowercased, so Shipping.md and shipping.md are the same
document (Windows treats them as the same file anyway). The CHECK makes the database
enforce that rule too, so the UNIQUE constraint really means "unique ignoring case".
"""
from alembic import op

revision = "0003_source_name_lowercase"
down_revision = "0002_document_source"
branch_labels = None
depends_on = None


def upgrade():
    op.create_check_constraint(
        "documents_source_name_lowercase", "documents", "source_name = lower(source_name)"
    )


def downgrade():
    op.drop_constraint("documents_source_name_lowercase", "documents", type_="check")
