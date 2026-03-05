# Deploy Profile v1 (API + Dashboard)

Goal: one standard run path for Day OS Web (`app.api` + `/dashboard`) using `dev/prod` profiles.

## 1) Prepare
1. Run bootstrap:
   - Windows: `./scripts/bootstrap.ps1`
   - macOS/Linux: `./scripts/bootstrap.sh`
2. Create `.env` from `.env.example`.
3. Create profile file:
   - `.env.dev` from `.env.dev.example`
   - `.env.prod` from `.env.prod.example`

## 2) Single start command (Windows and Mac)
Dev:
```bash
python scripts/run_web_service.py --profile dev
```
On startup, the runner prints local and detected LAN dashboard URLs.

Prod:
```bash
python scripts/run_web_service.py --profile prod
```

Optional override:
```bash
python scripts/run_web_service.py --profile prod --host 0.0.0.0 --port 8080 --workers 1 --no-reload
```

## 3) Wrapper scripts
- Windows: `./scripts/service.ps1 -Profile dev`
- macOS/Linux: `./scripts/service.sh dev`

## 4) Verify
1. Open `http://<host>:<port>/dashboard`
2. Check `GET /ops/services`
3. For `profile=prod`, verify:
   - `DASHBOARD_AUTH_ENABLED=1`
   - `DASHBOARD_ACCESS_TOKEN` is set
   - `DASHBOARD_ALLOW_PUBLIC=0`
   - `API_DEBUG_EVENTS_REMOTE=0`

## 5) Service mode (recommended)
### Windows Task Scheduler
- Program: `<repo>\\venv\\Scripts\\python.exe`
- Arguments: `scripts\\run_web_service.py --profile prod`
- Start in: `<repo>`

### macOS launchd (idea)
- ProgramArguments:
  - `<repo>/venv/bin/python`
  - `<repo>/scripts/run_web_service.py`
  - `--profile`
  - `prod`
- WorkingDirectory: `<repo>`
- KeepAlive: `true`

## 6) Remote access hardening
Use one remote channel only (recommended: mesh VPN such as Tailscale/WireGuard/ZeroTier), with no direct public exposure.

Full checklist:
- `REMOTE_ACCESS_CHECKLIST.md`

## 7) Backup and restore baseline
Use:
- `BACKUP_RESTORE.md`

Quick commands:
```bash
python scripts/backup_state.py --dest ops/backups --keep 14
python scripts/restore_state.py --snapshot ops/backups/<archive>.zip --target . --dry-run
```
