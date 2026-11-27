"""Shared monthly event, with a single commemorative badge per participant."""
from datetime import datetime

import discord
from discord import app_commands

from .core import bot, button_icon, embed, send_card
from .quests import COURT_TZ

GOAL = 40
PERSONAL_GOAL = 3


def event_window(now=None):
    day = datetime.now(COURT_TZ) if now is None else datetime.fromtimestamp(now, COURT_TZ)
    end = day.replace(day=8, hour=0, minute=0, second=0, microsecond=0)
    return day.strftime("%Y-%m"), int(end.timestamp()), day.day < 8


def progress_line(label, points, goal):
    filled = min(points, goal) * 10 // goal
    bar = "▰" * filled + "▱" * (10 - filled)
    return f"**{label}** · **{points}/{goal}**\n{bar}"


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


async def show(inter, notice="", *, show_help=False):
    now = datetime.now(COURT_TZ)
    month, ends, active = event_window(now.timestamp())
    next_month = now.replace(year=now.year + (now.month == 12), month=now.month % 12 + 1,
                             day=1, hour=0, minute=0, second=0, microsecond=0)
    next_start = int(next_month.timestamp())
    total, personal, claimed = await event_progress(bot.db, inter.guild_id, month, inter.user.id)
    lines = [
        f"**Общее дело · {month}**",
        "",
        progress_line("Весь двор", total, GOAL),
        progress_line("Твой вклад", personal, PERSONAL_GOAL),
        "",
    ]
    rows = []
    if active:
        lines.append(f"**Сбор открыт** до <t:{ends}:F> (<t:{ends}:R>).")
    else:
        result = "Двор достиг общей цели." if total >= GOAL else "Двор не достиг общей цели."
        lines.extend((f"**Итоги события.** {result}", f"Следующий сбор откроется <t:{next_start}:F>."))
    if claimed:
        lines.append("Твой памятный знак уже в Витрине.")
        rows.append(["showcase"])
    elif total >= GOAL and personal >= PERSONAL_GOAL:
        lines.append(f"Твой знак готов. Его можно забрать до <t:{next_start}:F>.")
        rows.append(["event:claim"])
    elif not active:
        reason = "Не хватило личного вклада." if total >= GOAL else "Для знака нужна общая победа двора."
        lines.append(reason)
    if active and show_help:
        lines.extend(("", "**Чем помочь двору**", "Служба и ежедневная награда дают по одному вкладу."))
        rows.append(["work", "daily"])
    elif active and not rows:
        rows.append(["event:help"])
    if notice:
        lines.extend(("", notice))
    title = f"{button_icon('court_event') or '🏆'} Событие двора"
    await send_card(inter, embed(title, "\n".join(lines)), "court_event", rows=rows)


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
