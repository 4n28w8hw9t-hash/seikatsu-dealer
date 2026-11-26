"""Совместное поручение для пары."""
import time

import discord
from discord import app_commands

from .core import bot, button_icon, embed, reply, send_card
from .marriage import get_marriage
from .quests import week_window

GOAL, REWARD = 30, 300


def quest_key(guild_id, marriage, week):
    return guild_id, marriage["a"], marriage["b"], marriage["since"], week


async def progress(db, key):
    async with db.execute(
        "SELECT voice,claimed FROM pair_weekly WHERE guild_id=? AND a=? AND b=? AND since=? AND week=?",
        key
    ) as cur:
        return await cur.fetchone() or (0, 0)


async def record_rooms(guild_id, occupied, now):
    if not occupied:
        return
    week, _ = week_window(now)
    async with bot.transaction() as db:
        async with db.execute(
            "SELECT a,b,since,room_id FROM marriages WHERE guild_id=? AND room_id IS NOT NULL", (guild_id,)
        ) as cur:
            rooms = await cur.fetchall()
        for a, b, since, room_id in rooms:
            members = occupied.get(room_id, ())
            if a in members and b in members:
                await db.execute(
                    "INSERT INTO pair_weekly(guild_id,a,b,since,week,voice,last_minute) VALUES(?,?,?,?,?,1,?) "
                    "ON CONFLICT(guild_id,a,b,since,week) DO UPDATE SET voice=voice+1,last_minute=excluded.last_minute "
                    "WHERE voice<? AND last_minute<excluded.last_minute",
                    (guild_id, a, b, since, week, int(now // 60), GOAL))


async def show(inter: discord.Interaction, notice=""):
    g, uid = inter.guild_id, inter.user.id
    mar = await get_marriage(g, uid)
    if not mar:
        return await reply(inter, "Совместное поручение доступно участникам пары.", rows=[["couple"]])
    week, ends = week_window()
    count, claimed = await progress(bot.db, quest_key(g, mar, week))
    reward = "Награда получена." if claimed else f"Награда: **{REWARD} опыта пары** и значок для витрины."
    text = (f"Проведите **{GOAL} минут вдвоём в своей лав-руме**.\n"
            f"Прогресс пары: **{count}/{GOAL} мин**\n\n{reward}\n-# Новая неделя <t:{ends}:R>.")
    if notice:
        text = f"{notice}\n\n{text}"
    rows = [["loveroom", "couple"]]
    if count >= GOAL and not claimed:
        rows.insert(0, ["pairquest:claim"])
    icon = button_icon("pair_quest") or "📜"
    await send_card(inter, embed(f"{icon} Поручение пары", text), "marry", rows=rows)


async def claim(inter: discord.Interaction):
    g, uid = inter.guild_id, inter.user.id
    async with bot.transaction() as db:
        mar = await get_marriage(g, uid, db=db)
        week, _ = week_window()
        notice = "Поручение ещё не завершено."
        if mar:
            key = quest_key(g, mar, week)
            count, claimed = await progress(db, key)
            if claimed:
                notice = "Пара уже получила награду за эту неделю."
            elif count >= GOAL:
                await db.execute(
                    "UPDATE pair_weekly SET claimed=1 WHERE guild_id=? AND a=? AND b=? AND since=? AND week=?", key)
                await db.execute(
                    "UPDATE marriages SET xp=xp+? WHERE guild_id=? AND a=? AND b=? AND since=?",
                    (REWARD, *key[:-1]))
                notice = f"Получено **{REWARD} опыта пары**. Памятный значок доступен в витрине обоим."
    await show(inter, notice)


@bot.tree.command(name="поручение_пары", description="Совместное задание на неделю для пары")
@app_commands.guild_only()
async def pair_quest_cmd(inter: discord.Interaction):
    await show(inter)
