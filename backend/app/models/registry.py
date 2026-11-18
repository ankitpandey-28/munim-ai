"""Imports every module's models so ``Base.metadata`` is complete.

Used by Alembic (env.py) and at application start-up (mapper configuration). Kept separate
from ``app.models`` to avoid import cycles (module models import ``app.models.base``).
"""

from app.models.base import Base


def import_all_models() -> type[Base]:
    from app.modules.approvals import models as _approvals  # noqa: F401
    from app.modules.audit import models as _audit  # noqa: F401
    from app.modules.catalog import models as _catalog  # noqa: F401
    from app.modules.credit import models as _credit  # noqa: F401
    from app.modules.customers import models as _customers  # noqa: F401
    from app.modules.expenses import models as _expenses  # noqa: F401
    from app.modules.identity import models as _identity  # noqa: F401
    from app.modules.inventory import models as _inventory  # noqa: F401
    from app.modules.ledger import models as _ledger  # noqa: F401
    from app.modules.notifications import models as _notifications  # noqa: F401
    from app.modules.platform import models as _platform  # noqa: F401
    from app.modules.purchasing import models as _purchasing  # noqa: F401
    from app.modules.sales import models as _sales  # noqa: F401
    from app.modules.shops import models as _shops  # noqa: F401
    from app.modules.suppliers import models as _suppliers  # noqa: F401
    from app.modules.voice import models as _voice  # noqa: F401

    return Base


# Tables that carry shop_id NOT NULL and get the standard tenant RLS policy.
# shops, shop_members, audit_logs and idempotency_keys have special policies; users,
# auth_sessions, login_attempts, units and jobs are global (no RLS).
STANDARD_TENANT_TABLES: tuple[str, ...] = (
    "shop_settings",
    "product_categories",
    "products",
    "product_aliases",
    "product_prices",
    "inventory_levels",
    "stock_movements",
    "stock_counts",
    "stock_count_items",
    "customers",
    "customer_aliases",
    "business_transactions",
    "sales",
    "sale_items",
    "credit_entries",
    "payments",
    "payment_allocations",
    "approval_requests",
    "expense_categories",
    "expenses",
    "suppliers",
    "supplier_products",
    "purchase_orders",
    "purchase_order_items",
    "goods_receipts",
    "goods_receipt_items",
    "voice_sessions",
    "voice_commands",
    "pending_actions",
    "reminders",
    "notifications",
)
SPECIAL_RLS_TABLES: tuple[str, ...] = ("shops", "shop_members", "audit_logs", "idempotency_keys")
GLOBAL_TABLES: tuple[str, ...] = ("users", "auth_sessions", "login_attempts", "units", "jobs")
