"""Меню, помощь и обработка всех кнопок."""
import os

import discord
from discord import app_commands

from .core import card_name, BUTTONS, DAILY_REWARD, after_action, ECON_LOCK, RED, bot, reply, send_card, too_fast
from .achievements import achievements
from .economy import balance, daily, profile
from .games import coinflip
from . import market
from .paths import choose_path, pick_path, work
from .marriage import buy_ring, couple, divorce, divorce_confirm, love_room, rings_shop


# ═════════ Помощь ═════════
@bot.tree.command(name="помощь", description="Что умеет Seikatsu Dealer")
async def help_cmd(inter: discord.Interaction):
    e = discord.Embed(
        title="Seikatsu Dealer",
        description=("Принцесса двора **Seikatsu** и хранительница казны.\n"
                     "Всё делается кнопками, ответы видишь только ты."),
        color=RED,
    )
    e.add_field(name="🎁 Монеты", inline=False,
                value=f"`/награда` — {DAILY_REWARD} монет раз в 24 часа\n"
                      "`/баланс` — сколько у тебя монет")
    e.add_field(name="🎲 Игры", inline=False,
                value="`/монетка` — угадал сторону: x2, нет — ставка сгорает\n"
                      "`/дуэль @участник` — ставка с каждого, победитель забирает всё")
    e.add_field(name="👤 Профиль", inline=False,
                value="`/путь` — знать или вера: от пути и уровня зависит титул\n"
                      "`/работа` — жалованье по титулу раз в 12 часов\n"
                      "`/профиль` — титул, уровень, опыт, баланс, пара, достижения\n"
                      "`/достижения` — все достижения с редкостью и наградами\n"
                      "Опыт идёт за сообщения и время в голосовых.")
    e.add_field(name="💍 Брак", inline=False,
                value="`/кольца` — купить кольцо · `/брак @участник` — предложение\n"
                      "`/пара` — парный профиль и лав-рума · `/развод`")
    e.add_field(name="🎭 Роли", inline=False,
                value=f"`/создать_роль` — своя роль за {market.ROLE_CREATE_PRICE:,} монет (до {market.ROLE_LIMIT} штук)\n"
                      "`/роли` — надеть, снять, выставить на продажу\n"
                      f"`/магазин` — купить роль; создатель получает {round(market.SELLER_SHARE * 100)}% с продажи"
                      .replace(",", " "))
    e.set_footer(text="Админам: /эко — управление монетами")
    await send_card(inter, e, "help")


# ═════════ Меню ═════════
MENU_ROWS = [
    "---", "### Профиль", ["profile", "path", "work", "ach"],
    "---", "### Монеты", ["balance", "daily", "coin"],
    "---", "### Пара", ["couple", "rings", "loveroom"],
    "---", "### Роли", ["market", "roles", "rolecreate"],
    "---", ["help"],
]
# окно с вводом: (заголовок, подпись поля, подсказка)
MENU_MODALS = {"coin": ("Монетка", "Ставка", "например 100")}


async def menu_action(key: str, inter: discord.Interaction, n: int = 0, side: str = ""):
    if key == "menu":
        await reply(inter, **menu_page())
    elif key == "profile":
        await profile.callback(inter, None)
    elif key == "work":
        await work.callback(inter)
    elif key == "path":
        await choose_path.callback(inter)
    elif key.startswith("path:"):
        await pick_path(inter, key[5:])
    elif key == "ach":
        await achievements.callback(inter, None)
    elif key == "balance":
        await balance.callback(inter, None)
    elif key == "daily":
        await daily.callback(inter)
    elif key == "help":
        await help_cmd.callback(inter)
    elif key == "couple":
        await couple.callback(inter, None)
    elif key == "rings":
        await rings_shop.callback(inter)
    elif key.startswith("ring:"):
        await buy_ring(inter, key[5:])
    elif key == "loveroom":
        await love_room(inter)
    elif key == "divorce":
        await divorce.callback(inter)
    elif key == "divorce:yes":
        await divorce_confirm(inter)
    elif key == "market":
        await market.market.callback(inter)
    elif key == "roles":
        await market.my_roles.callback(inter)
    elif key.startswith("mk:"):
        await market.handle(inter, key)
    elif key == "coin":
        if n < 10:
            return await reply(inter, "Минимальная ставка — 10", rows=[["coin"]])
        s = "решка" if side.strip().lower().startswith("р") else "орёл"
        await coinflip.callback(inter, n, app_commands.Choice(name=s, value=s))


