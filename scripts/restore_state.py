#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCAL_TMP_ROOT = PROJECT_ROOT / "ops" / ".tmp"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Restore DB + config snapshot created by backup_state.py.")
    parser.add_argument(
        "--snapshot",
        required=True,
        help="Path to snapshot (.zip or extracted directory).",
    )
    parser.add_argument(
        "--target",
        default=str(PROJECT_ROOT),
        help="Restore target root directory (default: project root).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without writing files.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Required for real restore (non-dry-run).",
    )
    return parser.parse_args()


def _load_manifest(snapshot_root: Path) -> dict[str, object]:
    manifest_path = snapshot_root / "manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("manifest.json not found in snapshot")
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"failed to parse manifest.json: {exc}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("manifest.json has invalid format")
    return data


def _snapshot_root(snapshot_path: Path) -> tuple[Path, Path | None]:
    if snapshot_path.is_dir():
        return snapshot_path, None
    if snapshot_path.is_file() and snapshot_path.suffix.lower() == ".zip":
        LOCAL_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        tmp_dir = LOCAL_TMP_ROOT / f"restore-stage-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=False)
        shutil.unpack_archive(str(snapshot_path), str(tmp_dir), "zip")
        return tmp_dir, tmp_dir
    raise RuntimeError("snapshot must be .zip file or extracted directory")


def _restore(snapshot_root: Path, target_root: Path, *, dry_run: bool) -> dict[str, object]:
    manifest = _load_manifest(snapshot_root)
    items = manifest.get("items_included")
    if not isinstance(items, list):
        raise RuntimeError("manifest.json missing items_included list")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    safety_root = target_root / "ops" / "restore_safety" / stamp
    restored: list[str] = []
    overwritten: list[str] = []
    missing_in_snapshot: list[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        rel = str(item.get("path") or "").strip()
        if not rel:
            continue
        source = snapshot_root / rel
        target = target_root / rel
        if not source.exists() or not source.is_file():
            missing_in_snapshot.append(rel)
            continue

        if target.exists() and target.is_file():
            overwritten.append(rel)
            if not dry_run:
                backup_path = safety_root / rel
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup_path)

        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        restored.append(rel)

    return {
        "restored": restored,
        "overwritten": overwritten,
        "missing_in_snapshot": missing_in_snapshot,
        "safety_dir": str(safety_root) if overwritten and not dry_run else None,
    }


def main() -> int:
    args = _parse_args()
    snapshot_path = Path(args.snapshot).expanduser().resolve()
    target_root = Path(args.target).expanduser().resolve()
    if not snapshot_path.exists():
        print(f"[restore] snapshot not found: {snapshot_path}")
        return 2
    if not target_root.exists():
        print(f"[restore] target not found: {target_root}")
        return 2
    if not args.dry_run and not args.yes:
        print("[restore] use --yes for real restore or run with --dry-run")
        return 2

    temp_dir: Path | None = None
    try:
        root, temp_dir = _snapshot_root(snapshot_path)
        summary = _restore(root, target_root, dry_run=bool(args.dry_run))
    except Exception as exc:  # noqa: BLE001
        print(f"[restore] failed: {exc}")
        return 1
    finally:
        if temp_dir is not None:
            shutil.rmtree(temp_dir, ignore_errors=True)

    mode = "dry-run" if args.dry_run else "apply"
    print(f"[restore] mode={mode} target={target_root}")
    print(
        f"[restore] restored={len(summary['restored'])} "
        f"overwritten={len(summary['overwritten'])} "
        f"missing_in_snapshot={len(summary['missing_in_snapshot'])}"
    )
    if summary["safety_dir"]:
        print(f"[restore] safety backup: {summary['safety_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
