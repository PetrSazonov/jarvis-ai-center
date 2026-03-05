# DAY_OS_MAP
## 1) Ядро Day OS: ключевые файлы
1. `bot.py`  
Точка сборки приложения: инициализация, регистрация роутеров, список команд, startup/shutdown lifecycle.

2. `handlers/ux_router.py`  
UX-контур дня: `/today`, `/week`, callback-логика `replan`, спринты `ux:sprint:*`, сторис-режим.

3. `handlers/commands.py`  
Командный контур для `/todo`, `/checkin`, `/subs`, `/settings`, `/mode`, `/confidence`, `/price`, `/weather`, `/status`, `/route`.

4. `handlers/chat.py`  
Контур обычного текста: routing, tool-first, LLM fallback, confidence-gate, memory context.

5. `services/routing.py`  
Единая политика маршрутизации: command/plain/date-time + правило сохранения истории.

6. `services/assistant_intent_service.py`  
LLM/heuristic intent-классификация и JSON-first валидация intent payload.

7. `services/assistant_tools_service.py`  
Tool-first ответы (`price/weather/digest/status/today/route/profile`) без свободной генерации фактов.

8. `services/llm_service.py`  
Сборка промпта, профили (`classifier/advisor/rewriter`), вызов Ollama.

9. `db.py`  
SQLite-ядро: todo/checkin/focus/user_settings/memory/conversation history + метрики для today/week.

10. `services/ux_service.py`  
Клавиатуры и inline-панели (`today_panel_markup`, story navigation, adaptive menu).

## 2) Доменные надстройки (не ядро Day OS)
1. `handlers/fitness.py` + `services/fitness_*`
2. `handlers/growth.py` + `services/growth_service.py`
3. `handlers/advanced_ops.py`
4. `services/digest_service.py`, `services/news_service.py`, `services/crypto_service.py`, `services/weather_service.py`
5. `services/gamification_service.py`

## 3) Связи между модулями (упрощённо)
`Telegram update -> Dispatcher(router) -> handler -> service -> DB/HTTP/Ollama -> response`

Day OS путь:
1. `/today`: `handlers/ux_router.py` -> `db.py` (todo/checkin) + fitness selector -> `services/ux_service.py`.
2. `/todo`: `handlers/commands.py` -> `db.py` (`todo_*`).
3. `focus`: `handlers/ux_router.py` callbacks -> `db.py` (`focus_session_*`).
4. `/checkin`: `handlers/commands.py` -> `db.py` (`daily_checkin_*`).
5. `replan`: callback в `handlers/ux_router.py` на базе текущих todo/checkin.
6. `/week`: `handlers/ux_router.py` -> `db.py` + `services/gamification_service.py` -> week screens.
7. `/decide`: `handlers/commands.py` LLM-guided -> `services/llm_service.py`.

## 4) Что перегружает основной путь
1. `handlers/commands.py` совмещает слишком много: core-команды, market/weather/status, profile/memory, subscriptions, LLM-guided команды.
2. `/focus` в core-цикле есть концептуально, но как команда фактически отключён (`focus_deprecated`), а живёт в callback-механике.
3. Weekly-контур раздвоен: `/week`, `/review week`, `/weekly`.
4. Командная поверхность в `bot.py` очень широкая для первого слоя (feature soup).
5. `known_commands` и `set_my_commands` содержат много экспериментальных пунктов, что ухудшает onboarding.

## 5) Минимальный рефакторинг (без переписывания архитектуры)
1. Упростить экспозицию команд: оставить first layer только `Core`, остальные через `Advanced` секцию `/menu`.
2. Восстановить `/focus` как тонкий мост в существующий sprint callback (без нового функционала).
3. Унифицировать weekly-путь: выбрать один canonical вход (`/week` + `/review week`), `/weekly` оставить как alias.
4. Вынести LLM-guided блок из `handlers/commands.py` в отдельный файл, например `handlers/day_os_ai.py`, сохранив поведение.
5. Оставить `handlers/commands.py` для deterministic core-операций (`/todo`, `/checkin`, `/settings`, `/status`, `/route`).

Это даст понятный продуктовый путь без большого rewrite и без удаления текущих модулей.
