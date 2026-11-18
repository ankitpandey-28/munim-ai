"""seed units: global unit-of-measure reference data (SRS FR-PROD-03).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-19

Inserts 8 rows into ``units`` (global, no RLS). Idempotent (ON CONFLICT DO NOTHING).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UNITS = (
    # code, dimension, factor to dimension base, allows_decimal, english, hindi, spoken forms
    ("kg", "mass", "1", True, "Kilogram", "किलो", ["kg", "kilo", "kila", "kilogram", "किलो"]),
    ("g", "mass", "0.001", True, "Gram", "ग्राम", ["g", "gm", "gram", "graam", "ग्राम"]),
    ("l", "volume", "1", True, "Litre", "लीटर", ["l", "ltr", "litre", "liter", "लीटर"]),
    ("ml", "volume", "0.001", True, "Millilitre", "मिलीलीटर", ["ml", "millilitre", "मिली"]),
    ("piece", "count", "1", False, "Piece", "पीस", ["piece", "pc", "pcs", "nag", "पीस", "नग"]),
    ("packet", "count", "1", False, "Packet", "पैकेट", ["packet", "pkt", "pack", "पैकेट"]),
    ("dozen", "count", "12", False, "Dozen", "दर्जन", ["dozen", "darjan", "दर्जन"]),
    ("box", "count", "1", False, "Box", "डिब्बा", ["box", "dabba", "dibba", "डिब्बा"]),
)


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    rows = []
    for code, dim, factor, decimal, en, hi, spoken in UNITS:
        spoken_sql = "ARRAY[" + ", ".join(_literal(s) for s in spoken) + "]::text[]"
        rows.append(
            f"({_literal(code)}, {_literal(dim)}, {factor}, {'true' if decimal else 'false'}, "
            f"{_literal(en)}, {_literal(hi)}, {spoken_sql})"
        )
    op.execute(
        "INSERT INTO units (code, dimension, factor_to_dimension_base, allows_decimal, name_en, "
        "name_hi, spoken_forms) VALUES " + ", ".join(rows) + " ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    codes = ", ".join(_literal(u[0]) for u in UNITS)
    op.execute(f"DELETE FROM units WHERE code IN ({codes})")
