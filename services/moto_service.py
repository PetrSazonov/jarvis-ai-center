from datetime import date

from core.settings import Settings


def _days_word_ru(n: int) -> str:
    rem10 = n % 10
    rem100 = n % 100
    if rem10 == 1 and rem100 != 11:
        return "день"
    if rem10 in {2, 3, 4} and rem100 not in {12, 13, 14}:
        return "дня"
    return "дней"


def next_moto_season_date(today: date, settings: Settings) -> date:
    month, day = settings.moto_season_start_mmdd
    candidate = date(today.year, month, day)
    if candidate < today:
        return date(today.year + 1, month, day)
    return candidate


def moto_season_countdown_line(settings: Settings, today: date | None = None) -> str:
    base = today or date.today()
    season_date = next_moto_season_date(base, settings)
    days = (season_date - base).days
    year = season_date.year
    return f"До мотосезона {year} осталось {days} {_days_word_ru(days)}."
