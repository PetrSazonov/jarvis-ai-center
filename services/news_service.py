import asyncio
from datetime import datetime
from email.utils import parsedate_to_datetime
import logging
import time
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from services.http_service import request_text

logger = logging.getLogger("purecompanybot")


TOP_FEEDS = [
    "https://vc.ru/rss/all",
    "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
    "https://www.ixbt.com/export/news.rss",
    "https://3dnews.ru/news/rss/",
    "https://www.cnews.ru/inc/rss/news.xml",
    "https://news.google.com/rss/search?q=UFC&hl=ru&gl=RU&ceid=RU:ru",
    "https://news.google.com/rss/search?q=Dota+2&hl=ru&gl=RU&ceid=RU:ru",
    "https://news.google.com/rss/search?q=MotoGP&hl=ru&gl=RU&ceid=RU:ru",
]

TOPIC_FEEDS = [
    "https://vc.ru/rss/all",
    "https://www.ixbt.com/export/news.rss",
    "https://3dnews.ru/news/rss/",
    "https://www.cnews.ru/inc/rss/news.xml",
    "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
    "https://news.google.com/rss/search?q=UFC&hl=ru&gl=RU&ceid=RU:ru",
    "https://news.google.com/rss/search?q=Dota+2&hl=ru&gl=RU&ceid=RU:ru",
    "https://news.google.com/rss/search?q=MotoGP&hl=ru&gl=RU&ceid=RU:ru",
]

MOTO_FALLBACK_FEEDS: list[str] = []

_FEED_CACHE_TTL_SEC = 300.0
_FEED_FAIL_COOLDOWN_SEC = 900.0
_FEED_REQUEST_TIMEOUT_SEC = 5.0
_FEED_BATCH_TIMEOUT_SEC = 7.0
_FEED_CACHE: dict[str, tuple[float, list[dict[str, str]]]] = {}
_FEED_FAIL_UNTIL: dict[str, float] = {}

TOPIC_KEYWORDS = {
    "технологии": ["технолог", "tech", "разработ", "it", "программ", "софт", "hardware", "гаджет"],
    "нейросети": ["нейросет", "neural", "llm", "gpt", "chatgpt", "ai", "ии", "машинн"],
    "ии": ["искусствен", "ai", "ии", "machine learning", "llm", "модель", "генератив"],
    "крипта": ["bitcoin", "btc", "ethereum", "eth", "крипт", "blockchain", "блокчейн", "web3"],
    "полиграфия": ["полиграф", "printing", "печать", "типограф", "офсет", "цифровая печать"],
    "спорт": ["ufc", "mma", "бой", "поедин", "нокаут", "octagon", "oktagon", "fight night", "чемпион"],
    "дота2": [
        "dota",
        "dota 2",
        "дота",
        "киберспорт",
        "esports",
        "the international",
        "valve",
    ],
    "motogp": [
        "motogp",
        "moto gp",
        "grand prix",
        "гран-при",
        "sprint race",
        "ducati",
        "yamaha",
        "honda",
        "ktm",
    ],
    "мотоциклы": [
        "мото",
        "motorcycle",
        "байк",
        "bike",
        "мотоцикл",
        "motogp",
        "ducati",
        "yamaha",
        "honda",
        "kawasaki",
        "ktm",
    ],
}

NOISE_KEYWORDS = [
    "полит",
    "президент",
    "выбор",
    "госдум",
    "дума",
    "министер",
    "мэр",
    "правитель",
    "санкц",
    "нато",
    "военн",
    "войн",
    "tv",
    "телешоу",
    "шоу",
    "скандал",
    "пропаганд",
    "депутат",
    "kremlin",
    "government",
    "election",
    "трамп",
    "байден",
    "украин",
    "сша",
    "евросоюз",
]

ALLOWED_GENERAL_KEYWORDS = sorted({kw for values in TOPIC_KEYWORDS.values() for kw in values})


def _clean_title(text: str) -> str:
    return " ".join((text or "").replace("\n", " ").split())


