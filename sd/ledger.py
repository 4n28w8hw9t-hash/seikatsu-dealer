"""Личная история кошелька. Записи добавляются в транзакции с операцией."""
import time

import discord
from discord import app_commands

from .core import bot, button_icon, embed, fmt, send_card

PAGE_SIZE = 8
KINDS = {
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


async def show(inter: discord.Interaction, before: int | None = None):
    g, uid = inter.guild_id, inter.user.id
    params = [g, uid]
    cutoff = ""
    if before is not None:
        cutoff = " AND id<?"
        params.append(before)
    async with bot.db.execute(
        "SELECT id,amount,kind,detail,status,created FROM coin_history WHERE guild_id=? AND user_id=?"
        + cutoff + " ORDER BY id DESC LIMIT ?", (*params, PAGE_SIZE + 1)
    ) as cur:
        entries = await cur.fetchall()
    lines = []
    for _, amount, kind, detail, status, created in entries[:PAGE_SIZE]:
        sign = "−" if amount < 0 else "+"
        info = f" · {detail}" if detail else ""
        state = f" · {STATUSES.get(status, status)}" if kind == "role_buy" else ""
        lines.append(f"<t:{created}:d> · **{sign}{fmt(abs(amount))}** · {KINDS.get(kind, kind)}{info}{state}")
    content = "\n".join(lines) if lines else "Пока нет записей за этот период."
    content += "\n\n-# История ведётся с момента установки обновления."
    buttons = []
    if before is not None:
        buttons.append(discord.ui.Button(label="К последним", custom_id="sd:history"))
    if len(entries) > PAGE_SIZE:
        buttons.append(discord.ui.Button(label="Раньше", custom_id=f"sd:history:{entries[PAGE_SIZE - 1][0]}"))
    icon = button_icon("history") or "📒"
    await send_card(inter, embed(f"{icon} История монет", content), "balance",
                    rows=[buttons] if buttons else [], ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none())


@bot.tree.command(name="история", description="Посмотреть личную историю монет")
@app_commands.guild_only()
async def history_cmd(inter: discord.Interaction):
    await show(inter)
