# CODE_UNDERSTANDING_PATH
Цель: быстро понять проект как систему, а не как набор файлов.

## Порядок чтения (7-10 файлов)
1. `bot.py`
2. `core/settings.py`
3. `services/routing.py`
4. `handlers/ux_router.py`
5. `handlers/commands.py`
6. `handlers/chat.py`
7. `services/assistant_intent_service.py`
8. `services/assistant_tools_service.py`
9. `services/llm_service.py`
10. `db.py`

## Что понять в каждом файле
### 1) `bot.py`
1. Где создаются `Bot`, `Dispatcher`, `AppContext`.
2. В каком порядке подключаются роутеры.
3. Какие команды считаются известными (`known_commands`).
4. Где startup/shutdown и фоновые задачи.

Проверка себя:
1. Сможешь объяснить, почему именно `handlers/chat.py` стоит последним.

### 2) `core/settings.py`
1. Какие env-переменные обязательны.
2. Как формируется runtime-конфиг (`Settings`).
3. Где дефолты и валидация.

Проверка себя:
1. Сможешь запустить проект на новом устройстве только по `.env.example`.

### 3) `services/routing.py`
1. Как определяется тип входа: known command / unknown command / plain text / date-time.
2. Когда сохраняется история диалога.

Проверка себя:
1. Сможешь объяснить, почему unknown slash не должен загрязнять историю.

### 4) `handlers/ux_router.py`
1. Как устроены `/today` и `/week`.
2. Как обрабатываются callbacks (`replan`, `sprint`, mood, session).
3. Где собираются week/digest screens.

Проверка себя:
1. Сможешь пройти путь от кнопки `Replan` до текста ответа.

### 5) `handlers/commands.py`
1. Какие deterministic-команды тут живут (`/todo`, `/checkin`, `/price`, `/weather`, `/status`, `/route`).
2. Где находится LLM-guided блок команд.
3. Какие места перегружены.

Проверка себя:
1. Сможешь добавить новый подкомандный сценарий в `/todo` без поломки остальных.

### 6) `handlers/chat.py`
1. Как работает plain-text контур.
2. Где tool-first, где LLM fallback.
3. Как устроен confidence-gate и memory context.

Проверка себя:
1. Сможешь объяснить, почему сначала intent/tools, а не сразу генерация LLM.

### 7) `services/assistant_intent_service.py`
1. Эвристики vs LLM classifier.
2. JSON-first + validate + fallback.
3. Какие intent реально поддерживаются.

Проверка себя:
1. Сможешь назвать условия, когда классификатор вообще вызывается.

### 8) `services/assistant_tools_service.py`
1. Какие tool intent возвращают детерминированные ответы.
2. Как строятся ответы по рынку/погоде/статусу.
3. Где подключаются внешние API.

Проверка себя:
1. Сможешь показать, какой код отвечает за `tool_today`.

### 9) `services/llm_service.py`
1. Как строится prompt.
2. Какие профили вызова модели используются.
3. Где ограничение истории по размеру.

Проверка себя:
1. Сможешь поменять только профиль `classifier`, не ломая `advisor`.

### 10) `db.py`
1. Какие таблицы формируют Day OS (`todo_items`, `daily_checkins`, `focus_sessions`, `user_settings`, `conversations`).
2. Какие функции чтения/записи реально используются ядром.
3. Где индексы и почему они важны для скорости.

Проверка себя:
1. Сможешь проследить, какие функции `db.py` вызываются при `/today`.

## Путь одного запроса простым языком
1. Пользователь отправляет сообщение в Telegram.
2. `bot.py` передаёт update в aiogram dispatcher.
3. Router выбирает нужный handler (команда или текст).
4. Handler вызывает сервисы.
5. Сервисы берут данные из `db.py`, внешних API или Ollama.
6. Handler формирует ответ и отправляет его пользователю.

Короткая формула:
`Telegram -> router -> handler -> service -> DB/LLM/API -> response`.
