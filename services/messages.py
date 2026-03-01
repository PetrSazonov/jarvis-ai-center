MESSAGES = {
    "ru": {
        "error_generic": "Произошла ошибка. Попробуйте еще раз чуть позже.",
        "error_service": "Сервис временно недоступен: {service}.",
        "history_reset": "История диалога очищена.",
        "clean_result": "Очистка выполнена. Удалено сообщений: {count}.",
        "clean_result_none": "Не удалось удалить сообщения. История бота очищена.",
        "start_welcome": (
            "<b>Панель управления</b>\n"
            "Основное: <code>/today</code>, <code>/digest</code>, <code>/fit</code>, <code>/subs</code>\n"
            "Нажмите кнопку ниже или введите команду."
        ),
        "start_back": "<b>С возвращением</b>\nГлавное меню готово.",
        "menu_enabled": "<b>Меню</b>\nГлавные действия на клавиатуре.",
        "prices_error": "Не удалось получить цены.",
        "prices_missing": "Не удалось извлечь данные по ценам.",
        "prices_fuel_na": "AI-95 Москва (средняя): н/д",
        "prices_partial_unavailable": "Частично недоступно: {services}",
        "help": (
            "<b>Быстрый старт</b>\n"
            "<code>/today</code>, <code>/digest</code>, <code>/fit</code>, <code>/subs</code>, "
            "<code>/price</code>, <code>/route</code>\n\n"
            "<b>Продуктивность</b>\n"
            "<code>/mission</code>, <code>/startnow</code>, <code>/checkin</code>, <code>/todo</code>, "
            "<code>/score</code>, <code>/plan</code>, <code>/review</code>, <code>/weekly</code>, <code>/settings</code>\n\n"
            "<b>AI-инструменты</b>\n"
            "<code>/simulate day</code>, <code>/premortem</code>, <code>/redteam</code>, <code>/scenario week</code>, "
            "<code>/legacy</code>, <code>/chronotwin simulate</code>, <code>/boardroom</code>, <code>/legend</code>, "
            "<code>/decide</code>, <code>/negotiate</code>, "
            "<code>/goal</code>, <code>/drift</code>, <code>/futureme</code>, <code>/crisis</code>, <code>/manual</code>\n\n"
            "<b>Сервис</b>\n"
            "<code>/status</code>, <code>/weather</code>, <code>/mode</code>, <code>/confidence</code>, "
            "<code>/clean</code>, <code>/reset</code>, <code>/menu</code>"
        ),
        "status_title": "<b>Статус сервисов</b>",
        "status_core_label": "Система",
        "status_services": "Сервисы",
        "status_cache_section": "Кэш",
        "status_cache_price": "Кэш рынка",
        "status_cache_weather": "Кэш погоды",
        "status_cache_empty": "нет",
        "status_cache_fresh": "свежий ({minutes}м)",
        "status_cache_stale": "устарел ({minutes}м)",
        "status_last_error": "Последние ошибки",
        "status_last_error_none": "нет",
        "status_ok": "OK",
        "status_fail": "FAIL",
        "now": "Сейчас: {time}",
        "today": "Сегодня: {date}",
        "weather_error": "Не удалось получить погоду.",
        "route_intro": "<b>Маршруты</b>\nДом, работа и ETA в один тап.",
        "route_eta_ask_location": "Отправьте геолокацию, и я рассчитаю время в пути.",
        "route_eta_done": "⏱ {title}: ~{minutes} мин (оценка без учета пробок в реальном времени).",
        "route_eta_failed": "Не удалось рассчитать время в пути. Попробуйте еще раз позже.",
        "route_eta_cleared": "Клавиатуру геолокации убрал.",
        "digest_bad_format": "Некорректный формат",
        "digest_unknown_action": "Неизвестное действие",
        "digest_expired": "Дайджест устарел",
        "digest_bad_data": "Ошибка данных",
        "digest_no_data": "Нет данных",
        "digest_more": "Подробнее",
        "digest_less": "Свернуть",
        "digest_open_workout": "🏋️ Открыть тренировку дня",
        "done_short": "Готово",
        "market_btc": "Биткоин",
        "market_eth": "Эфириум",
        "market_usd_rub": "Доллар/Рубль",
        "market_eur_rub": "Евро/Рубль",
        "market_fuel95": "AI-95 Москва (средняя)",
        "llm_unavailable": (
            "Сервис LLM временно недоступен. Попробуйте через 1-2 минуты. "
            "Пока доступны /price, /weather, /digest, /status, /route."
        ),
        "llm_low_quality": (
            "Похоже, ответ вышел некачественным. Дайте больше контекста в 1-2 предложениях, "
            "и я переформулирую точнее."
        ),
        "chat_fallback_here": "Да, я здесь. Можете продолжать.",
        "chat_fallback_improve": (
            "Лучший способ: давать мне четкие цели, контекст и обратную связь по качеству ответов. "
            "Тогда я буду полезнее именно под ваши задачи."
        ),
        "chat_fallback_structure": (
            "Сейчас нет доступа к LLM, но я могу помочь структурировать запрос. "
            "Сформулируйте цель, ограничения и желаемый результат, а я соберу краткий план."
        ),
        "fit_menu": "<b>Фитнес</b>\nВыберите действие кнопками ниже.",
        "fit_list_title": "Тренировки: страница {page} (всего {total})",
        "fit_no_workouts_seed": "Пока нет тренировок. Запустите /fit seed (admin), чтобы добавить шаблоны.",
        "fit_no_workouts": "Нет тренировок.",
        "fit_no_matching_workouts": "Нет подходящих тренировок.",
        "fit_not_found": "Тренировка не найдена.",
        "fit_unknown_command": "Неизвестная команда «Фитнес». Используйте /fit.",
        "fit_admin_only": "Команда доступна только администратору.",
        "fit_updated": "Обновлено ✅",
        "fit_update_failed": "Не удалось обновить тренировку.",
        "fit_seed_done": "Готово. Добавлено шаблонов: {count}.",
        "fit_deleted": "Удалено ✅",
        "fit_delete_not_found": "ID не найден.",
        "fit_done_saved": "Записал выполнение ✅\n🎯 Следующий шаг: {hint}",
        "fit_done_saved_short": "Записал ✅",
        "fit_next_hint": "🎯 Следующий шаг: {hint}",
        "fit_fav_added": "Добавлено в избранное ⭐",
        "fit_fav_removed": "Убрано из избранного.",
        "fit_stats_empty": "За последние 7 дней тренировок пока нет.",
        "fit_stats_title": "📈 За 7 дней: {count} тренировок",
        "fit_stats_streak": "🔥 Серия: {count} дн.",
        "fit_week_title": "🗓 Неделя тренировок",
        "fit_week_line": "{mark} {day}: {label}",
        "fit_repeat_empty": "Пока нет выполненных тренировок. Начни с /fit today.",
        "fit_bad_id": "Некорректный ID",
        "fit_no_message": "Нет сообщения",
        "fit_format_show": "Формат: /fit show <id>",
        "fit_format_send": "Формат: /fit send <id>",
        "fit_format_done": "Формат: /fit done <id> [rpe] [comment]",
        "fit_format_del": "Формат: /fit del <id>",
        "fit_format_fav": "Формат: /fit {action} <id>",
        "fit_plan_generating": "Собираю понятный план...",
        "fit_plan_failed": "Не удалось собрать AI-план, показываю базовый вариант.",
        "fit_vault_added": (
            "✅ Добавлено в Vault: {title} (id={workout_id})\n"
            "Подсказка: /fit edit {workout_id} title=... equipment=... difficulty=... duration=22m notes=..."
        ),
        "todo_help": (
            "🗂 Задачи:\n"
            "/todo add <текст> - добавить\n"
            "/todo list - показать активные\n"
            "/todo done <id> - отметить выполненной\n"
            "/todo del <id> - удалить"
        ),
        "todo_added": "Добавил задачу #{todo_id} ✅",
        "todo_empty": "Список задач пуст.",
        "todo_list_title": "🗂 Активные задачи:",
        "todo_done": "Задача #{todo_id} закрыта ✅",
        "todo_deleted": "Задача #{todo_id} удалена.",
        "todo_not_found": "Задача не найдена.",
        "todo_bad_format": "Формат: /todo add <текст> | /todo done <id> | /todo del <id>",
        "todo_add_prompt": "Напишите текст задачи следующим сообщением.",
        "focus_deprecated": "Фокус-таймер в боте выключен. Используйте ваш Pomodoro/Things.",
        "today_title": "🎯 Фокус дня",
        "screen_price_title": "📊 Рынок",
        "screen_weather_title": "🌦 Погода",
        "screen_digest_title": "📰 Дайджест",
        "screen_subs_title": "💳 Подписки",
        "today_todo_empty": "Нет активных задач. Добавьте через /todo add ...",
        "today_todo_title": "Топ-3 задачи:",
        "today_workout_title": "Тренировка дня:",
        "today_weather_title": "Погода:",
        "today_subs_title": "Подписка:",
        "today_subs_line": "{name} — осталось {days} дн.",
        "today_subs_line_overdue": "{name} — просрочено на {days} дн.",
        "today_subs_line_na": "{name} — дата {date}",
        "today_checkin_hint": "Вечером: /checkin done=<что сделал>; carry=<что перенести>; energy=<1-10>",
        "today_refresh": "Обновить",
        "today_open_workout": "Открыть тренировку",
        "checkin_help": (
            "Формат:\n"
            "/checkin done=<что сделал>; carry=<что перенести>; energy=<1-10>\n"
            "/checkin show - показать текущий чек-ин"
        ),
        "checkin_saved": "Чек-ин за сегодня сохранен ✅",
        "checkin_empty": "Чек-ин за сегодня пока пуст.",
        "checkin_show": "📝 Чек-ин за {date}\nСделал: {done}\nПеренос: {carry}\nЭнергия: {energy}",
        "checkin_bad_format": "Некорректный формат /checkin. Нажмите /checkin для примера.",
        "subs_help": "Формат: /subs add <name> <YYYY-MM-DD> <monthly|weekly|yearly|quarterly> | /subs list | /subs check | /subs roll <id> [n] | /subs del <id>",
        "subs_menu": "<b>Подписки</b>\nВыберите действие.",
        "subs_add_prompt": "Формат: Название | YYYY-MM-DD | monthly/weekly/yearly/quarterly",
        "subs_bad_date": "Некорректная дата. Формат: YYYY-MM-DD",
        "subs_bad_period": "Некорректный период. Допустимо: monthly, weekly, yearly, quarterly",
        "subs_added": "Подписка добавлена: #{sub_id}",
        "subs_deleted": "Подписка удалена: #{sub_id}",
        "subs_not_found": "Подписка не найдена.",
        "subs_empty": "Подписок пока нет.",
        "subs_list_title": "Подписки:",
        "subs_check_title": "Проверка подписок:",
        "subs_rolled": "Дата продлена: #{sub_id} -> {date}",
        "mode_help": "Формат: /mode fast | /mode normal | /mode precise",
        "mode_set": "Режим LLM: {mode} ✅",
        "mode_show": "Текущий режим LLM: {mode}",
        "confidence_help": "Формат: /confidence on | /confidence off",
        "confidence_set": "Показ confidence: {state} ✅",
        "confidence_show": "Показ confidence: {state}",
        "chat_clarify_prefix": "Нужно уточнение перед точным ответом:",
        "chat_confidence_line": "Уверенность: {score:.2f}",
        "remember_help": "Формат: /remember <ключ> = <значение>\nПример: /remember city = Москва",
        "remember_saved": "Запомнил: <b>{key}</b> ✅",
        "forget_help": "Формат: /forget <ключ>\nПример: /forget city",
        "forget_done": "Удалил из памяти: <b>{key}</b>",
        "forget_not_found": "Ключ не найден: <b>{key}</b>",
        "profile_title": "<b>Профиль памяти</b>",
        "profile_empty": "Память пока пустая. Используйте /remember.",
    },
    "en": {
        "error_generic": "Something went wrong. Please try again later.",
        "error_service": "Service is temporarily unavailable: {service}.",
        "history_reset": "Conversation history has been cleared.",
        "clean_result": "Cleanup complete. Messages deleted: {count}.",
        "clean_result_none": "Could not delete messages. Bot memory was cleared.",
        "start_welcome": (
            "<b>Control Panel</b>\n"
            "Core: <code>/today</code>, <code>/digest</code>, <code>/fit</code>, <code>/subs</code>\n"
            "Use buttons below or type a command."
        ),
        "start_back": "<b>Welcome back</b>\nMain menu is ready.",
        "menu_enabled": "<b>Menu</b>\nQuick sections are below.",
        "prices_error": "Could not fetch prices.",
        "prices_missing": "Could not retrieve price fields.",
        "prices_fuel_na": "AI-95 Moscow (avg): n/a",
        "prices_partial_unavailable": "Partially unavailable: {services}",
        "help": (
            "<b>Core</b>\n"
            "<code>/today</code> - daily focus\n"
            "<code>/mission</code> - mission dashboard\n"
            "<code>/digest</code> - digest\n"
            "<code>/fit</code> - workouts\n"
            "<code>/subs</code> - subscriptions\n"
            "<code>/startnow</code> - 5-minute start\n"
            "<code>/focus</code> - noise-fight block\n"
            "<code>/simulate day</code> - day simulator\n"
            "<code>/premortem</code> - pre-mortem goal\n"
            "<code>/redteam</code> - stress-test your plan\n"
            "<code>/scenario week</code> - week A/B/C scenarios\n"
            "<code>/legacy</code> - long-term progress by focus hours\n"
            "<code>/chronotwin simulate</code> - Peak/Real/Chaos day simulation\n"
            "<code>/boardroom</code> - 1y/5y/10y decision board\n"
            "<code>/legend</code> - Ordinary/Elite/Legendary day mode\n"
            "<code>/negotiate</code> - negotiation copilot\n"
            "<code>/life360</code> - 6-zone life risk\n"
            "<code>/goal</code> - 90-day goal decomposition\n"
            "<code>/drift</code> - anti-drift guard\n"
            "<code>/futureme</code> - future-self message\n"
            "<code>/crisis</code> - overload mode\n"
            "<code>/manual</code> - personal operating manual\n"
            "<code>/decide</code> - shadow coach\n"
            "<code>/rule</code> - if-then rules\n"
            "<code>/radar</code> - financial triggers\n"
            "<code>/state</code> - state protocol\n"
            "<code>/reflect</code> - evening reflection\n"
            "<code>/autopilot</code> - energy autopilot\n"
            "<code>/score</code> - growth score engine\n"
            "<code>/plan day|week|month|year</code> - planning cascade\n"
            "<code>/review day|week|month</code> - retro review\n"
            "<code>/weekly</code> - weekly review\n"
            "<code>/settings</code> - settings\n"
            "<code>/pro</code> - Pro status\n"
            "<code>/price</code> - market\n"
            "<code>/route</code> - route\n\n"
            "<b>More</b>\n"
            "<code>/todo</code>, <code>/checkin</code>, <code>/weather</code>, <code>/status</code>\n\n"
            "<b>System</b>\n"
            "<code>/mode</code>, <code>/confidence</code>, <code>/profile</code>, <code>/remember</code>, "
            "<code>/timeline</code>, <code>/forget</code>, <code>/export</code>, <code>/clean</code>, <code>/reset</code>, <code>/menu</code>"
        ),
        "status_title": "<b>Service Status</b>",
        "status_core_label": "Core",
        "status_services": "Services",
        "status_cache_section": "Cache",
        "status_cache_price": "Market cache",
        "status_cache_weather": "Weather cache",
        "status_cache_empty": "empty",
        "status_cache_fresh": "fresh ({minutes}m)",
        "status_cache_stale": "stale ({minutes}m)",
        "status_last_error": "Last errors",
        "status_last_error_none": "none",
        "status_ok": "OK",
        "status_fail": "FAIL",
        "now": "Now: {time}",
        "today": "Today: {date}",
        "weather_error": "Could not fetch weather.",
        "route_intro": "<b>Routes</b>\nHome, work and ETA in one tap.",
        "route_eta_ask_location": "Send your location and I will estimate travel time.",
        "route_eta_done": "⏱ {title}: ~{minutes} min (estimate without live traffic).",
        "route_eta_failed": "Could not estimate travel time. Please try again later.",
        "route_eta_cleared": "Location keyboard removed.",
        "digest_bad_format": "Invalid format",
        "digest_unknown_action": "Unknown action",
        "digest_expired": "Digest expired",
        "digest_bad_data": "Data error",
        "digest_no_data": "No data",
        "digest_more": "More",
        "digest_less": "Less",
        "digest_open_workout": "🏋️ Open workout of the day",
        "done_short": "Done",
        "market_btc": "Bitcoin",
        "market_eth": "Ethereum",
        "market_usd_rub": "USD/RUB",
        "market_eur_rub": "EUR/RUB",
        "market_fuel95": "AI-95 Moscow (avg)",
        "llm_unavailable": (
            "LLM service is temporarily unavailable. Please try again in 1-2 minutes. "
            "Available now: /price, /weather, /digest, /status, /route."
        ),
        "llm_low_quality": (
            "The answer quality seems low. Please add 1-2 sentences of context, "
            "and I will reformulate it more precisely."
        ),
        "chat_fallback_here": "Yes, I'm here. You can continue.",
        "chat_fallback_improve": (
            "Best way: give me clear goals, context, and feedback on answer quality. "
            "That makes me more useful for your tasks."
        ),
        "chat_fallback_structure": (
            "LLM is currently unavailable, but I can help structure your request. "
            "Share goal, constraints, and desired result, and I will draft a short plan."
        ),
        "fit_menu": "<b>Fitness</b>\nChoose an action with buttons.",
        "fit_list_title": "Workouts: page {page} (total {total})",
        "fit_no_workouts_seed": "No workouts yet. Run /fit seed (admin) to add presets.",
        "fit_no_workouts": "No workouts.",
        "fit_no_matching_workouts": "No matching workouts.",
        "fit_not_found": "Workout not found.",
        "fit_unknown_command": "Unknown Fitness command. Use /fit.",
        "fit_admin_only": "This command is admin-only.",
        "fit_updated": "Updated ✅",
        "fit_update_failed": "Could not update workout.",
        "fit_seed_done": "Done. Presets added: {count}.",
        "fit_deleted": "Deleted ✅",
        "fit_delete_not_found": "ID not found.",
        "fit_done_saved": "Logged ✅\n🎯 Next step: {hint}",
        "fit_done_saved_short": "Logged ✅",
        "fit_next_hint": "🎯 Next step: {hint}",
        "fit_fav_added": "Added to favorites ⭐",
        "fit_fav_removed": "Removed from favorites.",
        "fit_stats_empty": "No workouts in the last 7 days yet.",
        "fit_stats_title": "📈 Last 7 days: {count} workouts",
        "fit_stats_streak": "🔥 Streak: {count} days",
        "fit_week_title": "🗓 Training week",
        "fit_week_line": "{mark} {day}: {label}",
        "fit_repeat_empty": "No completed workouts yet. Start with /fit today.",
        "fit_bad_id": "Invalid ID",
        "fit_no_message": "No message",
        "fit_format_show": "Format: /fit show <id>",
        "fit_format_send": "Format: /fit send <id>",
        "fit_format_done": "Format: /fit done <id> [rpe] [comment]",
        "fit_format_del": "Format: /fit del <id>",
        "fit_format_fav": "Format: /fit {action} <id>",
        "fit_plan_generating": "Building a clear workout plan...",
        "fit_plan_failed": "Could not build AI plan, showing basic version.",
        "fit_vault_added": (
            "✅ Added to Vault: {title} (id={workout_id})\n"
            "Hint: /fit edit {workout_id} title=... equipment=... difficulty=... duration=22m notes=..."
        ),
        "todo_help": (
            "🗂 Tasks:\n"
            "/todo add <text> - add\n"
            "/todo list - show active\n"
            "/todo done <id> - mark done\n"
            "/todo del <id> - delete"
        ),
        "todo_added": "Added task #{todo_id} ✅",
        "todo_empty": "Task list is empty.",
        "todo_list_title": "🗂 Active tasks:",
        "todo_done": "Task #{todo_id} completed ✅",
        "todo_deleted": "Task #{todo_id} deleted.",
        "todo_not_found": "Task not found.",
        "todo_bad_format": "Format: /todo add <text> | /todo done <id> | /todo del <id>",
        "todo_add_prompt": "Send task text in the next message.",
        "focus_deprecated": "Focus timer in bot is disabled. Use your Pomodoro/Things workflow.",
        "today_title": "🎯 Focus of the day",
        "screen_price_title": "📊 Market",
        "screen_weather_title": "🌦 Weather",
        "screen_digest_title": "📰 Digest",
        "screen_subs_title": "💳 Subscriptions",
        "today_todo_empty": "No active tasks. Add with /todo add ...",
        "today_todo_title": "Top-3 tasks:",
        "today_workout_title": "Workout of the day:",
        "today_weather_title": "Weather:",
        "today_subs_title": "Subscription:",
        "today_subs_line": "{name} - {days} days left.",
        "today_subs_line_overdue": "{name} - overdue by {days} days.",
        "today_subs_line_na": "{name} - date {date}",
        "today_checkin_hint": "In the evening: /checkin done=<what done>; carry=<what moves>; energy=<1-10>",
        "today_refresh": "Refresh",
        "today_open_workout": "Open workout",
        "checkin_help": (
            "Format:\n"
            "/checkin done=<what done>; carry=<what moves>; energy=<1-10>\n"
            "/checkin show - show today's check-in"
        ),
        "checkin_saved": "Today's check-in saved ✅",
        "checkin_empty": "No check-in for today yet.",
        "checkin_show": "📝 Check-in for {date}\nDone: {done}\nCarry: {carry}\nEnergy: {energy}",
        "checkin_bad_format": "Invalid /checkin format. Use /checkin for example.",
        "subs_help": "Format: /subs add <name> <YYYY-MM-DD> <monthly|weekly|yearly|quarterly> | /subs list | /subs check | /subs roll <id> [n] | /subs del <id>",
        "subs_menu": "<b>Subscriptions</b>\nChoose an action.",
        "subs_add_prompt": "Format: Name | YYYY-MM-DD | monthly/weekly/yearly/quarterly",
        "subs_bad_date": "Invalid date. Format: YYYY-MM-DD",
        "subs_bad_period": "Invalid period. Use: monthly, weekly, yearly, quarterly",
        "subs_added": "Subscription added: #{sub_id}",
        "subs_deleted": "Subscription deleted: #{sub_id}",
        "subs_not_found": "Subscription not found.",
        "subs_empty": "No subscriptions yet.",
        "subs_list_title": "Subscriptions:",
        "subs_check_title": "Subscriptions check:",
        "subs_rolled": "Next date updated: #{sub_id} -> {date}",
        "mode_help": "Format: /mode fast | /mode normal | /mode precise",
        "mode_set": "LLM mode: {mode} ✅",
        "mode_show": "Current LLM mode: {mode}",
        "confidence_help": "Format: /confidence on | /confidence off",
        "confidence_set": "Confidence display: {state} ✅",
        "confidence_show": "Confidence display: {state}",
        "chat_clarify_prefix": "Need clarification before a precise answer:",
        "chat_confidence_line": "Confidence: {score:.2f}",
        "remember_help": "Format: /remember <key> = <value>\nExample: /remember city = Moscow",
        "remember_saved": "Saved: <b>{key}</b> ✅",
        "forget_help": "Format: /forget <key>\nExample: /forget city",
        "forget_done": "Removed from memory: <b>{key}</b>",
        "forget_not_found": "Key not found: <b>{key}</b>",
        "profile_title": "<b>Memory Profile</b>",
        "profile_empty": "Memory is empty. Use /remember.",
    },
}


def t(lang: str, key: str, **kwargs: object) -> str:
    selected = MESSAGES.get(lang, MESSAGES["ru"])
    template = selected.get(key, MESSAGES["ru"].get(key, key))
    return template.format(**kwargs)
