"""Личная история кошелька. Записи добавляются в транзакции с операцией."""
import time

import discord
from discord import app_commands

from .core import bot, button_emoji, button_icon, embed, fmt, send_card

PAGE_SIZE = 8
FILTERS = {
    "all": ("Все операции", "", "history", "📒"),
    "income": ("Приход", " AND amount>0", "filter_income", "⬇️"),
    "expense": ("Расход", " AND amount<0", "filter_expense", "⬆️"),
    "purchases": ("Покупки", " AND kind IN ('role_buy','role_create','ring','room_name')", "filter_purchase", "🛍️"),
}
KINDS = {
    "winter": "Бал зимней луны",
    "transfer": "Перевод", "duel": "Дуэль", "flip": "Монетка",
    "daily": "Ежедневная награда", "work": "Жалованье",
    "quests": "Поручения двора", "achievement": "Достижение",
    "ring": "Покупка кольца", "role_buy": "Покупка роли", "role_sell": "Продажа роли",
    "role_refund": "Возврат за роль", "role_create": "Создание роли",
    "room_name": "Название лав-румы", "admin": "Канцелярия",
}
STATUSES = {"pending": "проверяется", "done": "завершена", "refunded": "монеты возвращены"}


async def record(db, guild_id, user_id, amount, kind, detail="", *, status="done", role_ref=None):
    await db.execute(
        "INSERT INTO coin_history(guild_id,user_id,amount,kind,detail,status,role_ref,created) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (guild_id, user_id, amount, kind, detail, status, role_ref, int(time.time())))


async def role_status(db, guild_id, user_id, role_ref, status):
    await db.execute(
        "UPDATE coin_history SET status=? WHERE guild_id=? AND user_id=? AND role_ref=? "
        "AND kind='role_buy' AND status='pending'", (status, guild_id, user_id, role_ref))


async def show(inter: discord.Interaction, before: int | None = None, category="all"):
    from .quests import week_window
    category = category if category in FILTERS else "all"
    _, ends = week_window()
    async with bot.db.execute(
        "SELECT COALESCE(SUM(CASE WHEN amount>0 THEN amount END),0), "
        "COALESCE(-SUM(CASE WHEN amount<0 THEN amount END),0) FROM coin_history "
        "WHERE guild_id=? AND user_id=? AND created>=? AND created<? AND status<>'pending'",
        (inter.guild_id, inter.user.id, ends - 7 * 86400, ends),
    ) as cur:
        income, expense = await cur.fetchone()
    g, uid = inter.guild_id, inter.user.id
    params = [g, uid]
    cutoff = ""
    if before is not None:
        cutoff = " AND id<?"
        params.append(before)
    async with bot.db.execute(
        "SELECT id,amount,kind,detail,status,created FROM coin_history WHERE guild_id=? AND user_id=?"
        + FILTERS[category][1] + cutoff + " ORDER BY id DESC LIMIT ?", (*params, PAGE_SIZE + 1)
    ) as cur:
        entries = await cur.fetchall()
    lines = []
    for _, amount, kind, detail, status, created in entries[:PAGE_SIZE]:
        sign = "−" if amount < 0 else "+"
        info = f" · {detail}" if detail else ""
        state = f" · {STATUSES.get(status, status)}" if kind == "role_buy" else ""
        lines.append(f"<t:{created}:d> · **{sign}{fmt(abs(amount))}** · {KINDS.get(kind, kind)}{info}{state}")
    content = "\n".join(lines) if lines else "Пока нет записей за этот период."
    summary = f"**Неделя · +{fmt(income)} / −{fmt(expense)}**"
    content = summary + "\n\n" + content
    filters = discord.ui.Select(custom_id="sd:history:filter", placeholder="Фильтр операций", options=[
        discord.SelectOption(label=label, value=key, default=key == category,
                             emoji=button_emoji(icon, fallback))
        for key, (label, _, icon, fallback) in FILTERS.items()
    ])
    buttons = []
    if before is not None:
        buttons.append(discord.ui.Button(label="К последним", emoji=button_emoji("history", "📒"),
                                         custom_id=f"sd:history:{category}"))
    if len(entries) > PAGE_SIZE:
        buttons.append(discord.ui.Button(label="Раньше", emoji=button_emoji("page_prev", "⬅️"),
                                         custom_id=f"sd:history:{category}:{entries[PAGE_SIZE - 1][0]}"))
    icon = button_icon("history") or "📒"
    await send_card(inter, embed(f"{icon} История монет", content), "balance",
                    rows=[[filters], buttons] if buttons else [[filters]], ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="история", description="Посмотреть личную историю монет")
@app_commands.guild_only()
async def history_cmd(inter: discord.Interaction):
    await show(inter)