def _url_domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        return host[4:]
    return host


def _is_short_text(text: str) -> bool:
    return len((text or "").strip()) < 24


def _item_ts(item: dict[str, str]) -> float:
    raw = str(item.get("published_ts", "0") or "0")
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _rank_item(item: dict[str, str]) -> int:
    title = item["title"].lower()
    score = 0
    for kw in TOPIC_KEYWORDS["нейросети"] + TOPIC_KEYWORDS["ии"]:
        if kw in title:
            score += 2
    for kw in (
        TOPIC_KEYWORDS["крипта"]
        + TOPIC_KEYWORDS["мотоциклы"]
        + TOPIC_KEYWORDS["дота2"]
        + TOPIC_KEYWORDS["motogp"]
        + TOPIC_KEYWORDS["технологии"]
    ):
        if kw in title:
            score += 1

    age_sec = max(0.0, time.time() - _item_ts(item))
    if age_sec <= 6 * 3600:
        score += 4
    elif age_sec <= 24 * 3600:
        score += 3
    elif age_sec <= 72 * 3600:
        score += 1

    return score


def _limit_per_domain(items: list[dict[str, str]], max_per_domain: int) -> list[dict[str, str]]:
    counts: dict[str, int] = {}
    filtered: list[dict[str, str]] = []

    for item in items:
        domain = _url_domain(item["url"])
        current = counts.get(domain, 0)
        if current >= max_per_domain:
            continue
        counts[domain] = current + 1
        filtered.append(item)

    return filtered


def _dedupe_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    used_urls: set[str] = set()
    deduped: list[dict[str, str]] = []
    for item in items:
        url = item["url"]
        if url in used_urls:
            continue
        used_urls.add(url)
        deduped.append(item)
    return deduped


def _is_news_item_valid(item: dict[str, str]) -> bool:
    title = item.get("title") or ""
    url = item.get("url") or ""
    return bool(title and url and not _is_short_text(title))


def _sort_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    return sorted(items, key=lambda item: (_item_ts(item), _rank_item(item)), reverse=True)


def _parse_published_ts(value: str) -> float:
    raw = (value or "").strip()
    if not raw:
        return 0.0
    try:
        return parsedate_to_datetime(raw).timestamp()
    except Exception:
        pass
    try:
        normalized = raw.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return 0.0


