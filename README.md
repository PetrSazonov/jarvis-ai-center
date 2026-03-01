# PureCompanyBot

Telegram bot on `aiogram 3` with:
- LLM responses via Ollama
- Crypto prices via CoinGecko
- Weather via Russian source (Gismeteo RSS for Moscow) with fallback
- FX via Central Bank of Russia (CBR)
- News via Russian RSS feeds (RBC/Lenta/RIA/Habr/vc)
- SQLite conversation history
- `/status` health checks
- Optional background `crypto_watcher`

## 1. Install

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Configure `.env`

```powershell
Copy-Item .env.example .env
```

Required:
- `BOT_TOKEN`
- `OLLAMA_API_URL`
- `OLLAMA_MODEL`

Recommended:
- `DEFAULT_LANG=ru`
- `STYLE_MODE=neutral` (`neutral` or `rogan_like`)
- `LOG_LEVEL=INFO`
- `ENABLE_CRYPTO_WATCHER=false`
- `PRICE_CURRENCIES=usd,eur,rub`
- `WEATHER_CITY=Moscow`
- `HOME_ADDRESS=<your home address>`
- `WORK_ADDRESS=<your work address>`
- `FITNESS_VAULT_CHAT_ID=-100xxxxxxxxxx`
- `FITNESS_ADMIN_USER_ID=<your_telegram_user_id>`
- `ENABLE_AUTO_DIGEST=true`
- `DIGEST_CHAT_ID=<your_telegram_chat_id>`
- `DIGEST_TIMES=07:00,14:00,21:00`
- `ENABLE_PREWARM=true`
- `PREWARM_INTERVAL_SECONDS=600`
- `BIRTH_DATE=15.12.1984`
- `MOTO_SEASON_START=04-15`
- `FEEDBACK_MIN_CHARS=280` (show 👍/👎 only for longer LLM replies)

## 3. Run

```powershell
python bot.py
```

## 4. Tests and checks

```powershell
python -m unittest discover -s tests -v
python -m compileall -q bot.py core services handlers crypto_watch.py db.py
```

Smoke checks in Telegram:
- `/help`
- `/status`
- `/price`
- `/weather`
- `/digest`
- `/route`
- `/fit`
- `/reset`

## 5. Windows auto-start (Task Scheduler)

1. Open `Task Scheduler` -> `Create Task`.
2. Trigger: `At startup`.
3. Action:
- Program: path to `venv\Scripts\python.exe`
- Arguments: `bot.py`
- Start in: project directory
4. Enable restart on failure.

## 6. Release checklist

1. `.env` is not committed.
2. Telegram token rotated if previously exposed.
3. Tests are green.
4. `/status` is OK for Ollama/CoinGecko/DB.
5. Unknown slash commands are not persisted in history.

## 7. Commands

- `/price` - BTC/ETH in multiple currencies (`PRICE_CURRENCIES`)
- `/weather` - current weather for `WEATHER_CITY`
- `/digest` - daily digest (crypto + weather + headlines)
- `/status` - service health (Core, Ollama, CoinGecko, CBR, DB)
- `/route` - open route in Yandex Maps (home/work)
- `/fit` - Fitness Vault (list/send/log workouts from private channel)
- `/todo` - personal tasks (`add/list/done/del`)
- `/today` - daily cockpit (top tasks + workout + weather)
- `/mission` - Mission Control dashboard (risk + plan B + next step)
- `/startnow` - anti-procrastination 5-minute launch
- `/focus` - noise-fight focus block with debrief
- `/autopilot` - toggle energy autopilot (`on|off`)
- `/simulate day` - digital twin day simulator
- `/premortem` - anti-failure analysis before key task
- `/negotiate` - 3-tone negotiation copilot + red flags
- `/life360` - weekly 6-zone life risk score
- `/goal` - 90-day goal decomposition
- `/drift` - anti-drift guard for strategic focus
- `/futureme` - future-self advisory note
- `/crisis` - 72h crisis mode (critical-only flow)
- `/manual` - personal operating manual snapshot
- `/decide` - Shadow Coach (risks/benefits/24h experiment)
- `/rule` - if-then automations (`add/list/del/on/off`)
- `/radar` - personal financial triggers (`add/list/check`)
- `/state` - 10-15 minute situational protocol (`stress|lowenergy|overload`)
- `/reflect` - concise evening reflection + rule for tomorrow
- `/weekly` - weekly review + 3 focuses for next week
- `/checkin` - evening check-in (`done/carry/energy`)
- `/settings` - interactive personal settings (lang/TZ/city/digest/quiet/style)
- `/export` - export CSV (`todo|fitness|subs|all`)
- `/pro` - Pro status and available premium capabilities
- `/profile` - show assistant memory profile
- `/timeline` - show memory timeline (all or by key)
- `/remember` - save user fact (`/remember city = Moscow`)
- `/forget` - delete saved fact (`/forget city`)
- `/reset` - clear conversation history
- `/help` - command list

## 8. Auto Digest

If `ENABLE_AUTO_DIGEST=true` and `DIGEST_CHAT_ID` is set, bot sends digest automatically at times from `DIGEST_TIMES` (default `07:00,14:00,21:00`).

Morning slot (`07:00`) includes personalized intro using `BIRTH_DATE`.
Digest also includes annual moto-season countdown based on `MOTO_SEASON_START`.

## 9. Performance & Fallback

- Commands `/price`, `/weather`, `/digest`, `/status` log `duration_ms` as `event=command_done`.
- External HTTP requests use shared async HTTP client (connection reuse).
- Fallback cache is used only when fresh enough (up to ~180 minutes) for user-facing data.
- Optional prewarm worker refreshes market/weather cache in background (`ENABLE_PREWARM`).
