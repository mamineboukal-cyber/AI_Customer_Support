"""documents: source_name is the lowercased file name WITHOUT extension

Revision ID: 0004_source_name_stem
Revises: 0003_source_name_lowercase
Create Date: 2026-11-22

A document is identified by its stem, so shipping.pdf later updates shipping.md
instead of becoming a duplicate. Existing rows lose their extension. If two rows
would end up with the same stem, the migration stops with their names, and nothing
is changed: decide which one to keep first.

Downgrade changes nothing: the removed extensions cannot be recovered, and the
constraints from 0002/0003 accept stems as they are.
"""
from alembic import context, op
import sqlalchemy as sa

revision = "0004_source_name_stem"
down_revision = "0003_source_name_lowercase"
branch_labels = None
depends_on = None

# Same rule as pathlib's Path.stem: drop the last ".something".
STEM = r"regexp_replace(source_name, '\.[^.]*$', '')"


def upgrade():
    if not context.is_offline_mode():
        clashes = op.get_bind().execute(
            sa.text(
                f"SELECT {STEM}, string_agg(source_name, ', ' ORDER BY source_name) "
                "FROM documents GROUP BY 1 HAVING count(*) > 1"
            )
        ).fetchall()
        if clashes:
            detail = "; ".join(f"{stem}: {names}" for stem, names in clashes)
            raise RuntimeError(f"documents would merge into one source_name ({detail})")
    op.execute(f"UPDATE documents SET source_name = {STEM}")


def downgrade():
    pass
