"""Еженедельные поручения двора и награда за все три."""
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from .core import bot, embed, fmt, send_card

COURT_TZ = timezone(timedelta(hours=3))
QUESTS = (
    ("work", "Получить жалованье", 2, "раз"),
    ("voice", "Провести время в голосовом", 30, "мин"),
    ("daily", "Забрать ежедневную награду", 3, "раза"),
)
REWARD = 350


def week_window(now=None):
    day = datetime.now(COURT_TZ) if now is None else datetime.fromtimestamp(now, COURT_TZ)
    monday = (day - timedelta(days=day.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday.date().isoformat(), int((monday + timedelta(days=7)).timestamp())


async def record(db, guild_id: int, user_id: int, activity: str, now=None):
    if activity not in {"work", "voice", "daily"}:
        raise ValueError("Unknown weekly quest activity")
    week, _ = week_window(now)
    await db.execute(
        f"INSERT INTO weekly_quests(guild_id,user_id,week,{activity}) VALUES(?,?,?,1) "
        f"ON CONFLICT(guild_id,user_id,week) DO UPDATE SET {activity}={activity}+1",
        (guild_id, user_id, week))


async def progress(db, guild_id, user_id, week):
    async with db.execute(
        "SELECT work,voice,daily,claimed FROM weekly_quests WHERE guild_id=? AND user_id=? AND week=?",
        (guild_id, user_id, week)
    ) as cur:
        return await cur.fetchone() or (0, 0, 0, 0)


def complete(counts):
    return all(value >= quest[2] for value, quest in zip(counts, QUESTS))


async def show(inter: discord.Interaction, notice=""):
    week, ends = week_window()
    counts = await progress(bot.db, inter.guild_id, inter.user.id, week)
    lines = [f"{'✅' if count >= need else '◇'} **{title}** · {min(count, need)}/{need} {unit}"
             for (_, title, need, unit), count in zip(QUESTS, counts)]
    reward = "Награда получена" if counts[3] else f"За все три задания: **{fmt(REWARD)}**"
    text = "\n".join([f"Новая неделя <t:{ends}:R>.", "", *lines, "", reward])
    if notice:
        text = notice + "\n\n" + text
    rows = [["work", "daily"]]
    if complete(counts) and not counts[3]:
        rows.insert(0, ["quests:claim"])
    await send_card(inter, embed("📜 Поручения двора", text), "help", rows=rows)


async def claim(inter: discord.Interaction):
    g, uid = inter.guild_id, inter.user.id
    async with bot.transaction() as db:
        week, _ = week_window()
        counts = await progress(db, g, uid, week)
        if counts[3]:
            note = "Ты уже забрал награду за эту неделю."
        elif not complete(counts):
            note = "Сначала выполни все три поручения."
        else:
            await bot.ensure_user(db, g, uid)
            await db.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?",
                             (REWARD, g, uid))
            await db.execute(
                "UPDATE weekly_quests SET claimed=1 WHERE guild_id=? AND user_id=? AND week=?",
                (g, uid, week))
            note = f"🎁 Получено **{fmt(REWARD)}** за все поручения."
    await show(inter, note)


@bot.tree.command(name="поручения", description="Еженедельные задания двора и награда")
@app_commands.guild_only()
async def weekly_quests(inter: discord.Interaction):
    await show(inter)
