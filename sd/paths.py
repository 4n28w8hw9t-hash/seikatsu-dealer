"""Путь при дворе: знать или вера. От пути и уровня зависит титул в профиле."""
import os
import time

import discord

from .core import card_name, RED, bot, embed, fmt, fmt_time, reply, send_card, send_result
from .levels import (
    PATH_CHANGE_CD, PATHS, RANK_STEP, WORK_COOLDOWN, WORK_PAY, get_path, get_xp, is_female, level_of,
    rank_of, title_banner, titles,
    work_pay)


def ladder(path: str, female: bool = False) -> str:
    return "\n".join(f"`{max(1, i * RANK_STEP):>3}` {name} · {WORK_PAY[i]}"
                     for i, name in enumerate(titles(path, female)))


def path_image(path: str | None, level: int = 1, female: bool = False):
    b = getattr(bot, "banners", {})
    p = b.get(title_banner(path, level, female) or "") if path else None
    p = p or b.get(f"path_{path}") or b.get("help")
    return (card_name(p), p) if p and os.path.exists(p) else None


@bot.tree.command(name="путь", description="Выбрать путь при дворе: знать или вера")
async def choose_path(inter: discord.Interaction):
    cur = await get_path(inter.guild_id, inter.user.id)
    lvl = level_of(await get_xp(inter.guild_id, inter.user.id))
    fem = is_female(inter.user)
    e = embed("Выбор пути", "От пути зависит твой титул — он растёт вместе с уровнем, а с ним "
              "и жалованье за `/работа` (раз в 12 часов).\n"
              "Опыт идёт за сообщения и время в голосовых.\n"
              "-# В списке: уровень · титул · жалованье", RED)
    for key, (emo, name, _) in PATHS.items():
        mark = " — твой путь" if key == cur else ""
        e.add_field(name=f"{emo} {name}{mark}", value=ladder(key, fem), inline=True)
    now = f"Сейчас ты **{rank_of(lvl, cur, fem)}** ({PATHS[cur][1].lower()})" if cur else "Путь пока не выбран"
    e.set_footer(text=f"{now.replace('**', '')}. Сменить путь можно раз в 7 дней, уровень сохраняется.")
    await reply(inter, embed=e, image=path_image(cur, lvl, fem), rows=[[f"path:{k}" for k in PATHS]])


async def pick_path(inter: discord.Interaction, key: str):
    if key not in PATHS:
        return
    g, uid = inter.guild_id, inter.user.id
    cur = await get_path(g, uid)
    if cur == key:
        return await reply(inter, "Ты уже идёшь этим путём", rows=[["path"]])
    c = await bot.db.execute("SELECT path_changed FROM users WHERE guild_id=? AND user_id=?", (g, uid))
    changed = (await c.fetchone())[0] or 0
    now = int(time.time())
    if cur and now - changed < PATH_CHANGE_CD:
        return await reply(inter, f"Сменить путь можно через **{fmt_time(PATH_CHANGE_CD - (now - changed))}**",
                           rows=[["path"]])
    await bot.set_field(g, uid, path=key, path_changed=now)
    lvl = level_of(await get_xp(g, uid))
    emo, name, _ = PATHS[key]
    e = embed(f"{emo} Твой путь — {name}",
              f"Твой титул: **{rank_of(lvl, key, is_female(inter.user))}** (уровень {lvl}).\n\n"
              f"{ladder(key, is_female(inter.user))}", RED)
    await reply(inter, embed=e, image=path_image(key, lvl, is_female(inter.user)),
                rows=[["work", "profile"]])


@bot.tree.command(name="работа", description="Получить жалованье по своему титулу (раз в 12 часов)")
async def work(inter: discord.Interaction):
    g, uid = inter.guild_id, inter.user.id
    path = await get_path(g, uid)
    if not path:
        return await reply(inter, "Сначала выбери путь — знать или вера. От него зависит твой титул "
                           "и жалованье.", rows=[["path"]])
    u = await bot.get_user(g, uid)
    now = int(time.time())
    left = u["last_work"] + WORK_COOLDOWN - now
    if left > 0:
        return await send_result(inter, "work", "Служба ещё идёт",
                                 f"Следующая — через {fmt_time(left)}",
                                 "Пока можно забрать награду или заглянуть в казну.",
                                 rows=[["daily", "balance"]])
    lvl = level_of(await get_xp(g, uid))
    pay = work_pay(lvl)
    from .ledger import record as ledger_record
    from .quests import record
    async with bot.transaction() as db:
        await db.execute(
            "UPDATE users SET last_work=?, works=works+1, balance=balance+? WHERE guild_id=? AND user_id=?",
            (now, pay, g, uid))
        await record(db, g, uid, "work", now)
        await ledger_record(db, g, uid, pay, "work")
    title = rank_of(lvl, path, is_female(inter.user))
    await send_result(inter, title_banner(path, lvl, is_female(inter.user)) or "work",
                      f"{PATHS[path][0]} Служба окончена",
                      f"{title} получает жалованье: +{fmt(pay)}",
                      "Следующая — через 12 ч. Чем выше титул, тем больше жалованье.",
                      rows=[["daily", "balance"]])
