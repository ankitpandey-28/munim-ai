"""Domain modules of the modular monolith (docs/architecture.md §3).

Each module will be a package ``app/modules/<name>/`` containing ``api.py``, ``schemas.py``,
``service.py`` (its public interface), ``models.py`` and ``repository.py``. Modules call each
other only through ``service.py``. None exist yet: identity, shops, ledger and audit arrive in
Phase 2.2+; business modules (catalog, inventory, sales, credit, ...) in Phase 3+.
"""
