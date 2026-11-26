"""Еженедельные поручения двора и награда за все три."""
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands

from .core import E, bot, btn, button_icon, embed, fmt, send_card
from .ledger import record as ledger_record

COURT_TZ = timezone(timedelta(hours=3))
QUESTS = (
    ("work", "Получить жалованье", 2, "раз"),
    ("voice", "Провести время в голосовом", 12 * 60, "мин"),
    ("daily", "Забрать ежедневную награду", 3, "раза"),
)
VOICE_GOAL_START_WEEK = "2026-11-30"
REWARD = 350
QUEST_ICONS = {"work": ("quest_work", "work", "⚒️"),
               "voice": ("quest_voice", "ach_voice10", "🎙️"),
               "daily": ("quest_daily", "gift", "🎁")}


def quest_icon(key: str) -> str:
    icon, fallback, emoji = QUEST_ICONS[key]
    return E(f"sd_{icon}") or (E(f"sd_{fallback}", emoji) if fallback else emoji)


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
    if activity in ("work", "daily"):
        from .events import record_contribution
        await record_contribution(db, guild_id, user_id, now)


async def progress(db, guild_id, user_id, week):
    async with db.execute(
        "SELECT work,voice,daily,claimed FROM weekly_quests WHERE guild_id=? AND user_id=? AND week=?",
        (guild_id, user_id, week)
    ) as cur:
        return await cur.fetchone() or (0, 0, 0, 0)


def goals_for_week(week):
    if week >= VOICE_GOAL_START_WEEK:
        return QUESTS
    return tuple((key, title, 30 if key == "voice" else need, unit)
                 for key, title, need, unit in QUESTS)


def completed_count(counts, goals):
    return sum(value >= goal[2] for value, goal in zip(counts, goals))


def complete(counts, goals):
    return completed_count(counts, goals) == len(goals)


def voice_time(minutes):
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} ч {minutes} мин" if minutes else f"{hours} ч"
    return f"{minutes} мин"


def quest_line(goal, count):
    key, title, need, unit = goal
    shown = min(count, need)
    progress_text = (f"{voice_time(shown)} / {voice_time(need)}" if key == "voice"
                     else f"{shown}/{need} {unit}")
    done = " · ✅" if count >= need else ""
    return f"{quest_icon(key)} **{title}** · {progress_text}{done}"


async def show(inter: discord.Interaction, notice=""):
    week, ends = week_window()
    counts = await progress(bot.db, inter.guild_id, inter.user.id, week)
    goals = goals_for_week(week)
    lines = [quest_line(goal, count) for goal, count in zip(goals, counts)]
    reward = "Награда получена" if counts[3] else f"За все три задания: **{fmt(REWARD)}**"
    text = "\n".join([f"Новая неделя <t:{ends}:R>.", "", *lines, "", reward])
    if notice:
        text = notice + "\n\n" + text
    from .reminders import enabled
    remind = await enabled(inter.guild_id, inter.user.id)
    rows = [["work", "daily", btn("quests:reminder", "Напоминание: " + ("вкл." if remind else "выкл."))]]
    if complete(counts, goals) and not counts[3]:
        rows.insert(0, ["quests:claim"])
    await send_card(inter, embed(f"{button_icon('quest_book') or '📜'} Поручения двора", text), "quests", rows=rows)


async def claim(inter: discord.Interaction):
    g, uid = inter.guild_id, inter.user.id
    async with bot.transaction() as db:
        week, _ = week_window()
        counts = await progress(db, g, uid, week)
        if counts[3]:
            note = "Ты уже забрал награду за эту неделю."
        elif not complete(counts, goals_for_week(week)):
            note = "Сначала выполни все три поручения."
        else:
            await bot.ensure_user(db, g, uid)
            await db.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?",
                             (REWARD, g, uid))
            await db.execute(
                "UPDATE weekly_quests SET claimed=1 WHERE guild_id=? AND user_id=? AND week=?",
                (g, uid, week))
            await ledger_record(db, g, uid, REWARD, "quests")
            note = f"🎁 Получено **{fmt(REWARD)}** за все поручения."
    await show(inter, note)


@bot.tree.command(name="поручения", description="Еженедельные задания двора и награда")
@app_commands.guild_only()
async def weekly_quests(inter: discord.Interaction):
    await show(inter)
