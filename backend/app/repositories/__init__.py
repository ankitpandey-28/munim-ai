"""Shared repository base classes.

Phase 2.2 adds the shop-scoped base repository: every query requires a ``ShopContext``
and filters by ``shop_id`` (architecture §9.1, layer 4). Domain repositories will live
in their modules under ``app/modules/<name>/repository.py`` and extend it.
"""
