# PureCompanyBot

Telegram-бот "личный ассистент" на `aiogram + SQLite + локальная Ollama`.

## 1) Основная идея проекта
Сейчас проект эволюционирует в сторону **AI-центра как "Операционной системы дня"**:
- утром понять приоритет,
- днем поддержать выполнение,
- вечером зафиксировать результат,
- в конце недели скорректировать курс.

Ключевая проблема на текущем этапе: не баги, а распыление функционала.

## 2) Текущие подсистемы
1. **Core commands/router**: базовые команды, меню, статус, маршруты, todo/subs/checkin.
2. **Chat + LLM контур**: диалог, intent-классификация, confidence-gate, tool-first ответы.
3. **Data services**: рынок, погода, новости, дайджест, prewarm, scheduler.
4. **Fitness**: текстовые тренировки, дневной выбор, лог выполнения.
5. **Growth/Advanced ops**: score/plan/review + сценарные AI-команды.
6. **UX/gamification**: today/week панели, micro-sprints, boss/arena/rescue.
7. **Persistence layer (SQLite)**: все пользовательские данные и кэш.

## 3) Структура папок
```text
.
├─ bot.py                    # Точка входа, wiring роутеров и воркеров
├─ db.py                     # Схема и операции SQLite
├─ core/
│  ├─ settings.py            # Чтение и валидация .env
│  └─ logging_setup.py       # Логирование
├─ handlers/
│  ├─ commands.py            # Базовые команды и command center
│  ├─ chat.py                # Обычный LLM-чат
│  ├─ ux_router.py           # /today, /week, UX-панели
│  ├─ fitness.py             # /fit
│  ├─ growth.py              # /score, /plan, /review
│  └─ advanced_ops.py        # /boardroom, /redteam и др.
├─ services/
│  ├─ llm_service.py         # Вызовы Ollama + prompt-профили
│  ├─ assistant_intent_service.py
│  ├─ assistant_tools_service.py
│  ├─ digest_service.py
│  ├─ scheduler_service.py
│  └─ ...                    # weather/crypto/forex/fuel/ux и др.
├─ tests/                    # Unit-тесты
├─ scripts/                  # Bootstrap/run/check_secrets
├─ .githooks/                # pre-commit hook
├─ .env.example
└─ requirements.txt
```

## 4) Запуск локально (Windows и Mac)
### Windows (PowerShell)
```powershell
.\scripts\bootstrap.ps1
.\scripts\run.ps1
```

### macOS/Linux
```bash
chmod +x ./scripts/bootstrap.sh ./scripts/run.sh
./scripts/bootstrap.sh
./scripts/run.sh
```

Альтернатива вручную:
```bash
python -m venv venv
# Windows: .\venv\Scripts\activate
# Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # Windows: Copy-Item .env.example .env
python bot.py
```

## 5) Зависимости
`requirements.txt` содержит минимальный runtime-набор:
- `aiogram`
- `httpx`
- `aiohttp`
- `python-dotenv`

## 6) Настройка .env
1. Скопируйте `.env.example` -> `.env`.
2. Заполните минимум:
- `BOT_TOKEN`
- `OLLAMA_API_URL`
- `OLLAMA_MODEL`
3. Остальное можно оставить по умолчанию.

## 7) Защита секретов и Git
### Что сделано
- `.env` и локальные артефакты игнорируются через `.gitignore`.
- Добавлен сканер секретов: `scripts/check_secrets.py`.
- Добавлен pre-commit hook: `.githooks/pre-commit`.

### Как включить hook
```bash
git config core.hooksPath .githooks
```

### Ручная проверка перед пушем
```bash
python scripts/check_secrets.py
```

## 8) Поток запроса (как идет сообщение)
```text
Telegram update
  -> aiogram router (handlers/*)
  -> handler-логика
  -> service layer (tool-first / LLM / scheduler logic)
  -> DB/cache (db.py) и/или внешние API
  -> ответ пользователю
```

Для обычного чата:
```text
message -> chat router
  -> intent classifier (JSON)
  -> (если tool-intent) assistant_tools_service
  -> иначе advisor LLM
  -> confidence gate / clarify
  -> optional history persist
```

## 9) Ключевые команды сейчас
### Первый слой (Core-first)
- `/start`
- `/menu`
- `/today`
- `/todo`
- `/focus`
- `/checkin`
- `/week`
- `/review`
- `/decide`

### Канонический weekly flow
- `/week` — weekly dashboard
- `/review week` — weekly review
- `/weekly` — backward-compatible alias (мягкая переадресация)

### Операционные
- `/start`, `/menu`, `/help`, `/status`, `/reset`, `/clean`

### Инфо-блок
- `/price`, `/weather`, `/digest`, `/route`

### Дополнительно
- `/fit`, `/score`, `/plan`, `/boardroom`, `/redteam`, `/scenario`, `/legend`, и др.

## 10) Core vs Secondary модули
### Core (держать в фокусе)
- `handlers/ux_router.py` (today/week)
- `handlers/commands.py` (todo/checkin/mode/confidence)
- `handlers/chat.py` (LLM-контур)
- `services/assistant_intent_service.py`
- `services/assistant_tools_service.py`
- `services/llm_service.py`
- `db.py`

### Secondary (поддерживать, но не расширять первым приоритетом)
- `handlers/advanced_ops.py`
- `handlers/fitness.py`
- часть gamification внутри `handlers/ux_router.py`

## 11) Сокращение до ядра Day OS (статус)
### Core surface
- `/today`, `/todo`, `/focus`, `/checkin`, `/week`, `/review week`, `/decide`

### Спрятать глубже (через /help или command center)
- `/chronotwin`, `/boardroom`, `/legend`, `/life360`, `/futureme`, `/manual`, `/pro`, `/export`

### Временно заморозить (без удаления, без развития)
- экзотические сценарные команды и часть геймификации, не влияющие на daily execution loop.

## 12) Тесты
```bash
python -m unittest discover -s tests -p "test_*.py"
```

## 13) Multi-device workflow (рекомендуемый)
1. Один Git-репозиторий + единый `main`.
2. На каждом устройстве запускать `scripts/bootstrap.*`.
3. Перед коммитом: `python scripts/check_secrets.py` + тесты.
4. Разработка малыми PR/commit-блоками вокруг Day OS ядра.
