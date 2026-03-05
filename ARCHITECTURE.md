# ARCHITECTURE

Этот файл объясняет систему максимально простым языком.

## 0) Линейный core-route (главное)
Коротко:  
`Transport (Telegram/Web) -> coordinator -> core domain -> db -> response`

- Telegram-вход: `bot.py` + `handlers/*`
- Web-вход: `app/api.py`
- Единая доменная точка: `core/coordinator.py:handle_command(...)`
- Домен: `core/day_os.py`, `core/tasks.py`, `core/subs.py`
- Данные: `db.py`

Для короткой навигации есть отдельный файл: `CORE_ROUTE.md`.

## 1) Что делает `bot.py`
`bot.py` — это "дирижер":
1. читает `.env` и собирает `settings`;
2. поднимает логирование и БД (`init_db()`);
3. создает Telegram `Bot` и `Dispatcher`;
4. подключает все роутеры (`handlers/*`);
5. запускает background-задачи (автодайджест, prewarm, optional crypto worker);
6. стартует polling.

Сам `bot.py` почти не содержит бизнес-логики — он только связывает части системы.

## 2) Роль роутеров (`handlers/*`)
Роутер = входная точка пользовательских команд/сообщений.

- `handlers/commands.py`: базовые команды (`/price`, `/weather`, `/status`, `/route`, `/todo`, `/subs`, `/checkin`, `/mode`, `/confidence`).
- `handlers/chat.py`: обычные текстовые сообщения, LLM-диалог и intent-routing.
- `handlers/ux_router.py`: UX-панели `/today`, `/week`, спринты, кнопки replan/mood/session.
- `handlers/fitness.py`: фитнес-меню `/fit`.
- `handlers/growth.py`: детерминированные `/score`, `/plan`, `/review`.
- `handlers/advanced_ops.py`: продвинутые AI-команды (`/boardroom`, `/redteam`, `/scenario`, etc.).

## 3) Роль сервисов (`services/*`)
Сервис = "чистая" логика без Telegram-обвязки.

Примеры:
- `llm_service.py`: как строить prompt и как вызывать Ollama.
- `assistant_intent_service.py`: AI-классификация намерения пользователя в JSON.
- `assistant_tools_service.py`: tool-first ответы (рынок/погода/дайджест/статус/route/profile).
- `digest_service.py`: сборка дайджеста.
- `scheduler_service.py`: авто-дайджест и prewarm-кеш.
- `weather/crypto/forex/fuel` сервисы: конкретные внешние источники данных.

## 4) Роль `db.py`
`db.py` — единая точка для SQLite:
- создает таблицы (`init_db`),
- хранит/читает данные пользователя,
- хранит кэш,
- обслуживает todo/checkin/subs/fitness/memory/focus/reflections/decision journal.

Важно: если нужны данные из БД, лучше добавлять функцию в `db.py`, а не писать SQL в роутерах.

## 5) Как работает LLM-контур
Основной путь в `handlers/chat.py`:
1. Пришел текст пользователя.
2. `determine_route` решает: команда/обычный текст/дата-время и т.д.
3. Для обычного текста может вызываться AI intent classifier (`assistant_intent_service`).
4. Если intent инструментальный (например, погода/цены) — вызывается tool-first слой (`assistant_tools_service`) без "свободной генерации".
5. Иначе строится prompt и вызывается advisor-модель (`call_ollama`).
6. Проверяется качество/уверенность (confidence gate), при низкой уверенности бот задает уточняющий вопрос.
7. История и память обновляются по правилам роутинга.

## 6) Где tool-first логика
Tool-first означает: сначала факты от сервисов, потом формулировка.

Ключевые места:
- `services/assistant_tools_service.py`
- инструментальные ответы в `handlers/commands.py` (`/price`, `/weather`, `/status`, `/digest`)

Это снижает галлюцинации в фактических ответах.

## 7) Где хранится память
Есть 3 уровня:
1. `conversations` — история диалога.
2. `assistant_memory` — текущие факты о пользователе (ключ-значение).
3. `assistant_memory_timeline` — история изменений памяти (для контроля и аудита).

## 8) Какие места сейчас перегружены
1. **Поверхность команд**: слишком много команд одинакового класса важности.
2. **`handlers/commands.py`**: большой файл с разнородной логикой (несмотря на частичную декомпозицию).
3. **Смысловой фокус продукта**: много фич, но главный цикл Day OS не всегда в приоритете.

## 9) Что считать будущим ядром Day OS
Рабочее ядро на ближайший этап:
- `/today`
- `/todo`
- `/focus`
- `/checkin`
- `/week`
- `/decide`
- `replan` (кнопка в today)
- `weekly review` (`/weekly`, `/review week`)

Это цикл: **План дня -> Выполнение -> Фиксация -> Недельная коррекция**.

## 10) Рекомендованная граница модулей
### Core modules
- `handlers/chat.py`
- `handlers/ux_router.py`
- `handlers/commands.py` (только часть Day OS)
- `services/assistant_intent_service.py`
- `services/assistant_tools_service.py`
- `services/llm_service.py`
- `db.py`

### Secondary modules
- `handlers/advanced_ops.py`
- `handlers/fitness.py`
- часть gamification в `handlers/ux_router.py`

## 11) Принцип следующих изменений
Не добавлять новые фичи, пока не стабилизирован core loop Day OS:
- меньше поверхностных команд,
- больше прозрачности в сценарии "сегодня/неделя",
- понятные метрики выполнения.
