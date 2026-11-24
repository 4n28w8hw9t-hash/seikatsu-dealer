"""
Seikatsu Dealer — точка входа.
Сам бот лежит в папке sd/: каждый файл — отдельная часть (см. sd/__init__.py).
"""
import sys

sys.stdout.reconfigure(line_buffering=True)   # print() сразу виден в журнале Bothost

from sd.core import TOKEN, bot  # noqa: E402
from sd import levels, paths, achievements, economy, games, marriage, market, menu, admin, chronicle  # noqa: F401,E402


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Не найден DISCORD_TOKEN. Создай файл .env (см. README.md)")
    bot.run(TOKEN)
