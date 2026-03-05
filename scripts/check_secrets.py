#!/usr/bin/env python3
"""Basic secret scanner for local commits.

Usage:
    python scripts/check_secrets.py

The script prefers scanning files that are staged/tracked by git.
If git is unavailable, it falls back to scanning the working tree.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".git",
    "venv",
    ".venv",
    "Lib",
    "Scripts",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    "logs",
}

SKIP_FILES = {
    ".env",
}

TEXT_SUFFIXES = {
    ".py",
    ".md",
    ".txt",
    ".yml",
    ".yaml",
    ".json",
    ".toml",
    ".ini",
    ".cfg",
    ".env",
    ".example",
    ".sh",
    ".ps1",
    ".sql",
}

TELEGRAM_TOKEN_RE = re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{30,}\b")
GENERIC_ASSIGN_RE = re.compile(r"\b(BOT_TOKEN|API_KEY|SECRET|PASSWORD)\b\s*=\s*([^\s#]+)")


def _is_placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    markers = (
        "replace",
        "your_",
        "example",
        "changeme",
        "token_here",
        "dummy",
        "<",
        ">",
        "xxxxx",
    )
    return not lowered or any(m in lowered for m in markers)


def _git_files() -> list[Path]:
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        if inside.stdout.strip().lower() != "true":
            return []
    except Exception:
        return []

    files: set[str] = set()
    commands = [
        ["git", "ls-files"],
        ["git", "diff", "--cached", "--name-only"],
    ]
    for cmd in commands:
        try:
            out = subprocess.run(cmd, cwd=ROOT, check=True, capture_output=True, text=True)
        except Exception:
            continue
        for line in out.stdout.splitlines():
            line = line.strip()
            if line:
                files.add(line)

    return [ROOT / f for f in sorted(files)]


def _walk_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SKIP_FILES:
            continue
        out.append(path)
    return out


def _is_text_candidate(path: Path) -> bool:
    if path.name in {".env.example"}:
        return True
    if path.suffix.lower() in TEXT_SUFFIXES:
        return True
    return False


def _scan_file(path: Path) -> list[str]:
    rel = path.relative_to(ROOT)
    findings: list[str] = []

    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return findings

    # Hard check: Telegram bot-like token pattern.
    for match in TELEGRAM_TOKEN_RE.finditer(text):
        findings.append(f"{rel}: possible Telegram token `{match.group(0)[:12]}...`")

    # Soft check only for config-like files (env/toml/ini/cfg).
    is_config_like = (
        path.name.startswith(".env")
        or path.suffix.lower() in {".env", ".ini", ".cfg", ".toml"}
    )
    if is_config_like:
        for match in GENERIC_ASSIGN_RE.finditer(text):
            key = match.group(1)
            value = match.group(2).strip().strip("'\"")
            if _is_placeholder(value):
                continue
            findings.append(f"{rel}: suspicious assignment {key}=***")

    return findings


def main() -> int:
    files = _git_files()
    if not files:
        files = _walk_files()

    findings: list[str] = []
    for path in files:
        if not path.exists() or not path.is_file():
            continue
        if path.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not _is_text_candidate(path):
            continue
        findings.extend(_scan_file(path))

    if findings:
        print("Secret scan failed. Potential leaks found:")
        for item in findings:
            print(f"- {item}")
        print("\nFix or remove secrets before commit.")
        return 1

    print("Secret scan OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
