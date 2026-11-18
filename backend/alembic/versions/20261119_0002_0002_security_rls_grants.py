"""security: tenant context functions, row-level security, least-privilege grants, immutability.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-19

What this migration does (docs/physical-schema.md §Security):

1. Context functions ``app_current_shop_id()`` / ``app_current_user_id()`` read the
   transaction-local settings ``app.current_shop_id`` / ``app.current_user_id``. Missing or empty
   settings yield NULL, so every policy comparison is false: access FAILS CLOSED.
2. ENABLE + FORCE ROW LEVEL SECURITY on every tenant table (FORCE also binds the table owner).
   Standard policy: ``shop_id = app_current_shop_id()`` for USING and WITH CHECK.
   Special policies: shops, shop_members (members may see their own memberships),
   audit_logs (insert-only for shop-less events), idempotency_keys (per user).
3. Grants for the runtime role ``munim_app``: SELECT/INSERT and column-scoped UPDATE only.
   No DELETE on financial or audit tables; no TRUNCATE/REFERENCES/TRIGGER anywhere; no CREATE.
4. Triggers that reject DELETE and any change to immutable columns of append-only tables
   (defence in depth: they also bind the owner role).

Nothing here drops or rewrites data.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "munim_app"

STANDARD_TENANT_TABLES = (
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
SPECIAL_RLS_TABLES = ("shops", "shop_members", "audit_logs", "idempotency_keys")

# table -> (privileges, update_columns or None, allow_delete)
# Append-only tables list only their status/link/cache columns as updatable.
GRANTS: dict[str, tuple[tuple[str, ...], tuple[str, ...], bool]] = {
    # ---- global identity / infrastructure
    "users": (
        ("SELECT", "INSERT"),
        (
            "name",
            "preferred_language",
            "password_hash",
            "password_changed_at",
            "must_change_password",
            "failed_login_count",
            "locked_until",
            "last_active_shop_id",
            "last_login_at",
            "updated_at",
        ),
        False,
    ),
    "auth_sessions": (
        ("SELECT", "INSERT"),
        ("active_shop_id", "last_seen_at", "revoked_at", "revoke_reason"),
        True,
    ),
    "login_attempts": (("SELECT", "INSERT"), (), True),
    "units": (("SELECT",), (), False),
    "jobs": (
        ("SELECT", "INSERT"),
        ("status", "attempts", "run_after", "locked_at", "locked_by", "last_error", "updated_at"),
        False,
    ),
    "idempotency_keys": (
        ("SELECT", "INSERT"),
        ("response_status", "response_body", "transaction_id", "completed_at"),
        False,
    ),
    "audit_logs": (("SELECT", "INSERT"), (), False),
    # ---- shops
    "shops": (
        ("SELECT", "INSERT"),
        (
            "name",
            "business_type",
            "address",
            "city",
            "state",
            "pincode",
            "timezone",
            "default_language",
            "version",
            "updated_at",
        ),
        False,
    ),
    "shop_members": (
        ("SELECT", "INSERT"),
        (
            "role",
            "credit_limit_paise",
            "permission_overrides",
            "status",
            "removed_at",
            "updated_at",
        ),
        False,
    ),
    "shop_settings": (("SELECT", "INSERT"), ("settings", "version", "updated_at"), False),
    # ---- master data (archive, never delete; alias/link rows may be deleted)
    "product_categories": (
        ("SELECT", "INSERT"),
        ("name", "name_hi", "sort_order", "archived_at", "updated_at"),
        False,
    ),
    "products": (
        ("SELECT", "INSERT"),
        (
            "name",
            "name_hi",
            "category_id",
            "base_unit_code",
            "is_loose",
            "selling_price_paise",
            "default_cost_price_paise",
            "reorder_level",
            "barcode",
            "archived_at",
            "version",
            "updated_at",
        ),
        False,
    ),
    "product_aliases": (
        ("SELECT", "INSERT"),
        ("alias_text", "normalized_text", "phonetic_key", "language", "source"),
        True,
    ),
    "product_prices": (("SELECT", "INSERT"), (), False),
    "customers": (
        ("SELECT", "INSERT"),
        (
            "name",
            "name_normalized",
            "phonetic_key",
            "phone",
            "landmark",
            "address",
            "notes",
            "reminder_consent",
            "consent_at",
            "consent_source",
            "credit_limit_paise",
            "balance_paise",
            "oldest_open_credit_date",
            "archived_at",
            "version",
            "updated_at",
        ),
        False,
    ),
    "customer_aliases": (
        ("SELECT", "INSERT"),
        ("alias_text", "normalized_text", "phonetic_key"),
        True,
    ),
    "expense_categories": (
        ("SELECT", "INSERT"),
        ("name", "name_hi", "kind", "archived_at", "updated_at"),
        False,
    ),
    "suppliers": (
        ("SELECT", "INSERT"),
        ("name", "contact_person", "phone", "address", "notes", "archived_at", "updated_at"),
        False,
    ),
    "supplier_products": (
        ("SELECT", "INSERT"),
        ("is_preferred", "last_cost_paise", "pack_size", "pack_unit_code", "updated_at"),
        True,
    ),
    # ---- inventory
    "inventory_levels": (
        ("SELECT", "INSERT"),
        ("quantity_on_hand", "avg_cost_paise", "last_movement_id", "updated_at"),
        False,
    ),
    "stock_movements": (("SELECT", "INSERT"), (), False),
    "stock_counts": (
        ("SELECT", "INSERT"),
        ("status", "posted_transaction_id", "notes", "posted_at", "updated_at"),
        False,
    ),
    "stock_count_items": (
        ("SELECT", "INSERT"),
        ("counted_quantity", "difference", "reason"),
        False,
    ),
    # ---- ledger and financial records (append-only)
    "business_transactions": (
        ("SELECT", "INSERT"),
        ("status", "reversed_by_transaction_id"),
        False,
    ),
    "sales": (("SELECT", "INSERT"), ("status", "updated_at"), False),
    "sale_items": (("SELECT", "INSERT"), (), False),
    "credit_entries": (("SELECT", "INSERT"), ("settled_paise", "is_open"), False),
    "payments": (("SELECT", "INSERT"), ("allocated_paise", "unallocated_paise"), False),
    "payment_allocations": (("SELECT", "INSERT"), (), False),
    "expenses": (("SELECT", "INSERT"), ("status", "updated_at"), False),
    "goods_receipts": (("SELECT", "INSERT"), (), False),
    "goods_receipt_items": (("SELECT", "INSERT"), (), False),
    # ---- purchasing
    "purchase_orders": (
        ("SELECT", "INSERT"),
        (
            "supplier_id",
            "status",
            "expected_date",
            "notes",
            "estimated_total_paise",
            "sent_at",
            "version",
            "updated_at",
        ),
        False,
    ),
    "purchase_order_items": (
        ("SELECT", "INSERT"),
        ("ordered_quantity", "unit_code", "expected_unit_cost_paise", "received_quantity"),
        False,
    ),
    # ---- approvals / voice / notifications (request content immutable; only state changes)
    "approval_requests": (
        ("SELECT", "INSERT"),
        (
            "status",
            "decided_by_user_id",
            "decided_at",
            "decision_note",
            "resulting_transaction_id",
            "updated_at",
        ),
        False,
    ),
    "voice_sessions": (
        ("SELECT", "INSERT"),
        ("last_activity_at", "ended_at", "language", "active_pending_action_id"),
        False,
    ),
    "voice_commands": (("SELECT", "INSERT"), ("transcript", "transcript_redacted_at"), False),
    "pending_actions": (
        ("SELECT", "INSERT"),
        (
            "status",
            "confirmed_at",
            "confirmation_method",
            "approval_request_id",
            "executed_transaction_id",
            "failure_reason",
            "updated_at",
        ),
        False,
    ),
    "reminders": (("SELECT", "INSERT"), ("status", "opened_at", "marked_sent_at"), False),
    "notifications": (("SELECT", "INSERT"), ("read_at",), False),
}

# Append-only tables: (mutable columns...). DELETE always rejected; every other column frozen.
IMMUTABLE_TABLES: dict[str, tuple[str, ...]] = {
    "business_transactions": ("status", "reversed_by_transaction_id"),
    "stock_movements": (),
    "credit_entries": ("settled_paise", "is_open"),
    "payments": ("allocated_paise", "unallocated_paise"),
    "payment_allocations": (),
    "sales": ("status", "updated_at"),
    "sale_items": (),
    "expenses": ("status", "updated_at"),
    "goods_receipts": (),
    "goods_receipt_items": (),
    "product_prices": (),
    "audit_logs": (),
}


def _q(cols: tuple[str, ...]) -> str:
    return ", ".join(cols)


def upgrade() -> None:
    # ------------------------------------------------------------------ 1. context functions
    op.execute(
        """
        CREATE FUNCTION app_current_shop_id() RETURNS uuid
        LANGUAGE sql STABLE PARALLEL SAFE AS
        $$ SELECT NULLIF(current_setting('app.current_shop_id', true), '')::uuid $$;

        CREATE FUNCTION app_current_user_id() RETURNS uuid
        LANGUAGE sql STABLE PARALLEL SAFE AS
        $$ SELECT NULLIF(current_setting('app.current_user_id', true), '')::uuid $$;

        REVOKE ALL ON FUNCTION app_current_shop_id() FROM PUBLIC;
        REVOKE ALL ON FUNCTION app_current_user_id() FROM PUBLIC;
        """
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION app_current_shop_id() TO {APP_ROLE}")
    op.execute(f"GRANT EXECUTE ON FUNCTION app_current_user_id() TO {APP_ROLE}")

    # ------------------------------------------------------------------ 2. row-level security
    for table in STANDARD_TENANT_TABLES + SPECIAL_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    for table in STANDARD_TENANT_TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} FOR ALL "
            f"USING (shop_id = app_current_shop_id()) "
            f"WITH CHECK (shop_id = app_current_shop_id())"
        )

    op.execute(
        """
        -- shops: visible if it is the active shop or the user is an active member;
        -- a shop can only be created as the active shop by the creating user.
        CREATE POLICY shops_select ON shops FOR SELECT USING (
            id = app_current_shop_id()
            OR EXISTS (
                SELECT 1 FROM shop_members m
                WHERE m.shop_id = shops.id
                  AND m.user_id = app_current_user_id()
                  AND m.status = 'active'
            )
        );
        CREATE POLICY shops_insert ON shops FOR INSERT WITH CHECK (
            id = app_current_shop_id() AND created_by_user_id = app_current_user_id()
        );
        CREATE POLICY shops_update ON shops FOR UPDATE
            USING (id = app_current_shop_id())
            WITH CHECK (id = app_current_shop_id());

        -- shop_members: the active shop's members, plus the user's own memberships
        -- (needed to list shops and to switch shops before a shop context exists).
        CREATE POLICY shop_members_select ON shop_members FOR SELECT USING (
            shop_id = app_current_shop_id() OR user_id = app_current_user_id()
        );
        CREATE POLICY shop_members_insert ON shop_members FOR INSERT
            WITH CHECK (shop_id = app_current_shop_id());
        CREATE POLICY shop_members_update ON shop_members FOR UPDATE
            USING (shop_id = app_current_shop_id())
            WITH CHECK (shop_id = app_current_shop_id());

        -- audit_logs: readable per shop; shop-less events (login, registration) are write-only.
        CREATE POLICY audit_logs_select ON audit_logs FOR SELECT
            USING (shop_id = app_current_shop_id());
        CREATE POLICY audit_logs_insert ON audit_logs FOR INSERT
            WITH CHECK (shop_id IS NULL OR shop_id = app_current_shop_id());

        -- idempotency_keys: a user's own keys, scoped to the active shop (or shop-less).
        CREATE POLICY idempotency_keys_owner ON idempotency_keys FOR ALL
            USING (user_id = app_current_user_id()
                   AND (shop_id IS NULL OR shop_id = app_current_shop_id()))
            WITH CHECK (user_id = app_current_user_id()
                        AND (shop_id IS NULL OR shop_id = app_current_shop_id()));
        """
    )

    # ------------------------------------------------------------------ 3. grants
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    for table, (privileges, update_cols, allow_delete) in GRANTS.items():
        op.execute(f"GRANT {', '.join(privileges)} ON {table} TO {APP_ROLE}")
        if update_cols:
            op.execute(f"GRANT UPDATE ({_q(update_cols)}) ON {table} TO {APP_ROLE}")
        if allow_delete:
            op.execute(f"GRANT DELETE ON {table} TO {APP_ROLE}")

    # ------------------------------------------------------------------ 4. immutability
    op.execute(
        """
        CREATE FUNCTION munim_forbid_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'rows in % are append-only and cannot be deleted', TG_TABLE_NAME
                USING ERRCODE = 'insufficient_privilege';
        END $$;

        -- TG_ARGV = the only columns allowed to change; everything else must stay identical.
        CREATE FUNCTION munim_guard_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            old_row jsonb := to_jsonb(OLD);
            new_row jsonb := to_jsonb(NEW);
            col text;
        BEGIN
            IF TG_NARGS > 0 THEN
                FOREACH col IN ARRAY TG_ARGV LOOP
                    old_row := old_row - col;
                    new_row := new_row - col;
                END LOOP;
            END IF;
            IF old_row IS DISTINCT FROM new_row THEN
                RAISE EXCEPTION 'immutable columns of % cannot be changed', TG_TABLE_NAME
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END $$;

        -- A business transaction may change state only once: posted -> reversed.
        CREATE FUNCTION munim_guard_transaction_status() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status = 'reversed' THEN
                RAISE EXCEPTION 'business transaction % is already reversed', OLD.id
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            IF NEW.status <> 'reversed' OR NEW.reversed_by_transaction_id IS NULL THEN
                RAISE EXCEPTION 'business transactions can only change by being reversed'
                    USING ERRCODE = 'insufficient_privilege';
            END IF;
            RETURN NEW;
        END $$;
        """
    )
    for table, mutable in IMMUTABLE_TABLES.items():
        args = ", ".join(f"'{c}'" for c in mutable)
        op.execute(
            f"CREATE TRIGGER {table}_forbid_delete BEFORE DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION munim_forbid_delete()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_guard_immutable BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION munim_guard_immutable({args})"
        )
    op.execute(
        "CREATE TRIGGER business_transactions_guard_status BEFORE UPDATE ON business_transactions "
        "FOR EACH ROW EXECUTE FUNCTION munim_guard_transaction_status()"
    )


def downgrade() -> None:
    # Development/test databases only.
    op.execute("DROP TRIGGER IF EXISTS business_transactions_guard_status ON business_transactions")
    for table in IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {table}_guard_immutable ON {table}")
        op.execute(f"DROP TRIGGER IF EXISTS {table}_forbid_delete ON {table}")
    op.execute("DROP FUNCTION IF EXISTS munim_guard_transaction_status()")
    op.execute("DROP FUNCTION IF EXISTS munim_guard_immutable()")
    op.execute("DROP FUNCTION IF EXISTS munim_forbid_delete()")
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    for table in STANDARD_TENANT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    for policy, table in (
        ("shops_select", "shops"),
        ("shops_insert", "shops"),
        ("shops_update", "shops"),
        ("shop_members_select", "shop_members"),
        ("shop_members_insert", "shop_members"),
        ("shop_members_update", "shop_members"),
        ("audit_logs_select", "audit_logs"),
        ("audit_logs_insert", "audit_logs"),
        ("idempotency_keys_owner", "idempotency_keys"),
    ):
        op.execute(f"DROP POLICY IF EXISTS {policy} ON {table}")
    for table in STANDARD_TENANT_TABLES + SPECIAL_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION IF EXISTS app_current_user_id()")
    op.execute("DROP FUNCTION IF EXISTS app_current_shop_id()")
