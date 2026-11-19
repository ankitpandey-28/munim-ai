"""product track_stock flag (decision D-08 / Q-22).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-19

Adds ``products.track_stock BOOLEAN NOT NULL DEFAULT true`` and lets the application role
update it. Backward compatible and non-destructive:
- PostgreSQL 11+ stores a constant default in the catalog, so existing rows are not rewritten
  and every existing product keeps today's behaviour (stock tracked).
- Older application code that does not know the column keeps working (it is never required
  on insert thanks to the default).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "munim_app"


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("track_stock", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.execute(f"GRANT UPDATE (track_stock) ON products TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE UPDATE (track_stock) ON products FROM {APP_ROLE}")
    op.drop_column("products", "track_stock")
