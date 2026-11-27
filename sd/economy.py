"""Монеты и профиль: баланс, ежедневная награда, профиль-картинка."""
import asyncio
import time

import discord
from discord import app_commands

import art
from .core import DAILY_REWARD, bot, btn, embed, fmt, fmt_time, iconize, member_name, reply, send_card
from .core import E, send_panel, send_result, _OK, _G
from .achievements import ACHIEVEMENTS, get_stats, unlock
from .levels import PATHS, WORK_COOLDOWN, get_path, is_female, next_rank, rank_of, title_banner, work_pay, xp_for
from .top import _ranked

DAY = 24 * 3600


# ═════════ Баланс и награда ═════════
@bot.tree.command(name="баланс", description="Показать баланс")
@app_commands.describe(участник="Чей баланс посмотреть")
async def balance(inter: discord.Interaction, участник: discord.Member | None = None):
    m = участник or inter.user
    u = await bot.get_user(inter.guild_id, m.id)
    coins = f"{u['balance']:,}".replace(",", " ")
    if m.id != inter.user.id:   # чужой кошелёк — только сумма
        return await send_panel(inter, "balance", f"Казна · {m.display_name}",
                                tiles=[("coin", "Кошелёк", coins, "монет", False)],
                                rows=[["balance", "coin"]])
    now = int(time.time())
    d_left = u["last_daily"] + DAY - now
    w_left = u["last_work"] + WORK_COOLDOWN - now
    path = await get_path(inter.guild_id, m.id)
    from .achievements import get_stats
    lvl = (await get_stats(inter.guild_id, m.id))["level"]
    pay = work_pay(lvl)
    tiles = [("coin", "Кошелёк", coins, "монет", False),
             ("gift", "Награда", f"+{DAILY_REWARD}",
              "готово" if d_left <= 0 else f"через {fmt_time(d_left)}", d_left <= 0)]
    if path:
        tiles.append(("work", "Служба", f"+{pay}",
                      "готово" if w_left <= 0 else f"через {fmt_time(w_left)}", w_left <= 0))
    else:
        tiles.append(("work", "Служба", "—", "сначала выбери путь", False))
    streak = u["streak"] if now - u["last_daily"] < 2 * DAY else 0
    lines = [("hourglass", f"Серия наград: {streak} дн. подряд" +
              (" · на 7-й день — «Завсегдатай»" if streak < 7 else ""))]
    rows = [[btn("daily", "Забрать награду" if d_left <= 0 else "Награда",
                 _OK if d_left <= 0 else _G), "coin", "duel", "history"]]
    await send_panel(inter, "balance", "Казна", subtitle="Твои монеты и что можно сделать сейчас",
                     icon="coin", tiles=tiles, lines=lines, rows=rows)


