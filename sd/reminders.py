"""Optional weekly quest reminder, one delivery attempt per Moscow week."""
from datetime import datetime

import discord

from .core import bot
from . import quests

_last_scan = None


async def enabled(guild_id, user_id):
    async with bot.db.execute("SELECT enabled FROM quest_reminders WHERE guild_id=? AND user_id=?",
                              (guild_id, user_id)) as cur:
        row = await cur.fetchone()
    return bool(row and row[0])


async def toggle(inter):
    async with bot.transaction() as db:
        await db.execute(
            "INSERT INTO quest_reminders(guild_id,user_id,enabled) VALUES(?,?,1) "
            "ON CONFLICT(guild_id,user_id) DO UPDATE SET enabled=1-enabled",
            (inter.guild_id, inter.user.id),
        )
    note = ("В последний день недели бот попробует прислать одно напоминание в личные сообщения."
            if await enabled(inter.guild_id, inter.user.id) else "Личные напоминания выключены.")
    await quests.show(inter, note)


async def send_due():
    global _last_scan
    now = datetime.now(quests.COURT_TZ)
    week, ends = quests.week_window(now.timestamp())
    if not 0 < ends - now.timestamp() <= 24 * 3600:
        return
    hour = now.strftime("%Y%m%d%H")
    if _last_scan == hour:
        return
    _last_scan = hour
    async with bot.db.execute(
        "SELECT guild_id,user_id FROM quest_reminders WHERE enabled=1 AND last_week IS NOT ?",
        (week,),
    ) as cur:
        recipients = await cur.fetchall()
    goals = quests.goals_for_week(week)
    for guild_id, user_id in recipients:
        guild = bot.get_guild(guild_id)
        member = guild.get_member(user_id) if guild else None
        if member is None:
            continue
        async with bot.transaction() as db:
            counts = await quests.progress(db, guild_id, user_id, week)
            if counts[3]:
                continue
            changed = await db.execute(
                "UPDATE quest_reminders SET last_week=? WHERE guild_id=? AND user_id=? "
                "AND enabled=1 AND last_week IS NOT ?", (week, guild_id, user_id, week))
        if changed.rowcount != 1:
            continue
        count = quests.completed_count(counts, goals)
        notice = "Забери готовую награду." if count == len(goals) else f"Готово {count} из {len(goals)} поручений."
        try:
            await member.send(f"**{discord.utils.escape_markdown(guild.name)} · Поручения двора**\n"
                              f"{notice} Неделя закончится <t:{ends}:R>.",
                              allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException as ex:
            print("Не отправлено напоминание о поручениях:", guild_id, user_id, repr(ex))
