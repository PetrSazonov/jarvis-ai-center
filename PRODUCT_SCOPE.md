# PRODUCT_SCOPE

Цель: сократить текущий проект до понятного ядра **Day OS** без удаления кода.

## 1) Core-команды (поверхность по умолчанию)
Это то, что пользователь должен видеть первым:
- `/today`
- `/todo`
- `/focus` (как целевой элемент; текущую legacy-реализацию вернуть в единый контур)
- `/checkin`
- `/week`
- `/decide`
- `replan` (через inline-кнопки в `/today`)
- `weekly review` (`/weekly` + `/review week`)

## 2) Спрятать глубже
Эти команды полезны, но не должны быть в главной поверхности:
- `/price`, `/weather`, `/digest`, `/route`
- `/score`, `/plan`, `/review` (кроме weekly review в ядре)
- `/profile`, `/timeline`, `/remember`, `/forget`
- `/fit`, `/subs`

## 3) Временно заморозить (без удаления)
Не расширять, пока не стабилизирован Day OS core-loop:
- `/chronotwin`, `/boardroom`, `/legend`
- `/life360`, `/futureme`, `/manual`, `/pro`, `/export`
- расширенные сценарные/экспериментальные команды из `advanced_ops`
- часть gamification-функций, не влияющих на ежедневное выполнение

## 4) Модули: core vs secondary
## Core modules
- `handlers/ux_router.py` (today/week/replan/mood/session)
- `handlers/chat.py` (диалог, confidence, intent-routing)
- `handlers/commands.py` (todo/checkin/mode/confidence + базовые ops)
- `services/assistant_intent_service.py`
- `services/assistant_tools_service.py`
- `services/llm_service.py`
- `db.py`

## Secondary modules
- `handlers/advanced_ops.py`
- `handlers/fitness.py`
- часть `services/digest_service.py` (расширенные форматы)
- геймификация в `services/gamification_service.py` и смежных слоях

## 5) Критерий "мы в фокусе"
Каждая новая задача должна отвечать "да" на вопрос:
> Улучшает ли это цикл: **today -> action -> checkin -> week review**?

Если нет — задача идет в backlog/secondary.
