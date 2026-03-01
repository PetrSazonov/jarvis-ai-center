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
- Check logs for `event=api_error`, `event=crypto_worker_error`, `event=auto_digest_error`.
