import asyncio
import logging
import os
from datetime import datetime

from db import get_crypto_last, set_crypto_last
from services.crypto_service import CRYPTO_IDS, fetch_prices

COINGECKO_VS = (os.getenv("COINGECKO_VS") or "usd").lower()
POLL_SECONDS = int(os.getenv("CRYPTO_POLL_SECONDS") or "600")
ALERT_PCT = float(os.getenv("CRYPTO_ALERT_PCT") or "2.0")


def pct_change(new: float, old: float) -> float:
    if old == 0:
        return 0.0
    return (new - old) / old * 100.0


async def crypto_worker(
    send_signal_fn,
    logger: logging.Logger,
    *,
    vs_currency: str = COINGECKO_VS,
    poll_seconds: int = POLL_SECONDS,
    alert_pct: float = ALERT_PCT,
) -> None:
    backoff_seconds = 5
    max_backoff = max(30, poll_seconds)

    while True:
        try:
            now_iso = datetime.now().isoformat(timespec="seconds")
            data = await fetch_prices(vs_currency)

            for symbol, coin_id in CRYPTO_IDS.items():
                price = float(data[coin_id][vs_currency])
                last = get_crypto_last(symbol)

                if last is None:
                    set_crypto_last(symbol, price, now_iso)
                    continue

                prev_price = float(last[0])
                change = pct_change(price, prev_price)
                set_crypto_last(symbol, price, now_iso)

                if abs(change) >= alert_pct:
                    await send_signal_fn(symbol, price, change, prev_price)
                    logger.info(
                        "event=crypto_alert symbol=%s price=%s prev_price=%s change_pct=%.4f",
                        symbol,
                        price,
                        prev_price,
                        change,
                    )

            backoff_seconds = 5
            await asyncio.sleep(poll_seconds)
        except asyncio.CancelledError:
            logger.info("event=crypto_worker_cancelled")
            raise
        except Exception as exc:
            logger.exception(
                "event=crypto_worker_error backoff_seconds=%s error=%s",
                backoff_seconds,
                exc,
            )
            await asyncio.sleep(backoff_seconds)
            backoff_seconds = min(backoff_seconds * 2, max_backoff)
