# COMMAND_AUDIT
Источник аудита: `bot.py` (`set_my_commands`, `known_commands`) + активные роутеры в `handlers/*`.

## Принцип классификации
1. `Core` — без них ломается цикл Day OS.
2. `Secondary` — полезные доменные модули и операционные команды.
3. `Experimental / Frozen` — перегружают первый слой, пока не критичны для Day OS.

## Core
1. `/start`
2. `/menu`
3. `/today`
4. `/todo`
5. `/focus` (сейчас требуется восстановить как явную команду, сейчас фактически legacy)
6. `/checkin`
7. `/week`
8. `/review` (как weekly review через `/review week`)
9. `/decide`

## Secondary
1. `/help`
2. `/status`
3. `/settings`
4. `/mode`
5. `/confidence`
6. `/digest`
7. `/price`
8. `/weather`
9. `/route`
10. `/fit`
11. `/subs`
12. `/session`
13. `/score`
14. `/plan`
15. `/profile`
16. `/remember`
17. `/forget`
18. `/timeline`
19. `/clean`
20. `/reset`

## Experimental / Frozen (убрать из первого слоя)
1. `/mission`
2. `/startnow`
3. `/autopilot`
4. `/simulate`
5. `/premortem`
6. `/negotiate`
7. `/life360`
8. `/goal`
9. `/drift`
10. `/futureme`
11. `/crisis`
12. `/manual`
13. `/rule`
14. `/radar`
15. `/state`
16. `/reflect`
17. `/weekly` (как отдельный LLM-flow; оставить алиасом позже, но убрать из first layer)
18. `/export`
19. `/pro`
20. `/boss`
21. `/arena`
22. `/rescue`
23. `/recap`
24. `/chronotwin`
25. `/boardroom`
26. `/legend`
27. `/redteam`
28. `/scenario`
29. `/legacy`

## Что это значит для интерфейса сейчас
1. В Telegram command menu оставить только `Core + часть Secondary` (6-8 видимых действий).
2. `Experimental / Frozen` не удалять, но скрыть из первой навигации и из первого экрана `/menu`.
3. `/weekly` не удалять из кода, но перестать показывать как главный путь, пока не будет унифицирован weekly-контур.
