"""Disposable end-to-end stack: throwaway PostgreSQL 18 cluster + migrations + the real API.

Never touches the real ``munim_ai`` database or ``backend/.env``: the cluster is created by
``initdb`` in a temporary directory (tests/support/pg_cluster.py), the API runs with explicit
environment variables from a temporary working directory, and everything is deleted on exit.

Usage (from backend/):  .venv\\Scripts\\python -m scripts.e2e_stack [--port 8000]
Then build/start the frontend with BACKEND_INTERNAL_URL=http://127.0.0.1:<port>.
Stop with Ctrl+C, or create the file printed as "stop file".
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from tests.support.pg_cluster import TempPostgres, find_pg_bin  # noqa: E402


def _wait_healthy(url: str, timeout: float = 60) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:  # noqa: S310 - localhost only
                if r.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"API did not become healthy at {url}")


def _port_free(port: int) -> bool:
    """True if nothing listens on 127.0.0.1:port. A server already there (for example a dev
    server on the real database) would otherwise answer the health check and receive the
    E2E traffic instead of this disposable stack."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    if not _port_free(args.port):
        print(
            f"Port {args.port} is already in use (another API?). Stop it or pass --port; "
            "refusing to start so E2E traffic can never reach a non-disposable server.",
            file=sys.stderr,
        )
        return 3
    bin_dir = find_pg_bin()
    if bin_dir is None:
        print("PostgreSQL binaries not found; set MUNIM_PG_BIN.", file=sys.stderr)
        return 2
    exe_dir = Path(sys.executable).parent
    cluster = TempPostgres(bin_dir).start()
    api: subprocess.Popen | None = None
    cwd: str | None = None
    stop_file = Path(tempfile.gettempdir()) / f"munim-e2e-stop-{args.port}"
    stop_file.unlink(missing_ok=True)
    try:
        env = {
            **cluster.alembic_env(),
            "PYTHONPATH": str(BACKEND_DIR),
            "APP_ENV": "development",
            "AUTH_SECRET_KEY": secrets.token_urlsafe(32),
            "SESSION_COOKIE_SECURE": "false",
            "FRONTEND_ORIGINS": "http://localhost:3000,http://127.0.0.1:3000",
            "LOG_LEVEL": "WARNING",
            # Disposable test stack only: E2E suites register many accounts from 127.0.0.1
            # (same relaxation as tests/integration/conftest.py; production defaults unchanged).
            "REGISTRATION_IP_MAX_PER_HOUR": "1000",
            "LOGIN_IP_MAX_ATTEMPTS": "1000",
        }
        # Empty working directory so backend/.env is never read; removed after the API stops.
        cwd = tempfile.mkdtemp(prefix="munim-e2e-")
        alembic = exe_dir / ("alembic.exe" if os.name == "nt" else "alembic")
        result = subprocess.run(
            [str(alembic), "-c", str(BACKEND_DIR / "alembic.ini"), "upgrade", "head"],
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print("alembic upgrade failed", file=sys.stderr)
            return 1
        uvicorn = exe_dir / ("uvicorn.exe" if os.name == "nt" else "uvicorn")
        api = subprocess.Popen(
            [str(uvicorn), "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
            cwd=cwd,
            env=env,
        )
        _wait_healthy(f"http://127.0.0.1:{args.port}/api/v1/health")
        if api.poll() is not None:  # our API died (e.g. port taken meanwhile): not our server
            print("disposable API exited during startup; aborting", file=sys.stderr)
            return 1
        api_url = f"http://127.0.0.1:{args.port}"
        print(f"E2E stack ready: API {api_url} (disposable DB port {cluster.port})", flush=True)
        print(f"stop file: {stop_file}", flush=True)
        while api.poll() is None and not stop_file.exists():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        if api and api.poll() is None:
            api.terminate()
            try:
                api.wait(timeout=10)
            except subprocess.TimeoutExpired:
                api.kill()
        if cwd:
            shutil.rmtree(cwd, ignore_errors=True)
        cluster.stop()
        stop_file.unlink(missing_ok=True)
        print("E2E stack stopped and disposable database deleted.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
