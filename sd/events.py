"""Shared monthly event, with a single commemorative badge per participant."""
from datetime import datetime

import discord
from discord import app_commands

from .core import bot, embed, reply
from .quests import COURT_TZ

GOAL = 40
PERSONAL_GOAL = 3


def event_window(now=None):
    day = datetime.now(COURT_TZ) if now is None else datetime.fromtimestamp(now, COURT_TZ)
    end = day.replace(day=8, hour=0, minute=0, second=0, microsecond=0)
    return day.strftime("%Y-%m"), int(end.timestamp()), day.day < 8


async def record_contribution(db, guild_id, user_id, now=None):
    month, _, active = event_window(now)
    if active:
        await db.execute(
            "INSERT INTO court_events(guild_id,month,user_id,points) VALUES(?,?,?,1) "
            "ON CONFLICT(guild_id,month,user_id) DO UPDATE SET points=points+1",
            (guild_id, month, user_id),
        )


async def event_progress(db, guild_id, month, user_id):
    async with db.execute(
        "SELECT COALESCE(SUM(points),0), COALESCE(MAX(CASE WHEN user_id=? THEN points END),0), "
        "COALESCE(MAX(CASE WHEN user_id=? THEN claimed END),0) FROM court_events WHERE guild_id=? AND month=?",
        (user_id, user_id, guild_id, month),
    ) as cur:
        return await cur.fetchone()


async def show(inter, notice=""):
    month, ends, active = event_window()
    total, personal, claimed = await event_progress(bot.db, inter.guild_id, month, inter.user.id)
    lines = [
        f"**Общее дело · {month}**",
        f"Вклад двора **{total}/{GOAL}** · твой вклад **{personal}/{PERSONAL_GOAL}**",
    ]
    rows = []
    if active:
        lines.extend((f"Первые семь дней месяца. Вклад принимается до <t:{ends}:F>.",
                      "Работа и ежедневная награда дают по одному вкладу."))
        rows.append(["work", "daily"])
    else:
        lines.append("Сбор вклада завершён. Следующее событие начнётся 1-го числа.")
    if claimed:
        lines.append("Памятный знак уже доступен в Витрине.")
    elif total >= GOAL and personal >= PERSONAL_GOAL:
        rows.append(["event:claim"])
        lines.append("Цель достигнута. Забери памятный знак до конца месяца.")
    if notice:
        lines.extend(("", notice))
    await reply(inter, embed=embed("Событие двора", "\n".join(lines)), rows=rows, key=None)


async def claim(inter):
    month, _, _ = event_window()
    async with bot.transaction() as db:
        g, uid = inter.guild_id, inter.user.id
        total, personal, claimed = await event_progress(db, g, month, uid)
        if claimed:
            notice = "Ты уже забрал памятный знак."
        elif total < GOAL or personal < PERSONAL_GOAL:
            notice = "Для знака нужны общий и личный вклад."
        else:
            await db.execute("UPDATE court_events SET claimed=1 WHERE guild_id=? AND month=? AND user_id=?",
                             (g, month, uid))
            notice = "Памятный знак «Общее дело» добавлен в Витрину."
    await show(inter, notice)


@bot.tree.command(name="событие", description="Общее месячное событие двора и памятный знак")
@app_commands.guild_only()
async def court_event(inter: discord.Interaction):
    await show(inter)
