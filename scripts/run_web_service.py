from __future__ import annotations

import argparse
import ipaddress
import os
import socket
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv


TRUE_VALUES = {"1", "true", "yes", "on"}
PROFILE_CHOICES = ("dev", "prod")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _bool_from_env(key: str, default: bool) -> bool:
    raw = str(os.getenv(key, "")).strip().lower()
    if not raw:
        return default
    return raw in TRUE_VALUES


def _int_from_env(key: str, default: int, *, min_value: int = 1) -> int:
    raw = str(os.getenv(key, "")).strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return max(min_value, value)


def _apply_profile_defaults(profile: str) -> None:
    if profile == "dev":
        os.environ.setdefault("DASHBOARD_AUTH_ENABLED", "0")
        os.environ.setdefault("DASHBOARD_ALLOW_PUBLIC", "0")
        os.environ.setdefault(
            "DASHBOARD_TRUSTED_NETS",
            "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,fc00::/7",
        )
        os.environ.setdefault("API_DEBUG_EVENTS", "1")
        os.environ.setdefault("API_DEBUG_EVENTS_REMOTE", "0")
        os.environ.setdefault("DASHBOARD_RELOAD", "1")
        os.environ.setdefault("DASHBOARD_WORKERS", "1")
        os.environ.setdefault("LOG_LEVEL", "DEBUG")
        return

    os.environ.setdefault("DASHBOARD_AUTH_ENABLED", "1")
    os.environ.setdefault("DASHBOARD_ALLOW_PUBLIC", "0")
    os.environ.setdefault(
        "DASHBOARD_TRUSTED_NETS",
        "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,100.64.0.0/10,fc00::/7",
    )
    os.environ.setdefault("API_DEBUG_EVENTS", "0")
    os.environ.setdefault("API_DEBUG_EVENTS_REMOTE", "0")
    os.environ.setdefault("DASHBOARD_RELOAD", "0")
    os.environ.setdefault("DASHBOARD_WORKERS", "1")
    os.environ.setdefault("LOG_LEVEL", "INFO")


def _load_env(profile: str) -> Path | None:
    base_env = PROJECT_ROOT / ".env"
    profile_env = PROJECT_ROOT / f".env.{profile}"
    load_dotenv(dotenv_path=base_env, override=False)
    if profile_env.exists():
        load_dotenv(dotenv_path=profile_env, override=True)
        return profile_env
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Day OS Web service (FastAPI + Dashboard) with dev/prod profile."
    )
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default="dev",
        help="Runtime profile.",
    )
    parser.add_argument("--host", default="", help="Override host (default from env/profile).")
    parser.add_argument("--port", type=int, default=0, help="Override port (default from env/profile).")
    parser.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Override workers count (ignored when reload=1).",
    )

    reload_group = parser.add_mutually_exclusive_group()
    reload_group.add_argument("--reload", action="store_true", help="Force enable autoreload.")
    reload_group.add_argument("--no-reload", action="store_true", help="Force disable autoreload.")

    parser.add_argument("--dry-run", action="store_true", help="Print effective config and exit.")
    return parser


def _resolve_runtime(args: argparse.Namespace) -> dict[str, object]:
    profile = str(args.profile).strip().lower()
    host = str(args.host or "").strip() or os.getenv("DASHBOARD_HOST", "0.0.0.0")
    port = int(args.port or _int_from_env("DASHBOARD_PORT", 8000, min_value=1))
    workers = int(args.workers or _int_from_env("DASHBOARD_WORKERS", 1, min_value=1))

    if args.reload:
        reload_enabled = True
    elif args.no_reload:
        reload_enabled = False
    else:
        reload_enabled = _bool_from_env("DASHBOARD_RELOAD", default=(profile == "dev"))

    if reload_enabled:
        workers = 1

    log_level = str(os.getenv("LOG_LEVEL", "INFO")).strip().lower() or "info"
    allowed_levels = {"critical", "error", "warning", "info", "debug", "trace"}
    if log_level not in allowed_levels:
        log_level = "info"

    return {
        "profile": profile,
        "host": host,
        "port": port,
        "workers": workers,
        "reload": reload_enabled,
        "log_level": log_level,
    }


def _validate_security(profile: str) -> int:
    if profile != "prod":
        return 0
    auth_enabled = _bool_from_env("DASHBOARD_AUTH_ENABLED", True)
    if not auth_enabled:
        print("[ERROR] prod profile requires DASHBOARD_AUTH_ENABLED=1")
        return 2
    if _bool_from_env("DASHBOARD_ALLOW_PUBLIC", False):
        print("[ERROR] prod profile requires DASHBOARD_ALLOW_PUBLIC=0")
        return 2
    token = str(os.getenv("DASHBOARD_ACCESS_TOKEN", "")).strip()
    if not token:
        print("[ERROR] prod profile requires DASHBOARD_ACCESS_TOKEN in .env or .env.prod")
        return 2
    return 0


def _lan_ipv4_candidates() -> list[str]:
    values: list[str] = []
    seen: set[str] = set()

    def add(ip: str) -> None:
        if not ip or ip in seen:
            return
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return
        if addr.version != 4:
            return
        if ip.startswith("127."):
            return
        if not (addr.is_private or addr.is_link_local):
            return
        seen.add(ip)
        values.append(ip)

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            add(str(info[4][0]))
    except socket.gaierror:
        pass

    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        add(str(sock.getsockname()[0]))
    except OSError:
        pass
    finally:
        if sock is not None:
            sock.close()

    return values


def _print_access_urls(host: str, port: int) -> None:
    dashboard_path = "/dashboard"
    local_url = f"http://127.0.0.1:{port}{dashboard_path}"
    if host in {"0.0.0.0", "::"}:
        print(f"[DayOS] local: {local_url}")
        lan = _lan_ipv4_candidates()
        if lan:
            for ip in lan:
                print(f"[DayOS] lan:   http://{ip}:{port}{dashboard_path}")
        else:
            print("[DayOS] lan:   not detected automatically (check your active network adapter IP)")
        return
    if host in {"127.0.0.1", "localhost"}:
        print(f"[DayOS] local: {local_url}")
        return
    print(f"[DayOS] host:  http://{host}:{port}{dashboard_path}")


def main(argv: list[str] | None = None) -> int:
    os.chdir(PROJECT_ROOT)
    parser = _build_parser()
    args = parser.parse_args(argv)

    profile = str(args.profile).strip().lower()
    profile_env = _load_env(profile)
    _apply_profile_defaults(profile)

    security_code = _validate_security(profile)
    if security_code:
        return security_code

    runtime = _resolve_runtime(args)
    source = f".env + {profile_env.name}" if profile_env else ".env (profile defaults)"

    print(
        "[DayOS] profile={profile} source={source} host={host} port={port} "
        "reload={reload} workers={workers} log_level={log_level}".format(
            profile=runtime["profile"],
            source=source,
            host=runtime["host"],
            port=runtime["port"],
            reload=runtime["reload"],
            workers=runtime["workers"],
            log_level=runtime["log_level"],
        )
    )

    if args.dry_run:
        return 0

    _print_access_urls(str(runtime["host"]), int(runtime["port"]))

    uvicorn.run(
        "app.api:app",
        host=str(runtime["host"]),
        port=int(runtime["port"]),
        reload=bool(runtime["reload"]),
        workers=int(runtime["workers"]),
        log_level=str(runtime["log_level"]),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
