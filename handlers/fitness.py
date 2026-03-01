import re
from datetime import date, datetime, timedelta

from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from db import (
    delete_cache_prefix,
    fitness_add_session,
    fitness_current_streak_days,
    fitness_create_workout,
    fitness_delete_workout,
    fitness_get_progress,
    fitness_get_latest_session_for_user,
    fitness_get_random_workout,
    fitness_get_recent_rpe,
    fitness_get_workout,
    fitness_is_favorite,
    fitness_list_workouts,
    fitness_remove_favorite,
    fitness_seed_presets,
    fitness_set_favorite,
    fitness_stats_recent,
    fitness_update_workout,
    fitness_upsert_progress,
    fitness_week_done_dates,
)
from handlers.context import AppContext
from services.fitness_plan_service import (
    build_ai_workout_plan as svc_build_ai_workout_plan,
    fmt_minutes as svc_fmt_minutes,
    pick_workout_of_day as svc_pick_workout_of_day,
    program_summary as svc_program_summary,
    program_week as svc_program_week,
    render_plain_workout_plan as svc_render_plain_workout_plan,
    weekday_plan_slot as svc_weekday_plan_slot,
)
from services.fitness_progress_service import (
    next_hint_by_context as svc_next_hint_by_context,
    next_hint_by_rpe as svc_next_hint_by_rpe,
)
from services.fitness_view_service import (
    list_markup as svc_list_markup,
    menu_markup as svc_menu_markup,
    workout_actions as svc_workout_actions,
    workout_card as svc_workout_card,
)
from services.messages import t


LIST_PAGE_SIZE = 10


def _is_admin(ctx: AppContext, user_id: int | None) -> bool:
    return bool(user_id and ctx.settings.fitness_admin_user_id and user_id == ctx.settings.fitness_admin_user_id)


def _parse_workout_row(row) -> dict:
    return {
        "id": int(row[0]),
        "title": str(row[1]),
        "tags": str(row[2] or ""),
        "equipment": str(row[3] or ""),
        "difficulty": int(row[4] or 2),
        "duration_sec": int(row[5] or 0),
        "notes": str(row[6] or ""),
        "vault_chat_id": int(row[7]),
        "vault_message_id": int(row[8]),
        "file_id": str(row[9] or ""),
        "created_at": str(row[10]),
    }


def _program_week(today: date | None = None) -> int:
    return svc_program_week(today)


def _weekday_plan_slot(today: date | None = None) -> tuple[str, str]:
    return svc_weekday_plan_slot(today)


def _program_summary(today: date | None = None) -> str:
    return svc_program_summary(today)


def _pick_workout_of_day(today: date | None = None):
    return svc_pick_workout_of_day(today)


def _fmt_minutes(duration_sec: int) -> str:
    return svc_fmt_minutes(duration_sec)

def _workout_card(workout: dict) -> str:
    return svc_workout_card(workout)


def _next_hint_by_rpe(rpe: int | None) -> str:
    return svc_next_hint_by_rpe(rpe)


def _next_hint_by_context(rpe: int | None, recent_rpe: list[int | None]) -> str:
    return svc_next_hint_by_context(rpe, recent_rpe)


def _workout_card_for_user(user_id: int, workout: dict) -> str:
    next_hint = None
    if user_id > 0:
        progress = fitness_get_progress(user_id=user_id, workout_id=workout["id"])
        if progress:
            next_hint = str(progress[2] or "").strip() or None
    return svc_workout_card(workout, next_hint=next_hint)


def _render_plain_workout_plan(workout: dict) -> str:
    return svc_render_plain_workout_plan(workout)


async def _build_ai_workout_plan(ctx: AppContext, workout: dict) -> str:
    return await svc_build_ai_workout_plan(ctx.settings, workout)


async def _safe_workout_plan(ctx: AppContext, workout: dict, user_id: int | None = None) -> tuple[str, bool]:
    try:
        plan_text = await _build_ai_workout_plan(ctx, workout)
        if not plan_text.strip():
            return _render_plain_workout_plan(workout), False
        return plan_text, True
    except Exception as exc:
        ctx.logger.warning(
            "event=fit_plan_build_failed user_id=%s workout_id=%s error=%s",
            user_id or 0,
            workout.get("id"),
            exc.__class__.__name__,
        )
        return _render_plain_workout_plan(workout), False


def _workout_actions(workout_id: int, is_favorite: bool):
    return svc_workout_actions(workout_id, is_favorite)


