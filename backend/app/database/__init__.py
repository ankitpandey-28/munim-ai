"""Database engine, sessions and low-level checks.

Phase 2.2 adds the per-transaction shop context (``SET LOCAL app.current_shop_id``)
required by the RLS design in docs/database-design.md §8.
"""
