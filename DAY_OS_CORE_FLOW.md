# Day OS Core Flow
## Цель
Свести продукт к одному повторяемому циклу:
`сегодня -> задачи -> фокус -> фиксация -> корректировка -> неделя`.

Это ядро AI OS дня, потому что:
1. Даёт ежедневный рабочий ритм, а не набор разрозненных команд.
2. Создаёт измеримый контур улучшений (todo/focus/checkin/week).
3. Позволяет AI помогать в принятии решений (`/decide`) в контексте реального дня.

## Канонический цикл
1. Утро: `/today`  
Пользователь видит фокус дня, MIT-задачи и действие "что делать первым".

2. План: `/todo`  
Добавляет/чистит задачи, оставляет 1-3 ключевых.

3. Исполнение: `/focus`  
Запускает фокус-сессию/спринт.

4. Фиксация: `/checkin`  
Фиксирует done/carry/energy.

5. Корректировка: `replan`  
Быстрое перепланирование из `/today` при изменении контекста.

6. Недельный контур: `/week` + weekly review  
Подведение итогов и настройка следующей недели.

7. AI-усилитель: `/decide`  
Для сложных развилок и выбора следующего безопасного шага.

## Где цикл уже реализован, а где разорван
| Шаг | Реализация в коде | Статус |
|---|---|---|
| `/today` | `handlers/ux_router.py` (`today_command`, today callbacks) | Работает |
| `/todo` | `handlers/commands.py` (`basic_text_cmds`, `cmd:todo:*`) | Работает |
| `/focus` | В `handlers/commands.py` помечен deprecated; фактический фокус живёт в `handlers/ux_router.py` (`ux:sprint:*`) | Разорван |
| `/checkin` | `handlers/commands.py` (`basic_text_cmds`, `daily_checkin_upsert`) | Работает |
| `replan` | `handlers/ux_router.py` (`ux:today:replan:*`) | Работает как callback |
| `/week` | `handlers/ux_router.py` (`week_command`, week screens) | Работает |
| weekly review | `/review week` в `handlers/growth.py`, `/weekly` в `handlers/commands.py` (LLM-guided) | Раздвоено |
| `/decide` | `handlers/commands.py` (LLM-guided группа команд) | Работает, но слабо связан с ядром дня |

## Упрощённый вход для нового пользователя (1 минута)
Показать в первом слое только 7 сценариев:
1. `/today` — старт дня.
2. `/todo` — задачи.
3. `/focus` — рабочий блок.
4. `/checkin` — фиксация дня.
5. `/week` — неделя.
6. `/decide` — решение.
7. `/menu` — навигация.

Предложение для структуры `/menu` (без удаления существующего кода):
1. Раздел `Day OS`: `/today`, `/todo`, `/focus`, `/checkin`, `/week`, `/decide`.
2. Раздел `Data`: `/price`, `/weather`, `/digest`, `/route`, `/status`.
3. Раздел `Modules`: `/fit`, `/subs`.
4. Раздел `System`: `/settings`, `/mode`, `/confidence`, `/clean`, `/reset`, `/help`.
5. Всё остальное перенести в `Advanced` (не в первом экране).

## Ключевой вывод
Ядро уже в проекте есть, но пользовательский путь распадается из-за:
1. Де-факто выключенного `/focus`.
2. Дублирования weekly-контура (`/week`, `/weekly`, `/review week`).
3. Перегруженного первого слоя команд.