def _plan_actions(workout_id: int, is_favorite: bool) -> InlineKeyboardMarkup:
    fav_text = "✖ Убрать из избранного" if is_favorite else "⭐ В избранное"
    fav_action = "unfav" if is_favorite else "fav"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⬅️ Назад", callback_data=f"fit:show:{workout_id}")],
            [InlineKeyboardButton(text="✅ Сделал", callback_data=f"fit:done:{workout_id}")],
            [InlineKeyboardButton(text=fav_text, callback_data=f"fit:{fav_action}:{workout_id}")],
            [InlineKeyboardButton(text="➡️ Следующая", callback_data="fit:next:0")],
        ]
    )


def _menu_markup():
    return svc_menu_markup()


def _list_markup(page: int, total: int, rows):
    workouts = [_parse_workout_row(row) for row in rows]
    return svc_list_markup(page, total, workouts, LIST_PAGE_SIZE)


def _week_overview_text(lang: str, user_id: int) -> str:
    now = datetime.now()
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    week_end = week_start + timedelta(days=7)
    done_days = set(
        fitness_week_done_dates(
            user_id=user_id,
            week_start_iso=week_start.isoformat(timespec="seconds"),
            week_end_iso=week_end.isoformat(timespec="seconds"),
        )
    )
    day_map = [
        ("Пн", "Сила верх"),
        ("Вт", "Восстановление"),
        ("Ср", "Ноги и корпус"),
        ("Чт", "Восстановление"),
        ("Пт", "Кондиция и берпи"),
        ("Сб", "Восстановление"),
        ("Вс", "Восстановление"),
    ]
    lines = [t(lang, "fit_week_title")]
    for idx, (day, label) in enumerate(day_map):
        day_iso = (week_start + timedelta(days=idx)).date().isoformat()
        mark = "✅" if day_iso in done_days else "⬜"
        lines.append(t(lang, "fit_week_line", mark=mark, day=day, label=label))
    return "\n".join(lines)


def _parse_duration_to_seconds(raw: str) -> int:
    value = raw.strip().lower()
    if value.endswith("m"):
        mins = int(value[:-1].strip())
        return max(0, mins * 60)
    if value.endswith("min"):
        mins = int(value[:-3].strip())
        return max(0, mins * 60)
    return max(0, int(value))


def _parse_fit_edit(text: str) -> tuple[int, dict]:
    payload = (text or "").strip()
    m = re.match(r"^/fit\s+edit\s+(\d+)\s+(.+)$", payload, flags=re.IGNORECASE | re.DOTALL)
    if not m:
        raise ValueError("Формат: /fit edit <id> title=... tags=... equipment=... difficulty=... duration=... notes=...")
    workout_id = int(m.group(1))
    rest = m.group(2).strip()
    key_pattern = re.compile(r"\b(title|tags|equipment|difficulty|duration|notes)\s*=", flags=re.IGNORECASE)
    matches = list(key_pattern.finditer(rest))
    if not matches:
        raise ValueError("Не найдено полей для обновления.")

    updates: dict = {}
    for i, match in enumerate(matches):
        key = match.group(1).lower()
        value_start = match.end()
        value_end = matches[i + 1].start() if i + 1 < len(matches) else len(rest)
        raw_value = rest[value_start:value_end].strip()
        if not raw_value:
            continue
        if key == "difficulty":
            updates["difficulty"] = max(1, min(5, int(raw_value)))
        elif key == "duration":
            updates["duration_sec"] = _parse_duration_to_seconds(raw_value)
        else:
            updates[key] = raw_value
    if not updates:
        raise ValueError("Не удалось распарсить значения полей.")
    return workout_id, updates


def _extract_caption_title(caption: str | None) -> str:
    if not caption:
        return f"Workout {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    first_line = caption.strip().splitlines()[0].strip()
    return first_line or f"Workout {datetime.now().strftime('%Y-%m-%d %H:%M')}"


