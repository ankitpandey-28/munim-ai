"""Verification of the *actual* PostgreSQL session identity (docs/database-design.md §8.1).

Configuration can lie (a wrong user in a URL, a password shared between roles, ``SET ROLE``),
so both connections check who they really are after connecting:

- runtime (API/worker): must be ``munim_app`` on ``munim_ai``, NOSUPERUSER, NOBYPASSRLS,
  NOINHERIT, and must not own the database;
- migrations (Alembic): must be ``munim_owner`` on ``munim_ai``, NOSUPERUSER, NOBYPASSRLS,
  and must own the database.

Problems are reported as fixed, non-secret codes. Role and database *names* are not secrets;
passwords, URLs and connection strings never appear in any message produced here.
"""

from dataclasses import dataclass

from sqlalchemy import Connection, text

from app.core.config import Settings

# session_user = the role that authenticated; current_user = the effective role (differs after
# SET ROLE). Both must be the expected role.
IDENTITY_SQL = text(
    """
    SELECT session_user        AS login_role,
           current_user        AS effective_role,
           current_database()  AS database,
           r.rolsuper          AS is_superuser,
           r.rolbypassrls      AS bypass_rls,
           r.rolinherit        AS inherit,
           (d.datdba = r.oid)  AS owns_database
    FROM pg_catalog.pg_roles r
    JOIN pg_catalog.pg_database d ON d.datname = current_database()
    WHERE r.rolname = current_user
    """
)


@dataclass(frozen=True)
class SessionIdentity:
    login_role: str
    effective_role: str
    database: str
    is_superuser: bool
    bypass_rls: bool
    inherit: bool
    owns_database: bool


class UnsafeDatabaseIdentityError(RuntimeError):
    """Raised when a connection is not the role/database it must be. Message has no secrets."""

    def __init__(self, purpose: str, problems: list[str]) -> None:
        self.purpose = purpose
        self.problems = problems
        super().__init__(
            f"{purpose} database connection failed the identity check: {', '.join(problems)}"
        )


def fetch_identity(connection: Connection) -> SessionIdentity | None:
    row = connection.execute(IDENTITY_SQL).mappings().one_or_none()
    return SessionIdentity(**row) if row is not None else None


def _common_problems(
    identity: SessionIdentity, expected_role: str, expected_database: str
) -> list[str]:
    problems: list[str] = []
    if identity.login_role != expected_role or identity.effective_role != expected_role:
        problems.append(f"unexpected_role(expected {expected_role})")
    if identity.database != expected_database:
        problems.append(f"unexpected_database(expected {expected_database})")
    if identity.is_superuser:
        problems.append("superuser")
    if identity.bypass_rls:
        problems.append("bypassrls")
    return problems


def runtime_identity_problems(identity: SessionIdentity | None, settings: Settings) -> list[str]:
    """Empty list means the runtime connection is safe."""
    if identity is None:
        return ["identity_unavailable"]
    problems = _common_problems(identity, settings.database_app_role, settings.database_name)
    if identity.inherit:
        problems.append("inherit")
    if identity.owns_database:
        problems.append("owns_database")
    return problems


def migration_identity_problems(identity: SessionIdentity | None, settings: Settings) -> list[str]:
    """Empty list means the migration connection is the expected schema owner."""
    if identity is None:
        return ["identity_unavailable"]
    problems = _common_problems(identity, settings.database_owner_role, settings.database_name)
    if not identity.owns_database:
        problems.append("not_database_owner")
    return problems


def verify_migration_identity(connection: Connection, settings: Settings) -> SessionIdentity:
    """Fail closed unless ``connection`` is the migration owner on the project database.

    Ends the read-only transaction it opened so Alembic starts its own migration transaction.
    """
    try:
        identity = fetch_identity(connection)
    finally:
        connection.rollback()
    problems = migration_identity_problems(identity, settings)
    if problems or identity is None:
        raise UnsafeDatabaseIdentityError("migration", problems or ["identity_unavailable"])
    return identity