async def begin(inter: discord.Interaction):
    """Нажатие в личном сообщении меняет его же; в общей панели — открывает личное."""
    own = inter.message is not None and inter.message.flags.ephemeral
    if own:
        await inter.response.defer()
        inter.extras["sd_edit"] = True
    else:
        await inter.response.defer(ephemeral=True, thinking=True)


async def run_action(inter: discord.Interaction, key: str, n: int = 0, side: str = ""):
    await run_fn(inter, lambda i: menu_action(key, i, n, side), key)


async def run_fn(inter: discord.Interaction, fn, label: str = "окно"):
    """Подтверждает нажатие и выполняет действие строго по очереди с остальными."""
    try:
        await begin(inter)
        async with ECON_LOCK:
            await fn(inter)
            await after_action(inter)
    except Exception as ex:
        print("Ошибка кнопки:", label, repr(ex))
        try:
            await reply(inter, "Что-то пошло не так, попробуй ещё раз")
        except Exception:
            pass


class AmountModal(discord.ui.Modal):
    def __init__(self, key: str):
        title, label, hint = MENU_MODALS[key]
        super().__init__(title=title)
        self.key = key
        self.amount = discord.ui.TextInput(label=label, placeholder=hint, max_length=9)
        self.add_item(self.amount)
        self.side = None
        if key == "coin":
            self.side = discord.ui.TextInput(label="Орёл или решка", default="орёл", max_length=10)
            self.add_item(self.side)

    async def on_submit(self, inter: discord.Interaction):
        raw = self.amount.value.strip()
        if not raw.isdigit():
            return await inter.response.send_message("Нужно целое число", ephemeral=True)
        await run_action(inter, self.key, int(raw), self.side.value if self.side else "")


@bot.event
async def on_interaction(inter: discord.Interaction):
    """Все кнопки бота (sd:...) — работают и после перезапуска."""
    if inter.type is not discord.InteractionType.component:
        return
    cid = str((inter.data or {}).get("custom_id", ""))
    if not cid.startswith("sd:"):
        return
    key = cid[3:]
    if key not in BUTTONS and not key.startswith("mk:"):
        return
    try:
        if too_fast(inter.user.id):
            return await inter.response.send_message(
                "⏳ Не так быстро, подожди пару секунд", ephemeral=True)
        if key in MENU_MODALS:
            return await inter.response.send_modal(AmountModal(key))
        modal = market.modal_for(key)
        if modal:
            return await inter.response.send_modal(modal)
    except discord.HTTPException as ex:
        return print("Ошибка кнопки:", key, repr(ex))
    await run_action(inter, key)


def menu_page() -> dict:
    e = discord.Embed(
        title="Двор Seikatsu — меню",
        description=("Жми кнопки — всё открывается здесь же и видно только тебе.\n"
                     "-# Командами остались действия с другим игроком: "
                     "`/дуэль` и `/брак`."),
        color=RED)
    kw = {"embed": e, "rows": MENU_ROWS, "nav": False}
    b = getattr(bot, "banners", {})
    path = b.get("menu") or b.get("help")
    if path and os.path.exists(path):
        kw["image"] = (card_name(path), path)
    return kw


@bot.tree.command(name="меню", description="Все действия кнопками")
async def menu(inter: discord.Interaction):
    await reply(inter, **menu_page())
