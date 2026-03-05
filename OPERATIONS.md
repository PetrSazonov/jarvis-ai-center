# Runtime Notes

## Local/Home Server Run
- Use a dedicated virtual environment.
- Set environment variables in `.env` (never commit real tokens).
- Run with restart policy (Task Scheduler, launchd/systemd, pm2 equivalent).

## Multi-device Setup
1. Clone repo on new machine.
2. Run bootstrap script:
   - Windows: `./scripts/bootstrap.ps1`
   - Mac/Linux: `./scripts/bootstrap.sh`
3. Fill local `.env`.
4. Run secret scan: `python scripts/check_secrets.py`.
5. Enable git hook once: `git config core.hooksPath .githooks`.

## Windows Task Scheduler (example)
1. Trigger: At startup.
2. Action: `venv\\Scripts\\python.exe bot.py` in project directory.
3. Enable restart on failure (1 minute, up to 3 attempts).

## Security
- Rotate Telegram token if it was ever exposed.
- Keep `.env` local only.
- Before push/commit run secret scan.

## Basic Health Checks
- Use `/status` for Ollama/CoinGecko/DB quick checks.
- Check logs for `event=api_error`, `event=crypto_worker_error`, `event=auto_digest_error`, `event=todo_reminder_error`.

## Minimal Web API Run
- Start API server (recommended profile-runner):
  - `python scripts/run_web_service.py --profile dev`
  - `python scripts/run_web_service.py --profile prod`
  - runner prints local and detected LAN dashboard URLs on startup (when host is `0.0.0.0`)
- Alternative raw uvicorn:
  - `uvicorn app.api:app --reload`
- Endpoints:
  - `GET /today?user_id=<id>`
  - `GET /tasks?user_id=<id>`
  - `POST /tasks`
  - `GET /subs?user_id=<id>`
  - `POST /subs`
  - `GET /signals?user_id=<id>`
  - `GET /dashboard`
  - `GET /dashboard/data?user_id=<id>&debug=0|1&ai=0|1`

API flags:
- `API_DEBUG_EVENTS=1` enables event stream in API responses when `debug=1`.
- `API_DEBUG_EVENTS_REMOTE=0` keeps debug events local-only (loopback). Set `1` only for trusted networks.
- `DASHBOARD_ALLOW_PUBLIC=0` keeps dashboard/API restricted to trusted networks only.
- `DASHBOARD_TRUSTED_NETS` defines allowed CIDRs for dashboard/API access.
- `DASHBOARD_AI_BRIEF=1` enables LLM AI-brief in dashboard data when `ai=1`.
- `DASHBOARD_AI_EVERYWHERE=1` enables LLM polish pack across core dashboard panels when `ai=1`.
- `ENABLE_TASK_REMINDERS=true` enables Telegram reminders for tasks with `remind_at`.
- `TASK_REMINDER_INTERVAL_SECONDS=45` controls reminder queue poll interval.
- `INGEST_IMAP_ENABLED=1` enables IMAP ingest signals.
- `INGEST_LOCAL_ENABLED=1` + `INGEST_LOCAL_PATHS=<path1,path2>` enables local-file ingest signals.
- `RAG_ENABLED=1` enables retrieval over personal ingest data.
- `RAG_REQUIRE_CITATIONS=1` enforces citation requirement for personal-data chat answers.
- `DASHBOARD_AUTH_ENABLED=1` + `DASHBOARD_ACCESS_TOKEN=<secret>` enables minimal token auth for dashboard/API routes.
- Access patterns when auth is enabled:
  - Browser: open `/dashboard?token=<secret>` once (token stored in secure cookie).
  - API client: send header `x-jarvis-token: <secret>` or `Authorization: Bearer <secret>`.

Profile env files:
- `.env.dev` (from `.env.dev.example`)
- `.env.prod` (from `.env.prod.example`)
- full runbook: `RUNBOOK_DEPLOY_V1.md`
- remote-access checklist: `REMOTE_ACCESS_CHECKLIST.md`
- backup/restore baseline: `BACKUP_RESTORE.md`

## Backup and Restore
- Create snapshot:
  - `python scripts/backup_state.py --dest ops/backups --keep 14`
- Restore dry-run:
  - `python scripts/restore_state.py --snapshot ops/backups/<archive>.zip --target . --dry-run`
- Restore apply:
  - `python scripts/restore_state.py --snapshot ops/backups/<archive>.zip --target . --yes`

## Day OS First Layer
Command list exposed in Telegram menu is intentionally minimal:
- `/start`
- `/menu`
- `/today`
- `/todo`
- `/focus`
- `/checkin`
- `/week`
- `/review`
- `/decide`

Weekly compatibility:
- canonical: `/week` + `/review week`
- alias: `/weekly` (soft redirect)

## Release Hardening (RC)
- RC checklist: `RELEASE_RC_CHECKLIST.md`
- Fast pre-release commands:
  - `.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`
  - `.\venv\Scripts\python.exe -m compileall -q app core handlers services tests bot.py`
