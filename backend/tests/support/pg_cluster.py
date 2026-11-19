"""Disposable PostgreSQL cluster for integration tests and migration generation.

Never touches the developer's real PostgreSQL: it runs ``initdb`` into a temporary directory,
starts a private server on a free localhost port, provisions roles with the project's own
``infra/postgres/local-setup.sql`` (CI mode, throwaway passwords) and deletes everything on stop.

Binary discovery order: $MUNIM_PG_BIN, PATH, common install locations. PostgreSQL 17+ required
(18 recommended; the schema uses uuidv7()).
"""

from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SETUP_SQL = REPO_ROOT / "infra" / "postgres" / "local-setup.sql"

_CANDIDATE_DIRS = [
    r"C:\Program Files\PostgreSQL\18\bin",
    r"C:\Program Files\PostgreSQL\17\bin",
    "/usr/lib/postgresql/18/bin",
    "/usr/lib/postgresql/17/bin",
    "/opt/homebrew/opt/postgresql@18/bin",
    "/usr/local/opt/postgresql@18/bin",
]


def find_pg_bin() -> Path | None:
    env = os.environ.get("MUNIM_PG_BIN")
    candidates = [env] if env else []
    which = shutil.which("initdb")
    if which:
        candidates.append(str(Path(which).parent))
    candidates += _CANDIDATE_DIRS
    exe = ".exe" if os.name == "nt" else ""
    for c in candidates:
        if c and (Path(c) / f"initdb{exe}").exists() and (Path(c) / f"pg_ctl{exe}").exists():
            return Path(c)
    return None


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class TempPostgres:
    bin_dir: Path
    port: int = field(default_factory=_free_port)
    workdir: Path = field(default_factory=lambda: Path(tempfile.mkdtemp(prefix="munim-pg-")))
    superuser: str = "test_super"
    superuser_password: str = field(default_factory=lambda: secrets.token_urlsafe(18))
    owner_password: str = field(default_factory=lambda: secrets.token_urlsafe(18))
    app_password: str = field(default_factory=lambda: secrets.token_urlsafe(18))
    started: bool = False

    def _exe(self, name: str) -> str:
        return str(self.bin_dir / (name + (".exe" if os.name == "nt" else "")))

    @property
    def data_dir(self) -> Path:
        return self.workdir / "data"

    def url(self, role: str, password: str, database: str = "munim_ai") -> str:
        return f"postgresql+psycopg://{role}:{password}@127.0.0.1:{self.port}/{database}"

    @property
    def app_url(self) -> str:
        return self.url("munim_app", self.app_password)

    @property
    def owner_url(self) -> str:
        return self.url("munim_owner", self.owner_password)

    @property
    def superuser_url(self) -> str:
        return self.url(self.superuser, self.superuser_password)

    def psql(self, *args: str, database: str = "postgres", check: bool = True):
        env = {**os.environ, "PGPASSWORD": self.superuser_password, "PGCLIENTENCODING": "UTF8"}
        return subprocess.run(
            [
                self._exe("psql"),
                "-X",
                "-q",
                "-h",
                "127.0.0.1",
                "-p",
                str(self.port),
                "-U",
                self.superuser,
                "-d",
                database,
                "-v",
                "ON_ERROR_STOP=1",
                *args,
            ],
            env=env,
            capture_output=True,
            text=True,
            check=check,
        )

    def start(self) -> TempPostgres:
        pwfile = self.workdir / "su.pw"
        pwfile.write_text(self.superuser_password, encoding="utf-8")
        subprocess.run(
            [
                self._exe("initdb"),
                "-D",
                str(self.data_dir),
                "-U",
                self.superuser,
                "-A",
                "scram-sha-256",
                f"--pwfile={pwfile}",
                "-E",
                "UTF8",
                "--no-instructions",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        pwfile.unlink()
        log = self.workdir / "server.log"
        options = (
            f"-p {self.port} -c listen_addresses=127.0.0.1 -c fsync=off "
            "-c synchronous_commit=off -c full_page_writes=off"
        )
        if os.name != "nt":
            # Debian/Ubuntu builds default the Unix socket to /var/run/postgresql, which only the
            # postgres OS user may write; keep this throwaway cluster's socket in its own dir.
            options += f" -c unix_socket_directories={self.workdir}"
        result = subprocess.run(
            [
                self._exe("pg_ctl"),
                "-D",
                str(self.data_dir),
                "-l",
                str(log),
                "-w",
                "-t",
                "60",
                "-o",
                options,
                "start",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0:
            tail = log.read_text(encoding="utf-8", errors="replace")[-2000:] if log.exists() else ""
            raise RuntimeError(f"disposable PostgreSQL failed to start:\n{tail}")
        self.started = True
        # Provision munim_ai + roles exactly as developers do (CI mode = throwaway passwords).
        self.psql(
            "-v",
            f"owner_password={self.owner_password}",
            "-v",
            f"app_password={self.app_password}",
            "-f",
            str(SETUP_SQL),
        )
        return self

    def stop(self) -> None:
        if self.started:
            subprocess.run(
                [self._exe("pg_ctl"), "-D", str(self.data_dir), "-m", "immediate", "-w", "stop"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            self.started = False
            time.sleep(0.5)
        shutil.rmtree(self.workdir, ignore_errors=True)

    def alembic_env(self) -> dict[str, str]:
        """Environment for running Alembic/backend against this cluster (never the real .env)."""
        return {
            **os.environ,
            "DATABASE_URL": self.app_url,
            "MIGRATION_DATABASE_URL": self.owner_url,
            "APP_ENV": "test",
        }

    def __enter__(self) -> TempPostgres:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