def _extract_items(xml_text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    for node in root.findall(".//item"):
        title = _clean_title(node.findtext("title") or "")
        link = (node.findtext("link") or "").strip()
        pub = node.findtext("pubDate") or node.findtext("{http://purl.org/dc/elements/1.1/}date") or ""
        published_ts = _parse_published_ts(pub)
        if title and link:
            items.append({"title": title, "url": link, "published_ts": f"{published_ts:.0f}"})

    if not items:
        for node in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
            title = _clean_title(node.findtext("{http://www.w3.org/2005/Atom}title") or "")
            link = ""
            updated = (
                node.findtext("{http://www.w3.org/2005/Atom}updated")
                or node.findtext("{http://www.w3.org/2005/Atom}published")
                or ""
            )
            published_ts = _parse_published_ts(updated)
            for link_node in node.findall("{http://www.w3.org/2005/Atom}link"):
                href = (link_node.attrib.get("href") or "").strip()
                if href:
                    link = href
                    break
            if title and link:
                items.append({"title": title, "url": link, "published_ts": f"{published_ts:.0f}"})

    return items


async def _fetch_feed(url: str) -> list[dict[str, str]]:
    now = time.monotonic()
    fail_until = _FEED_FAIL_UNTIL.get(url, 0.0)
    if fail_until > now:
        return []

    cached = _FEED_CACHE.get(url)
    if cached and (now - cached[0]) <= _FEED_CACHE_TTL_SEC:
        return cached[1]

    try:
        xml_text = await request_text(
            service="rss",
            method="GET",
            url=url,
            retries=0,
            timeout=_FEED_REQUEST_TIMEOUT_SEC,
        )
        items = _extract_items(xml_text)
        filtered = [item for item in items if _is_news_item_valid(item)]
        _FEED_CACHE[url] = (time.monotonic(), filtered)
        return filtered
    except Exception as exc:
        logger.warning("event=rss_feed_fetch_failed url=%s error=%s", url, exc.__class__.__name__)
        _FEED_FAIL_UNTIL[url] = time.monotonic() + _FEED_FAIL_COOLDOWN_SEC
        return []


async def _fetch_many(urls: list[str]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    tasks = [asyncio.create_task(_fetch_feed(url)) for url in urls]
    try:
        for done in asyncio.as_completed(tasks, timeout=_FEED_BATCH_TIMEOUT_SEC):
            try:
                result = await done
            except Exception:
                continue
            merged.extend(result)
    except asyncio.TimeoutError:
        for task in tasks:
            if not task.done():
                task.cancel()
        logger.warning("event=rss_batch_timeout timeout=%.1f", _FEED_BATCH_TIMEOUT_SEC)
    finally:
        await asyncio.gather(*tasks, return_exceptions=True)

    merged = _dedupe_items(merged)
    return _sort_items(merged)


def _is_noise(title: str) -> bool:
    lower = title.lower()
    return any(keyword in lower for keyword in NOISE_KEYWORDS)


def _is_allowed_general(title: str) -> bool:
    lower = title.lower()
    return any(keyword in lower for keyword in ALLOWED_GENERAL_KEYWORDS)


async def fetch_headlines(limit: int = 5) -> list[str]:
    items = await _fetch_many(TOP_FEEDS)
    filtered_items = [
        item for item in items if not _is_noise(item["title"]) and _is_allowed_general(item["title"])
    ]
    filtered_items = _limit_per_domain(filtered_items, max_per_domain=2)

    if not filtered_items:
        return ["Новости временно недоступны"]
    return [item["title"] for item in filtered_items[:limit]]


def _match_topic(title: str, topic: str) -> bool:
    lower = title.lower()
    return any(keyword in lower for keyword in TOPIC_KEYWORDS.get(topic, []))


async def fetch_topic_links(limit_total: int = 4) -> list[dict[str, str]]:
    items = await _fetch_many(TOPIC_FEEDS)
    items = [item for item in items if not _is_noise(item["title"])]

    moto_items = await _fetch_many(MOTO_FALLBACK_FEEDS)
    moto_items = [
        item for item in moto_items if _match_topic(item["title"], "мотоциклы") and not _is_noise(item["title"])
    ]

    topics_order = ["нейросети", "ии", "крипта", "дота2", "motogp", "мотоциклы", "спорт", "технологии", "полиграфия"]

    selected: list[dict[str, str]] = []
    used_urls: set[str] = set()
    used_domains: set[str] = set()

    for topic in topics_order:
        pool = moto_items if topic == "мотоциклы" and moto_items else items
        for item in pool:
            if item["url"] in used_urls:
                continue
            if not _match_topic(item["title"], topic):
                continue
            domain = _url_domain(item["url"])
            if domain in used_domains and len(used_domains) < limit_total:
                continue
            used_urls.add(item["url"])
            used_domains.add(domain)
            selected.append(
                {
                    "topic": topic,
                    "title": item["title"],
                    "url": item["url"],
                    "published_ts": str(item.get("published_ts", "0")),
                }
            )
            break

    if len(selected) < limit_total:
        for item in items:
            if item["url"] in used_urls:
                continue
            domain = _url_domain(item["url"])
            if domain in used_domains and len(used_domains) < limit_total:
                continue
            used_urls.add(item["url"])
            used_domains.add(domain)
            selected.append(
                {
                    "topic": "технологии",
                    "title": item["title"],
                    "url": item["url"],
                    "published_ts": str(item.get("published_ts", "0")),
                }
            )
            if len(selected) >= limit_total:
                break

    return selected[:limit_total]