@bot.tree.command(name="награда", description=f"Ежедневная награда — {DAILY_REWARD} монет раз в 24 часа")
async def daily(inter: discord.Interaction):
    g, uid = inter.guild_id, inter.user.id
    u = await bot.get_user(g, uid)
    now = int(time.time())
    left = u["last_daily"] + DAY - now
    if left > 0:
        return await send_result(inter, "daily", "Награда ещё не готова",
                                 f"Можно забрать через {fmt_time(left)}",
                                 "Пока можно сходить на службу или сыграть в монетку.",
                                 rows=[["work", "coin", "balance"]])
    streak = u["streak"] + 1 if now - u["last_daily"] < 2 * DAY else 1
    from .ledger import record as ledger_record
    from .quests import record
    async with bot.transaction() as db:
        await db.execute(
            "UPDATE users SET last_daily=?, streak=?, balance=balance+? WHERE guild_id=? AND user_id=?",
            (now, streak, DAILY_REWARD, g, uid))
        await record(db, g, uid, "daily", now)
        await ledger_record(db, g, uid, DAILY_REWARD, "daily")
    left_coins = u["balance"] + DAILY_REWARD
    await send_result(inter, "daily", "🎁 Награда получена",
                      f"+{fmt(DAILY_REWARD)} · серия {streak} дн.",
                      f"В кошельке: {left_coins:,} · следующая через 24 ч".replace(",", " "),
                      rows=[["work", "coin", "balance"]])


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
    if not await bot.move_coins(g, uid, m.id, сумма):
        return await reply(inter, "Не хватает монет для перевода", rows=[["balance", "daily"]])
    left = (await bot.get_user(g, uid))["balance"]
    transfer_icon = E("sd_transfer", "💰")
    await send_result(inter, "balance", f"{transfer_icon} Перевод отправлен",
                      f"{m.display_name} получает {fmt(сумма)}",
                      f"Осталось у тебя: {left:,}".replace(",", " "), rows=[["balance"]])
    # получатель узнаёт о переводе в канале
    try:
        await inter.channel.send(
            iconize(f"{transfer_icon} {inter.user.mention} переводит {m.mention} **{fmt(сумма)}**"),
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
    if m.id == inter.user.id:
        from .onboarding import open_profile
        await open_profile(g, m.id)
    await unlock(g, m.id)
    s = await get_stats(g, m.id)
    lvl = s["level"]
    have, need = s["xp"] - xp_for(lvl), xp_for(lvl + 1) - xp_for(lvl)
    partner = "—"
    ring_icon = None
    if s["marriage"]:
        other = s["marriage"]["b"] if s["marriage"]["a"] == m.id else s["marriage"]["a"]
        partner = await member_name(inter.guild, other)
        ring_icon = f"ring_{s['marriage']['ring']}"
    rank_medals = ("top_1", "top_2", "top_3")
    top_level = await _ranked(inter.guild, "xp")
    top_coins = await _ranked(inter.guild, "balance")

    def top_cell(ranked, label):
        place = next((i for i, (uid, _) in enumerate(ranked, 1) if uid == m.id), None)
        medal = rank_medals[place - 1] if place and place <= 3 else None
        value = f"Топ {place} из {len(ranked)}" if place else "—"
        return (label, value, medal)

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
                      ("Пара", partner, ring_icon),
                      ("Жалованье", f"{work_pay(lvl)} / 12 ч" if path else "—"),
                      ("В голосовых", f"{vmin // 60} ч {vmin % 60} мин"),
                      ("Достижения", f"{len(s['ach'])} / {len(ACHIEVEMENTS)}"),
                      nxt_cell,
                      top_cell(top_level, "Топ уровня"),
                      top_cell(top_coins, "Топ монет")]}
    try:
        avatar = await m.display_avatar.replace(size=128, format="png").read()
    except Exception:
        avatar = None
    from .showcase import badge, selection
    from .winter_state import cosmetics
    data["skin"], data["frame"] = await cosmetics(bot.db,g,m.id)
    data["showcase"] = [(key, *badge(key)) for key in await selection(g, m.id)]
    banners = getattr(bot, "banners", {})
    actions = ["work", "path", "ach", "couple"]
    extras = ["quests"]
    if m.id == inter.user.id:
        actions.append("inventory")
        extras.insert(0, "showcase")
        extras.append("wb:dress")
    rows = [actions, extras, "---", ["menu"]]
    try:
        png = await asyncio.to_thread(
            art.profile_card, banners.get(title_banner(path, lvl, is_female(m)) or "")
            or banners.get("profile")
            or banners.get("help"), data, avatar)
        return await reply(inter, image=("profile.png", png), rows=rows, nav=False)
    except Exception as ex:
        print("Карточка профиля не нарисована:", repr(ex))
    e = embed(f"Профиль {m.display_name}", f"**{title}** · уровень **{lvl}** · опыт {have} / {need}")
    for cell in data["cells"]:
        n, v = cell[:2]
        e.add_field(name=n, value=v)
    if data["showcase"]:
        e.add_field(name="Витрина", value=" · ".join(label for _, label, _, _ in data["showcase"]), inline=False)
    await reply(inter, embed=e, rows=rows, nav=False)

