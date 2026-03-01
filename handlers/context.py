import logging
from dataclasses import dataclass

from aiogram import Bot

from core.settings import Settings


@dataclass
class AppContext:
    bot: Bot
    settings: Settings
    logger: logging.Logger
    known_commands: set[str]