def build_fitness_router(ctx: AppContext) -> Router:
    router = Router(name="fitness")
    router.message.filter(F.chat.type == "private")

    @router.channel_post()
    async def on_vault_channel_post(post: types.Message) -> None:
        # Keep channel sync for future video mode, but current UX is text-first.
        vault_chat_id = ctx.settings.fitness_vault_chat_id
        if not vault_chat_id or post.chat.id != vault_chat_id:
            return

        file_id = ""
        if post.video:
            file_id = post.video.file_id
        elif post.document:
            mime = (post.document.mime_type or "").lower()
            file_name = (post.document.file_name or "").lower()
            if mime.startswith("video/") or file_name.endswith(".mp4"):
                file_id = post.document.file_id
        if not file_id:
            return

        title = _extract_caption_title(post.caption)
        workout_id = fitness_create_workout(
            title=title,
            tags="",
            equipment="",
            difficulty=2,
            duration_sec=0,
            notes="",
            vault_chat_id=post.chat.id,
            vault_message_id=post.message_id,
            file_id=file_id,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        if not workout_id:
            return

        admin_id = ctx.settings.fitness_admin_user_id
        if admin_id:
            try:
                await ctx.bot.send_message(
                    admin_id,
                    t(
                        ctx.settings.default_lang,
                        "fit_vault_added",
                        title=title,
                        workout_id=workout_id,
                    ),
                )
            except Exception as exc:
                ctx.logger.warning("event=fit_admin_notify_failed workout_id=%s error=%s", workout_id, exc.__class__.__name__)

    @router.message(Command("fit"))
    async def fit_entry(message: types.Message) -> None:
        text = (message.text or "").strip()
        user_id = message.from_user.id if message.from_user else None
        is_admin = _is_admin(ctx, user_id)
        parts = text.split(maxsplit=3)
        sub = parts[1].lower() if len(parts) > 1 else ""

        if not sub:
            await message.reply(
                t(ctx.settings.default_lang, "fit_menu"),
                reply_markup=_menu_markup(),
                parse_mode="HTML",
            )
            return

        if sub == "list":
            page = 1
            if len(parts) > 2 and parts[2].isdigit():
                page = max(1, int(parts[2]))
            rows, total = fitness_list_workouts(page=page, limit=LIST_PAGE_SIZE)
            if not rows:
                await message.reply(t(ctx.settings.default_lang, "fit_no_workouts_seed"))
                return
            await message.reply(
                t(ctx.settings.default_lang, "fit_list_title", page=page, total=total),
                reply_markup=_list_markup(page, total, rows),
            )
            return

        if sub == "show":
            if len(parts) < 3 or not parts[2].isdigit():
                await message.reply(t(ctx.settings.default_lang, "fit_format_show"))
                return
            workout_row = fitness_get_workout(int(parts[2]))
            if not workout_row:
                await message.reply(t(ctx.settings.default_lang, "fit_not_found"))
                return
            workout = _parse_workout_row(workout_row)
            is_fav = fitness_is_favorite(user_id=user_id or 0, workout_id=workout["id"])
            await message.reply(_workout_card_for_user(user_id or 0, workout), reply_markup=_workout_actions(workout["id"], is_fav))
            return

        if sub in {"send", "text", "plan_text"}:
            if len(parts) < 3 or not parts[2].isdigit():
                await message.reply(t(ctx.settings.default_lang, "fit_format_send"))
                return
            workout_row = fitness_get_workout(int(parts[2]))
            if not workout_row:
                await message.reply(t(ctx.settings.default_lang, "fit_not_found"))
                return
            workout = _parse_workout_row(workout_row)
            plan_text, ok = await _safe_workout_plan(ctx, workout, user_id=user_id)
            if not ok:
                await message.reply(t(ctx.settings.default_lang, "fit_plan_failed"))
            await message.reply(plan_text)
            return

        if sub == "random":
            tag = parts[2].strip().lower() if len(parts) > 2 else None
            picked_by_plan = False
            if not tag:
                _day_name, suggested_tag = _weekday_plan_slot()
                tag = suggested_tag
                picked_by_plan = True
            workout_row = fitness_get_random_workout(tag=tag)
            if not workout_row and picked_by_plan:
                workout_row = fitness_get_random_workout()
            if not workout_row:
                await message.reply(t(ctx.settings.default_lang, "fit_no_matching_workouts"))
                return
            workout = _parse_workout_row(workout_row)
            is_fav = fitness_is_favorite(user_id=user_id or 0, workout_id=workout["id"])
            prefix = _program_summary() + "\n\n" if picked_by_plan else ""
            await message.reply(prefix + _workout_card_for_user(user_id or 0, workout), reply_markup=_workout_actions(workout["id"], is_fav))
            return

        if sub == "today":
            workout_row = _pick_workout_of_day()
            if not workout_row:
                await message.reply(t(ctx.settings.default_lang, "fit_no_matching_workouts"))
                return
            workout = _parse_workout_row(workout_row)
            is_fav = fitness_is_favorite(user_id=user_id or 0, workout_id=workout["id"])
            await message.reply(
                _program_summary() + "\n\n" + _workout_card_for_user(user_id or 0, workout),
                reply_markup=_workout_actions(workout["id"], is_fav),
            )
            return

        if sub == "plan":
            await message.reply(_program_summary())
            return

        if sub == "week":
            await message.reply(_week_overview_text(ctx.settings.default_lang, user_id or 0))
            return

        if sub == "repeat":
            latest = fitness_get_latest_session_for_user(user_id or 0)
            if not latest:
                await message.reply(t(ctx.settings.default_lang, "fit_repeat_empty"))
                return
            workout_row = fitness_get_workout(int(latest[0]))
            if not workout_row:
                await message.reply(t(ctx.settings.default_lang, "fit_not_found"))
                return
            workout = _parse_workout_row(workout_row)
            is_fav = fitness_is_favorite(user_id=user_id or 0, workout_id=workout["id"])
            await message.reply(
                _workout_card_for_user(user_id or 0, workout),
                reply_markup=_workout_actions(workout["id"], is_fav),
            )
            return

        if sub in {"fav", "unfav"}:
            if len(parts) < 3 or not parts[2].isdigit():
                await message.reply(t(ctx.settings.default_lang, "fit_format_fav", action=sub))
                return
            workout_id = int(parts[2])
            if not fitness_get_workout(workout_id):
                await message.reply(t(ctx.settings.default_lang, "fit_not_found"))
                return
            if sub == "fav":
                fitness_set_favorite(user_id=user_id or 0, workout_id=workout_id)
                await message.reply(t(ctx.settings.default_lang, "fit_fav_added"))
            else:
                fitness_remove_favorite(user_id=user_id or 0, workout_id=workout_id)
                await message.reply(t(ctx.settings.default_lang, "fit_fav_removed"))
            return

        if sub == "done":
            tokens = text.split(maxsplit=4)
            if len(tokens) < 3 or not tokens[2].isdigit():
                await message.reply(t(ctx.settings.default_lang, "fit_format_done"))
                return
            workout_id = int(tokens[2])
            if not fitness_get_workout(workout_id):
                await message.reply(t(ctx.settings.default_lang, "fit_not_found"))
                return
            rpe = None
            comment = None
            if len(tokens) >= 4:
                if tokens[3].isdigit():
                    rpe = max(1, min(10, int(tokens[3])))
                    if len(tokens) == 5:
                        comment = tokens[4].strip()
                else:
                    comment = " ".join(tokens[3:]).strip()
            fitness_add_session(
                user_id=user_id or 0,
                workout_id=workout_id,
                done_at=datetime.now().isoformat(timespec="seconds"),
                rpe=rpe,
                comment=comment or None,
            )
            recent_rpe = fitness_get_recent_rpe(user_id=user_id or 0, workout_id=workout_id, limit=3)
            hint = _next_hint_by_context(rpe, recent_rpe)
            fitness_upsert_progress(
                user_id=user_id or 0,
                workout_id=workout_id,
                last_rpe=rpe,
                last_comment=comment or None,
                next_hint=hint,
                updated_at=datetime.now().isoformat(timespec="seconds"),
            )
            await message.reply(t(ctx.settings.default_lang, "fit_done_saved", hint=hint))
            return

        if sub == "stats":
            since = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
            total, rows = fitness_stats_recent(user_id=user_id or 0, since_iso=since)
            if total == 0:
                await message.reply(t(ctx.settings.default_lang, "fit_stats_empty"))
                return
            streak = fitness_current_streak_days(user_id=user_id or 0)
            lines = [
                t(ctx.settings.default_lang, "fit_stats_title", count=total),
                t(ctx.settings.default_lang, "fit_stats_streak", count=streak),
            ]
            for workout_id, title, done_at, _tags in rows[:10]:
                short_dt = str(done_at).replace("T", " ")[:16]
                lines.append(f"- #{workout_id} {title} ({short_dt})")
            await message.reply("\n".join(lines))
            return

        if sub == "edit":
            if not is_admin:
                await message.reply(t(ctx.settings.default_lang, "fit_admin_only"))
                return
            try:
                workout_id, updates = _parse_fit_edit(text)
            except Exception as exc:
                await message.reply(str(exc))
                return
            ok = fitness_update_workout(workout_id, updates)
            if ok:
                delete_cache_prefix(f"fit_plan:{workout_id}:")
            await message.reply(
                t(ctx.settings.default_lang, "fit_updated")
                if ok
                else t(ctx.settings.default_lang, "fit_update_failed")
            )
            return

        if sub == "seed":
            if not is_admin:
                await message.reply(t(ctx.settings.default_lang, "fit_admin_only"))
                return
            seed_chat_id = ctx.settings.fitness_vault_chat_id or -1000000000000
            inserted = fitness_seed_presets(vault_chat_id=seed_chat_id)
            await message.reply(t(ctx.settings.default_lang, "fit_seed_done", count=inserted))
            return

        if sub == "del":
            if not is_admin:
                await message.reply(t(ctx.settings.default_lang, "fit_admin_only"))
                return
            if len(parts) < 3 or not parts[2].isdigit():
                await message.reply(t(ctx.settings.default_lang, "fit_format_del"))
                return
            workout_id = int(parts[2])
            ok = fitness_delete_workout(workout_id)
            if ok:
                delete_cache_prefix(f"fit_plan:{workout_id}:")
            await message.reply(
                t(ctx.settings.default_lang, "fit_deleted")
                if ok
                else t(ctx.settings.default_lang, "fit_delete_not_found")
            )
            return

        await message.reply(t(ctx.settings.default_lang, "fit_unknown_command"))

    @router.callback_query(F.data.startswith("fit:"))
    async def fit_callback(callback: CallbackQuery) -> None:
        raw = callback.data or ""
        parts = raw.split(":")
        if len(parts) != 3:
            await callback.answer(t(ctx.settings.default_lang, "digest_bad_format"), show_alert=False)
            return
        _, action, arg = parts
        user_id = callback.from_user.id if callback.from_user else 0

        if action == "menu":
            if callback.message:
                await callback.message.edit_text(
                    t(ctx.settings.default_lang, "fit_menu"),
                    reply_markup=_menu_markup(),
                    parse_mode="HTML",
                )
            await callback.answer()
            return

        if action == "today":
            workout_row = _pick_workout_of_day()
            if not workout_row:
                await callback.answer(t(ctx.settings.default_lang, "fit_no_workouts"), show_alert=False)
                return
            workout = _parse_workout_row(workout_row)
            is_fav = fitness_is_favorite(user_id=user_id, workout_id=workout["id"])
            if callback.message:
                await callback.message.edit_text(
                    _program_summary() + "\n\n" + _workout_card_for_user(user_id, workout),
                    reply_markup=_workout_actions(workout["id"], is_fav),
                )
            await callback.answer()
            return

        if action == "plan":
            if callback.message:
                await callback.message.edit_text(_program_summary(), reply_markup=_menu_markup())
            await callback.answer()
            return

        if action == "week":
            if callback.message:
                await callback.message.edit_text(_week_overview_text(ctx.settings.default_lang, user_id), reply_markup=_menu_markup())
            await callback.answer()
            return

        if action == "repeat":
            latest = fitness_get_latest_session_for_user(user_id)
            if not latest:
                await callback.answer(t(ctx.settings.default_lang, "fit_repeat_empty"), show_alert=False)
                return
            workout_row = fitness_get_workout(int(latest[0]))
            if not workout_row:
                await callback.answer(t(ctx.settings.default_lang, "fit_not_found"), show_alert=False)
                return
            workout = _parse_workout_row(workout_row)
            is_fav = fitness_is_favorite(user_id=user_id, workout_id=workout["id"])
            if callback.message:
                await callback.message.edit_text(
                    _workout_card_for_user(user_id, workout),
                    reply_markup=_workout_actions(workout["id"], is_fav),
                )
            await callback.answer()
            return

        if action == "list":
            page = max(1, int(arg or "1"))
            rows, total = fitness_list_workouts(page=page, limit=LIST_PAGE_SIZE)
            if not rows:
                await callback.answer(t(ctx.settings.default_lang, "fit_no_workouts"), show_alert=False)
                return
            if callback.message:
                await callback.message.edit_text(
                    t(ctx.settings.default_lang, "fit_list_title", page=page, total=total),
                    reply_markup=_list_markup(page, total, rows),
                )
            await callback.answer()
            return

        if action in {"show", "send", "done", "fav", "unfav"}:
            if not arg.isdigit():
                await callback.answer(t(ctx.settings.default_lang, "fit_bad_id"), show_alert=False)
                return
            workout_row = fitness_get_workout(int(arg))
            if not workout_row:
                await callback.answer(t(ctx.settings.default_lang, "fit_not_found"), show_alert=False)
                return
            workout = _parse_workout_row(workout_row)

            if action == "show":
                is_fav = fitness_is_favorite(user_id=user_id, workout_id=workout["id"])
                if callback.message:
                    await callback.message.edit_text(
                        _workout_card_for_user(user_id, workout),
                        reply_markup=_workout_actions(workout["id"], is_fav),
                    )
                await callback.answer()
                return

            if action == "send":
                if not callback.message:
                    await callback.answer(t(ctx.settings.default_lang, "fit_no_message"), show_alert=False)
                    return
                await callback.answer(t(ctx.settings.default_lang, "fit_plan_generating"), show_alert=False)
                plan_text, ok = await _safe_workout_plan(ctx, workout, user_id=user_id)
                if not ok:
                    await callback.message.reply(t(ctx.settings.default_lang, "fit_plan_failed"))
                is_fav = fitness_is_favorite(user_id=user_id, workout_id=workout["id"])
                try:
                    await callback.message.edit_text(plan_text, reply_markup=_plan_actions(workout["id"], is_fav))
                except Exception:
                    await callback.message.reply(plan_text, reply_markup=_plan_actions(workout["id"], is_fav))
                return

            if action == "done":
                fitness_add_session(
                    user_id=user_id,
                    workout_id=workout["id"],
                    done_at=datetime.now().isoformat(timespec="seconds"),
                    rpe=None,
                    comment=None,
                )
                recent_rpe = fitness_get_recent_rpe(user_id=user_id, workout_id=workout["id"], limit=3)
                hint = _next_hint_by_context(None, recent_rpe)
                fitness_upsert_progress(
                    user_id=user_id,
                    workout_id=workout["id"],
                    last_rpe=None,
                    last_comment=None,
                    next_hint=hint,
                    updated_at=datetime.now().isoformat(timespec="seconds"),
                )
                await callback.answer(t(ctx.settings.default_lang, "fit_done_saved_short"), show_alert=False)
                if callback.message:
                    await callback.message.reply(t(ctx.settings.default_lang, "fit_next_hint", hint=hint))
                return

            if action == "fav":
                fitness_set_favorite(user_id=user_id, workout_id=workout["id"])
                if callback.message:
                    await callback.message.edit_reply_markup(reply_markup=_workout_actions(workout["id"], True))
                await callback.answer(t(ctx.settings.default_lang, "fit_fav_added"), show_alert=False)
                return

            if action == "unfav":
                fitness_remove_favorite(user_id=user_id, workout_id=workout["id"])
                if callback.message:
                    await callback.message.edit_reply_markup(reply_markup=_workout_actions(workout["id"], False))
                await callback.answer(t(ctx.settings.default_lang, "fit_fav_removed"), show_alert=False)
                return

        if action == "next":
            _day_name, suggested_tag = _weekday_plan_slot()
            workout_row = fitness_get_random_workout(tag=suggested_tag) or fitness_get_random_workout()
            if not workout_row:
                await callback.answer(t(ctx.settings.default_lang, "fit_no_workouts"), show_alert=False)
                return
            workout = _parse_workout_row(workout_row)
            is_fav = fitness_is_favorite(user_id=user_id, workout_id=workout["id"])
            if callback.message:
                await callback.message.edit_text(
                    _workout_card_for_user(user_id, workout),
                    reply_markup=_workout_actions(workout["id"], is_fav),
                )
            await callback.answer()
            return

        if action == "stats":
            since = (datetime.now() - timedelta(days=7)).isoformat(timespec="seconds")
            total, rows = fitness_stats_recent(user_id=user_id, since_iso=since)
            if total == 0:
                text = t(ctx.settings.default_lang, "fit_stats_empty")
            else:
                streak = fitness_current_streak_days(user_id=user_id)
                lines = [
                    t(ctx.settings.default_lang, "fit_stats_title", count=total),
                    t(ctx.settings.default_lang, "fit_stats_streak", count=streak),
                ]
                for workout_id, title, done_at, _tags in rows[:10]:
                    short_dt = str(done_at).replace("T", " ")[:16]
                    lines.append(f"- #{workout_id} {title} ({short_dt})")
                text = "\n".join(lines)
            if callback.message:
                await callback.message.edit_text(text, reply_markup=_menu_markup())
            await callback.answer()
            return

        await callback.answer(t(ctx.settings.default_lang, "digest_unknown_action"), show_alert=False)

    return router

