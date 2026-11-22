"""Монеты и профиль: баланс, ежедневная награда, профиль-картинка."""
import asyncio
import time

import discord
from discord import app_commands

import art
from .core import DAILY_REWARD, bot, embed, fmt, fmt_time, iconize, member_name, reply, send_card
from .achievements import ACHIEVEMENTS, get_stats, unlock
from .levels import PATHS, get_path, is_female, next_rank, rank_of, title_banner, work_pay, xp_for

DAY = 24 * 3600


# ═════════ Баланс и награда ═════════
@bot.tree.command(name="баланс", description="Показать баланс")
@app_commands.describe(участник="Чей баланс посмотреть")
async def balance(inter: discord.Interaction, участник: discord.Member | None = None):
    m = участник or inter.user
    u = await bot.get_user(inter.guild_id, m.id)
    e = embed(f"Баланс {m.display_name}", f"## {fmt(u['balance'])}")
    e.set_thumbnail(url=m.display_avatar.url)
    await send_card(inter, e, "balance", rows=[["daily", "coin"]])


@bot.tree.command(name="награда", description=f"Ежедневная награда — {DAILY_REWARD} монет раз в 24 часа")
async def daily(inter: discord.Interaction):
    g, uid = inter.guild_id, inter.user.id
    u = await bot.get_user(g, uid)
    now = int(time.time())
    left = u["last_daily"] + DAY - now
    if left > 0:
        return await reply(inter, f"⏳ Награду можно забрать через **{fmt_time(left)}**",
                           rows=[["balance"]])
    streak = u["streak"] + 1 if now - u["last_daily"] < 2 * DAY else 1
    await bot.set_field(g, uid, last_daily=now, streak=streak)
    await bot.add(g, uid, DAILY_REWARD)
    e = embed("🎁 Награда получена",
              f"+**{fmt(DAILY_REWARD)}**\nДней подряд: **{streak}**\n"
              f"Следующая — через 24 часа.", discord.Color.green())
    await send_card(inter, e, "daily", rows=[["balance", "coin"]])


# ═════════ Перевод ═════════
TRANSFER_MIN = 10


@bot.tree.command(name="перевод", description="Перевести монеты другому участнику")
@app_commands.describe(участник="Кому перевести", сумма=f"Сколько монет (от {TRANSFER_MIN})")
async def transfer(inter: discord.Interaction, участник: discord.Member,
                   сумма: app_commands.Range[int, 1, 1_000_000_000]):
    g, uid, m = inter.guild_id, inter.user.id, участник
    if m.id == uid:
        return await reply(inter, "Самому себе перевести нельзя", rows=[["balance"]])
    if m.bot:
        return await reply(inter, "Ботам монеты не нужны", rows=[["balance"]])
    if сумма < TRANSFER_MIN:
        return await reply(inter, f"Минимальный перевод — {fmt(TRANSFER_MIN)}", rows=[["balance"]])
    u = await bot.get_user(g, uid)
    if u["balance"] < сумма:
        return await reply(inter, f"Не хватает монет: у тебя **{fmt(u['balance'])}**",
                           rows=[["balance", "daily"]])
    await bot.add(g, uid, -сумма)
    await bot.add(g, m.id, сумма)
    left = u["balance"] - сумма
    e = embed("💰 Перевод отправлен",
              f"{m.mention} получает **{fmt(сумма)}**\nОсталось у тебя: **{fmt(left)}**",
              discord.Color.green())
    await send_card(inter, e, "balance", rows=[["balance", "profile"]])
    # получатель узнаёт о переводе в канале
    try:
        await inter.channel.send(
            iconize(f"💰 {inter.user.mention} переводит {m.mention} **{fmt(сумма)}**"),
            allowed_mentions=discord.AllowedMentions(users=[m]))
    except Exception as ex:
        print("Не удалось объявить перевод:", repr(ex))
    try:
        await unlock(g, m.id)     # у получателя могли открыться «денежные» достижения
    except Exception as ex:
        print("Достижения получателя:", repr(ex))


# ═════════ Профиль ═════════
@bot.tree.command(name="профиль", description="Уровень, опыт, баланс, пара и достижения")
@app_commands.describe(участник="Чей профиль посмотреть")
async def profile(inter: discord.Interaction, участник: discord.Member | None = None):
    m = участник or inter.user
    g = inter.guild_id
    await unlock(g, m.id)
    s = await get_stats(g, m.id)
    lvl = s["level"]
    have, need = s["xp"] - xp_for(lvl), xp_for(lvl + 1) - xp_for(lvl)
    partner = "—"
    if s["marriage"]:
        other = s["marriage"]["b"] if s["marriage"]["a"] == m.id else s["marriage"]["a"]
        partner = await member_name(inter.guild, other)
    vmin = s["voice"]
    path = await get_path(g, m.id)
    if path:
        fem = is_female(m)
        title = f"{rank_of(lvl, path, fem)} · {PATHS[path][1]}"
        nxt = next_rank(lvl, path, fem)
        nxt_cell = ("Следующий титул", f"{nxt[1]} с {nxt[0]} ур." if nxt else "высший")
    else:
        title = "Путь не выбран"
        nxt_cell = ("Путь", "выбери в /путь")
    data = {"name": m.display_name, "title": title, "level": lvl, "have": have, "need": need,
            "cells": [("Монеты", f"{s['coins']:,}".replace(",", " ")),
                      ("Пара", partner),
                      ("Жалованье", f"{work_pay(lvl)} / 12 ч" if path else "—"),
                      ("В голосовых", f"{vmin // 60} ч {vmin % 60} мин"),
                      ("Достижения", f"{len(s['ach'])} / {len(ACHIEVEMENTS)}"),
                      nxt_cell]}
    try:
        avatar = await m.display_avatar.replace(size=128, format="png").read()
    except Exception:
        avatar = None
    banners = getattr(bot, "banners", {})
    rows = [["work", "path", "ach", "couple"]]
    try:
        png = await asyncio.to_thread(
            art.profile_card, banners.get(title_banner(path, lvl, is_female(m)) or "")
            or banners.get("profile")
            or banners.get("help"), data, avatar)
        return await reply(inter, image=("profile.png", png), rows=rows)
    except Exception as ex:
        print("Карточка профиля не нарисована:", repr(ex))
    e = embed(f"Профиль {m.display_name}", f"**{title}** · уровень **{lvl}** · опыт {have} / {need}")
    for n, v in data["cells"]:
        e.add_field(name=n, value=v)
    await reply(inter, embed=e, rows=rows)
