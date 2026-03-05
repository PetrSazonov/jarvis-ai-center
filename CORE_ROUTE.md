# Core Route (Day OS)

Этот файл фиксирует линейный маршрут ядра без feature soup.

## 1) Точка входа
- Telegram: `bot.py` -> `handlers/*`
- Web: `app/api.py` endpoints

## 2) Единая доменная точка
- Команды Day OS проходят через `core/coordinator.py:handle_command(...)`.
- Coordinator роутит только доменные действия:
  - `today`
  - `tasks:list|add|done|delete`
  - `subs:list|add|delete|roll`

## 3) Доменный слой
- `core/day_os.py` — обзор дня (`/today`)
- `core/tasks.py` — задачи (`/todo` и связанные действия)
- `core/subs.py` — подписки (`/subs`)

## 4) Данные
- Все чтение/запись в SQLite централизовано в `db.py`.
- Core-модули не знают о Telegram/Web-обвязке, только о данных и правилах.

## 5) События
- `core/events.py` + event-коллектор в coordinator.
- Для dev/debug API можно вернуть events (`return_events=True`) без изменения UX.

## 6) Что считается чистым маршрутом
`Transport (Telegram/Web) -> coordinator -> core domain -> db -> response`

Это и есть опорный маршрут для дальнейшей разработки.
