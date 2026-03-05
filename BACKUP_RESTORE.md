# Backup and Restore Baseline (TASK-016)

Goal: regular backup of DB/config and a restore path that is actually testable.

## What is backed up
Default snapshot includes:
- `jarvis.db`
- `.env`
- `.env.dev`
- `.env.prod`

Backup archive also contains `manifest.json` with metadata and checksums.
For `.db` files, snapshot is created via SQLite backup API (`sqlite3.backup`) for consistent copy.

## 1) Create backup
```bash
python scripts/backup_state.py
```

Optional:
```bash
python scripts/backup_state.py --dest ops/backups --prefix dayos-backup --keep 14
python scripts/backup_state.py --item jarvis.db --item .env --item .env.prod
```

Output:
- zip archive in `ops/backups/`
- old archives cleanup based on `--keep`

## 2) Restore (safe)
Dry-run first:
```bash
python scripts/restore_state.py --snapshot ops/backups/<archive>.zip --target . --dry-run
```

Apply restore:
```bash
python scripts/restore_state.py --snapshot ops/backups/<archive>.zip --target . --yes
```

Safety behavior:
- existing target files are copied to `ops/restore_safety/<timestamp>/` before overwrite.

## 3) Test restore procedure (required)
Recommended non-destructive check:
```bash
python scripts/restore_state.py --snapshot ops/backups/<archive>.zip --target ops/restore_test --yes
```

Expected:
- command exits with code 0
- `ops/restore_test/jarvis.db` and env files appear

## 4) Regular schedule baseline
Windows Task Scheduler:
- Program: `<repo>\\venv\\Scripts\\python.exe`
- Arguments: `scripts\\backup_state.py --dest ops\\backups --keep 14`
- Trigger: daily, e.g. 03:30

macOS/Linux cron example:
```cron
30 3 * * * cd /path/to/repo && /path/to/repo/venv/bin/python scripts/backup_state.py --dest ops/backups --keep 14
```

## 5) Done criteria for TASK-016
- regular backup command configured
- restore procedure documented
- restore tested at least once and result validated
