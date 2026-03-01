def next_hint_by_rpe(rpe: int | None) -> str:
    if rpe is None:
        return "Следующий раз держи технику и попробуй добавить +1 повтор в ключевых подходах."
    if rpe <= 6:
        return "Было легко: добавь 1-2 повтора в каждом подходе или +1-2 кг."
    if rpe <= 8:
        return "Нормальная рабочая нагрузка: добавь +1 повтор в 1-2 подходах."
    return "Близко к пределу: оставь текущий объем, добавь отдых и чистую технику."


def next_hint_by_context(rpe: int | None, recent_rpe: list[int | None]) -> str:
    valid = [int(x) for x in recent_rpe if isinstance(x, int)]
    if len(valid) >= 3:
        last3 = valid[:3]
        if all(x >= 8 for x in last3):
            return "3 сессии подряд тяжело (RPE 8+): снизь объем на 20% на следующей тренировке."
        if all(x <= 6 for x in last3):
            return "3 сессии подряд легко (RPE <=6): добавь подход или +1-2 кг."
    return next_hint_by_rpe(rpe)
