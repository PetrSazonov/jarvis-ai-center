#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import shutil
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKUP_DIR = PROJECT_ROOT / "ops" / "backups"
DEFAULT_ITEMS = ("jarvis.db", ".env", ".env.dev", ".env.prod")
LOCAL_TMP_ROOT = PROJECT_ROOT / "ops" / ".tmp"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_sqlite_safe(source: Path, target: Path) -> None:
    src_uri = f"file:{source.as_posix()}?mode=ro"
    src = sqlite3.connect(src_uri, uri=True)
    dst = sqlite3.connect(target.as_posix())
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create local backup for DB + config files.")
    parser.add_argument(
        "--dest",
        default=str(DEFAULT_BACKUP_DIR),
        help="Directory where backup archives are stored.",
    )
    parser.add_argument(
        "--prefix",
        default="dayos-backup",
        help="Backup file prefix.",
    )
    parser.add_argument(
        "--keep",
        type=int,
        default=14,
        help="How many latest archives to keep. Set 0 to disable cleanup.",
    )
    parser.add_argument(
        "--item",
        action="append",
        default=[],
        help="Relative file path to include. Can be repeated. Default: jarvis.db, .env, .env.dev, .env.prod.",
    )
    parser.add_argument(
        "--print-json",
        action="store_true",
        help="Print one-line JSON result.",
    )
    return parser.parse_args()


def _resolve_items(cli_items: list[str]) -> list[Path]:
    items = cli_items if cli_items else list(DEFAULT_ITEMS)
    out: list[Path] = []
    for item in items:
        rel = Path(item)
        if rel.is_absolute():
            continue
        out.append(PROJECT_ROOT / rel)
    return out


def _cleanup_old_archives(dest_dir: Path, prefix: str, keep: int) -> list[str]:
    if keep <= 0:
        return []
    archives = sorted(
        dest_dir.glob(f"{prefix}-*.zip"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed: list[str] = []
    for path in archives[keep:]:
        try:
            path.unlink()
            removed.append(path.name)
        except OSError:
            continue
    return removed


def main() -> int:
    args = _parse_args()
    dest_dir = Path(args.dest).expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = _utc_stamp()
    archive_base = dest_dir / f"{args.prefix}-{stamp}"
    archive_path = archive_base.with_suffix(".zip")
    LOCAL_TMP_ROOT.mkdir(parents=True, exist_ok=True)

    items = _resolve_items(args.item)
    included: list[dict[str, object]] = []
    missing: list[str] = []

    stage = LOCAL_TMP_ROOT / f"backup-stage-{stamp}-{uuid4().hex[:8]}"
    stage.mkdir(parents=True, exist_ok=False)
    try:
        for absolute_path in items:
            rel = absolute_path.relative_to(PROJECT_ROOT)
            if not absolute_path.exists():
                missing.append(rel.as_posix())
                continue
            if not absolute_path.is_file():
                missing.append(rel.as_posix())
                continue
            target = stage / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            used_sqlite_backup = False
            if absolute_path.suffix.lower() == ".db":
                try:
                    _copy_sqlite_safe(absolute_path, target)
                    used_sqlite_backup = True
                except Exception:
                    used_sqlite_backup = False
            if not used_sqlite_backup:
                shutil.copy2(absolute_path, target)
            included.append(
                {
                    "path": rel.as_posix(),
                    "size_bytes": int(target.stat().st_size),
                    "sha256": _sha256(target),
                    "mode": "sqlite_backup" if used_sqlite_backup else "copy2",
                }
            )

        manifest = {
            "schema": "dayos.backup.v1",
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "host": socket.gethostname(),
            "cwd": str(PROJECT_ROOT),
            "python": sys.version.split()[0],
            "items_included": included,
            "items_missing": missing,
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        shutil.make_archive(str(archive_base), "zip", root_dir=stage)
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    removed = _cleanup_old_archives(dest_dir, args.prefix, int(args.keep))
    result = {
        "ok": True,
        "archive": str(archive_path),
        "included_count": len(included),
        "missing_count": len(missing),
        "removed_old_archives": removed,
    }

    if args.print_json:
        print(json.dumps(result, ensure_ascii=False))
        return 0

    print(f"[backup] archive={archive_path}")
    print(f"[backup] included={len(included)} missing={len(missing)}")
    if missing:
        print(f"[backup] missing items: {', '.join(missing)}")
    if removed:
        print(f"[backup] removed old archives: {', '.join(removed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
