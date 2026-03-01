# Fitness Vault

`Fitness Vault` хранит тренировочные видео в приватном Telegram-канале и выдает их в личке через бота.

## 1) Подготовка канала

1. Создай приватный канал (например: `Fitness Vault`).
2. Добавь бота в админы канала.
3. Убедись, что бот может читать сообщения канала.

## 2) Настройка `.env`

Добавь:

```env
FITNESS_VAULT_CHAT_ID=-100xxxxxxxxxx
FITNESS_ADMIN_USER_ID=123456789
FITNESS_LOG_CHAT_ID=
```

- `FITNESS_VAULT_CHAT_ID` - ID приватного канала с видео.
- `FITNESS_ADMIN_USER_ID` - твой Telegram user_id (для админ-команд и уведомлений).
- `FITNESS_LOG_CHAT_ID` - опционально, чат для техлогов добавления.

## 3) Как узнать `FITNESS_VAULT_CHAT_ID`

1. Добавь бота в канал.
2. Отправь любое сообщение в канал.
3. Посмотри логи бота, ID канала приходит как `-100...`.

## 4) Как добавлять видео

1. Загружай видео (или `.mp4` документ) в канал.
2. Первая строка `caption` становится названием тренировки.
3. Бот автоматически добавляет запись в SQLite и шлет админу:
   `✅ Добавлено: <title> (id=<id>)`.

## 5) Команды в личке

- `/fit` - меню.
- `/fit list [page]` - список тренировок.
- `/fit show <id>` - карточка.
- `/fit send <id>` - отправить видео себе.
- `/fit random [tag]` - случайная тренировка.
- `/fit fav <id>` / `/fit unfav <id>` - избранное.
- `/fit done <id> [rpe] [comment]` - отметить выполнение.
- `/fit stats` - статистика за 7 дней.

Админ:

- `/fit edit <id> title=... tags=... equipment=... difficulty=... duration=22m notes=...`
- `/fit del <id>`

## 6) Важно про отправку видео

Источник всегда:

- `from_chat_id = FITNESS_VAULT_CHAT_ID`
- `message_id = vault_message_id`

Бот пытается отправить так:
1. `copyMessage`
2. `forwardMessage`
3. `sendVideo(file_id)` как fallback
