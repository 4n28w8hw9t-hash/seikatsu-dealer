"""
Seikatsu Dealer — точка входа.
Сам бот лежит в папке sd/: каждый файл — отдельная часть (см. sd/__init__.py).
"""
from sd.core import TOKEN, bot
from sd import levels, paths, achievements, economy, games, marriage, market, menu, admin  # noqa: F401  (подключают свои команды)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Не найден DISCORD_TOKEN. Создай файл .env (см. README.md)")
    bot.run(TOKEN)
