from __future__ import annotations

from aiogram import F, Router, types
from aiogram.filters import Command

from db import user_settings_get_full
from handlers.context import AppContext
from services.growth_service import build_plan_text, build_review_text, build_score_text
from services.messages import t


def _resolve_lang(ctx: AppContext, user_id: int) -> str:
    lang = ctx.settings.default_lang
    if user_id <= 0:
        return lang
    profile = user_settings_get_full(user_id)
    value = str(profile.get("lang") or "").strip().lower()
    if value in {"ru", "en"}:
        return value
    return lang


def build_growth_router(ctx: AppContext) -> Router:
    router = Router(name="growth")
    router.message.filter(F.chat.type == "private")

    @router.message(Command("score"))
    async def score_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        lang = _resolve_lang(ctx, user_id)
        if user_id <= 0:
            await message.reply(t(lang, "error_generic"))
            return
        await message.reply(build_score_text(user_id=user_id, lang=lang))

    @router.message(Command("plan"))
    async def plan_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        lang = _resolve_lang(ctx, user_id)
        if user_id <= 0:
            await message.reply(t(lang, "error_generic"))
            return
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        horizon = parts[1] if len(parts) > 1 else "day"
        await message.reply(build_plan_text(user_id=user_id, horizon=horizon, lang=lang))

    @router.message(Command("review"))
    async def review_command(message: types.Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        lang = _resolve_lang(ctx, user_id)
        if user_id <= 0:
            await message.reply(t(lang, "error_generic"))
            return
        text = (message.text or "").strip()
        parts = text.split(maxsplit=1)
        horizon = parts[1] if len(parts) > 1 else "week"
        await message.reply(build_review_text(user_id=user_id, horizon=horizon, lang=lang))

    return router
