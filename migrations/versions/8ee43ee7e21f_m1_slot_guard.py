"""m1 slot guard

Revision ID: 8ee43ee7e21f
Revises: 
Create Date: 2025-11-05 10:41:37.107128

"""
from pathlib import Path
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '8ee43ee7e21f'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    project_root = Path(__file__).resolve().parents[2]
    sql_dir = project_root / "sql"

    for filename in ("001_extensions.sql", "010_schema.sql", "030_commit_reservation.sql"):
        op.execute((sql_dir / filename).read_text())


def downgrade() -> None:
    op.execute(
        """
        DROP FUNCTION IF EXISTS commit_reservation(
          uuid, text, integer, timestamptz, timestamptz,
          text, text, text, text
        );
        """
    )
    op.drop_table("event_log", schema="public")
    op.drop_table("reservation", schema="public")
    op.drop_table("capacity_rule", schema="public")
    op.drop_table("blackout", schema="public")
    op.drop_table("hours_rule", schema="public")
    op.drop_table("restaurant", schema="public")
    op.execute("DROP EXTENSION IF EXISTS pg_stat_statements;")
    op.execute("DROP EXTENSION IF EXISTS btree_gist;")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto;")
