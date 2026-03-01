# Runtime Notes

## Local/Home Server Run
- Use a dedicated virtual environment.
- Set environment variables in `.env` (never commit real tokens).
- Run with restart policy (Task Scheduler, NSSM, pm2, or systemd if on Linux host).

## Windows Task Scheduler (example)
1. Trigger: At startup.
2. Action: `python bot.py` in project directory.
3. Enable restart on failure (1 minute, up to 3 attempts).

## Security
- Rotate Telegram token if it was ever exposed.
- Keep `.env` local only.

## Basic Health Checks
- Use `/status` for Ollama/CoinGecko/DB quick checks.
- Check logs for `event=api_error` and `event=crypto_worker_error`.
