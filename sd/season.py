"""Месячный рейтинг опыта по времени Москвы."""
from datetime import datetime

from .core import bot
from .quests import COURT_TZ


def month_window():
    now = datetime.now(COURT_TZ)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    after = (start.replace(year=start.year + 1, month=1) if start.month == 12
             else start.replace(month=start.month + 1))
    return start.strftime("%Y-%m"), int(after.timestamp())


async def record(db, guild_id, user_id, xp):
    month, _ = month_window()
    await db.execute(
        "INSERT INTO season_xp(guild_id,month,user_id,xp) VALUES(?,?,?,?) "
        "ON CONFLICT(guild_id,month,user_id) DO UPDATE SET xp=season_xp.xp+excluded.xp",
        (guild_id, month, user_id, xp))


async def ranked(guild, month):
    async with bot.db.execute(
        "SELECT user_id,xp FROM season_xp WHERE guild_id=? AND month=? ORDER BY xp DESC,user_id ASC",
        (guild.id, month)
    ) as cur:
        rows = await cur.fetchall()
    ranked = []
    for uid, xp in rows:
        member = guild.get_member(uid)
        if member and not member.bot:
            ranked.append((uid, xp))
    return ranked


async def close_seasons():
    month, _ = month_window()
    async with bot.db.execute(
        "SELECT DISTINCT s.guild_id,s.month FROM season_xp s "
        "WHERE s.month<? AND NOT EXISTS (SELECT 1 FROM season_closed c WHERE c.guild_id=s.guild_id AND c.month=s.month)",
        (month,)
    ) as cur:
        finished = await cur.fetchall()
    for guild_id, past in finished:
        guild = bot.get_guild(guild_id)
        if not guild or guild.unavailable or not guild.chunked:
            continue
        winners = (await ranked(guild, past))[:3]
        async with bot.transaction() as db:
            changed = await db.execute("INSERT OR IGNORE INTO season_closed(guild_id,month) VALUES(?,?)",
                                       (guild_id, past))
            if changed.rowcount == 1:
                await db.executemany(
                    "INSERT INTO season_awards(guild_id,month,user_id,place) VALUES(?,?,?,?)",
                    [(guild_id, past, uid, place) for place, (uid, _) in enumerate(winners, start=1)])
