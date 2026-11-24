"""Хроники двора: публичная «летопись» (форум) и закрытый «журнал» стражи + проверка прав бота.
Каналы создаются сами в стиле сервера (берётся с канала устава): ┌|📖・летопись, └|🪶・журнал."""
import asyncio
import os
import re
import time

import discord

from .core import bot

RULES_CHANNEL = 1370852188611416064
MEMBER_ROLE = 1365250956710772756
STAFF_ROLES = (1365248221269463060, 1574154563051720795)
CHECK_ROLES = {   # роли, которые бот выдаёт сам
    1365250956710772756: "member",
    1574505794316279929: "Кавалер",
    1574505809063444571: "Дама",
    1574467661067194410: "разделитель staff",
    1574469695627591700: "разделитель roles",
    1574169992038064318: "роль пары",
}
TAGS = [("Свадьба", "💍"), ("Титул", "👑"), ("Дуэль", "⚔️"), ("Рекорд", "🏆"), ("Ивент", "❄️")]
CRIMSON = discord.Color.from_rgb(150, 30, 40)
DOTS = "・•·∙"


def _style(guild: discord.Guild):
    """Шаблон названий с канала устава: (линия, черта, точка-хвост, ЗАГЛАВНЫЕ?, шаблон категории)."""
    ch = guild.get_channel(RULES_CHANNEL)
    name = ch.name if ch else "┌|📜・устав"
    m = re.search(r"[A-Za-zА-Яа-яЁё]", name)
    prefix = name[:m.start()] if m else name
    tree, bar = (prefix[0], prefix[1]) if len(prefix) >= 2 else ("┌", "|")
    k = max((prefix.rfind(d) for d in DOTS), default=-1)
    tail = prefix[k:] if k >= 0 else "・"
    upper = bool(m) and name[m.start()].isupper()
    cat = ch.category.name if ch and ch.category else "✦ КАНЦЕЛЯРИЯ ✦"
    return tree, bar, tail, upper, cat


def _name(guild, tree, emoji, word):
    _, bar, tail, upper, _ = _style(guild)
    return f"{tree}{bar}{emoji}{tail}{word.upper() if upper else word}"


def _cat_name(guild, word):
    cat = _style(guild)[4]
    return re.sub(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё ]*[A-Za-zА-Яа-яЁё]", word, cat, count=1)


async def _meta(key, value=None):
    if value is None:
        cur = await bot.db.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = await cur.fetchone()
        return int(row[0]) if row else None
    await bot.db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))
    await bot.db.commit()


async def ensure_channels(guild: discord.Guild):
    """Категория «✦ ХРОНИКИ ✦» с форумом-летописью (для member) и журналом (для стражи)."""
    me = guild.me
    if not me.guild_permissions.manage_channels:
        return None, None
    cat = guild.get_channel(await _meta(f"chron_cat_{guild.id}") or 0)
    if not isinstance(cat, discord.CategoryChannel):
        cat = await guild.create_category(_cat_name(guild, "ХРОНИКИ"), reason="Хроники двора")
        await _meta(f"chron_cat_{guild.id}", cat.id)
    everyone, member = guild.default_role, guild.get_role(MEMBER_ROLE)
    log = guild.get_channel(await _meta(f"journal_{guild.id}") or 0)
    if not isinstance(log, discord.TextChannel):
        ow = {everyone: discord.PermissionOverwrite(view_channel=False),
              me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True)}
        for rid in STAFF_ROLES:
            r = guild.get_role(rid)
            if r:
                ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
        log = await guild.create_text_channel(
            _name(guild, "└", "🪶", "журнал"), category=cat, overwrites=ow,
            topic="Журнал стражи: устав, гербы, админ-панель, входы и выходы.", reason="Журнал стражи")
        await _meta(f"journal_{guild.id}", log.id)
    forum = None
    try:
        forum = guild.get_channel(await _meta(f"letopis_{guild.id}") or 0)
        if not isinstance(forum, discord.ForumChannel):
            ow = {everyone: discord.PermissionOverwrite(view_channel=False),
                  me: discord.PermissionOverwrite(view_channel=True, send_messages=True, create_public_threads=True,
                                                  manage_threads=True, attach_files=True, embed_links=True)}
            if member:
                ow[member] = discord.PermissionOverwrite(view_channel=True, send_messages=False,
                                                         create_public_threads=False, send_messages_in_threads=True)
            forum = await guild.create_forum(
                _name(guild, "┌", "📖", "летопись"), category=cat, overwrites=ow,
                topic="Хроника двора: свадьбы, титулы и подвиги. Записи ведёт бот.",
                available_tags=[discord.ForumTag(name=n, emoji=e) for n, e in TAGS], reason="Летопись двора")
            await _meta(f"letopis_{guild.id}", forum.id)
            await forum.move(beginning=True, category=cat, reason="Летопись — первой")
    except discord.HTTPException as ex:   # форум бывает только на сервере-сообществе
        print("Летопись не создана:", repr(ex))
    return forum, log


# ───────── журнал стражи ─────────
async def journal(guild: discord.Guild | None, text: str, color=None):
    if not guild:
        return
    try:
        ch = guild.get_channel(await _meta(f"journal_{guild.id}") or 0)
        if isinstance(ch, discord.TextChannel):
            e = discord.Embed(description=text, color=color or discord.Color.from_rgb(90, 70, 50))
            e.set_footer(text=time.strftime("%d.%m %H:%M"))
            await ch.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
    except Exception as ex:
        print("Журнал:", repr(ex))


def jlog(guild, text, color=None):
    """Запись в журнал без ожидания (можно звать откуда угодно)."""
    try:
        asyncio.get_running_loop().create_task(journal(guild, text, color))
    except RuntimeError:
        pass


# ───────── летопись ─────────
async def chronicle(guild: discord.Guild | None, tag: str, title: str, text: str, banner: str | None = None):
    if not guild:
        return
    try:
        forum = guild.get_channel(await _meta(f"letopis_{guild.id}") or 0)
        if not isinstance(forum, discord.ForumChannel):
            return
        tags = [t for t in forum.available_tags if t.name == tag][:1]
        e = discord.Embed(description=text, color=CRIMSON)
        path = getattr(bot, "banners", {}).get(banner or "")
        kw = {}
        if path and os.path.exists(path):
            fn = "chronicle" + os.path.splitext(path)[1].lower()
            e.set_image(url=f"attachment://{fn}")
            kw["file"] = discord.File(path, filename=fn)
        await forum.create_thread(name=title[:100], embed=e, applied_tags=tags,
                                  allowed_mentions=discord.AllowedMentions.none(), **kw)
    except Exception as ex:
        print("Летопись:", repr(ex))


def clog(guild, tag, title, text, banner=None):
    try:
        asyncio.get_running_loop().create_task(chronicle(guild, tag, title, text, banner))
    except RuntimeError:
        pass


# ───────── проверка прав ─────────
def perm_report(guild: discord.Guild) -> list[str]:
    me, problems = guild.me, []
    gp = me.guild_permissions
    for ok, what in ((gp.manage_roles, "Управлять ролями"), (gp.manage_channels, "Управлять каналами"),
                     (gp.manage_webhooks, "Управлять вебхуками")):
        if not ok:
            problems.append(f"нет права **{what}**")
    for rid, label in CHECK_ROLES.items():
        r = guild.get_role(rid)
        if not r:
            problems.append(f"роль **{label}** ({rid}) не найдена")
        elif r >= me.top_role:
            problems.append(f"роль **{label}** выше роли бота — подними роль бота выше неё")
    for cid, label in ((RULES_CHANNEL, "устав"), (1466426644649742417, "роли")):
        ch = guild.get_channel(cid)
        if not ch:
            problems.append(f"канал **{label}** не найден")
            continue
        p = ch.permissions_for(me)
        miss = [n for ok, n in ((p.view_channel, "видеть"), (p.send_messages, "писать"),
                                (p.embed_links, "встраивать ссылки"), (p.attach_files, "прикреплять файлы"))
                if not ok]
        if miss:
            problems.append(f"в канале **{label}** бот не может: {', '.join(miss)}")
    return problems


@bot.listen("on_ready")
async def _chronicle_startup():
    for g in bot.guilds:
        try:
            await ensure_channels(g)
        except Exception as ex:
            print("Хроники не созданы:", repr(ex))
        probs = perm_report(g)
        bot.perm_report = getattr(bot, "perm_report", {})
        bot.perm_report[g.id] = probs
        print("[ПРОВЕРКА ПРАВ]", "всё в порядке" if not probs else "; ".join(probs))
        await journal(g, "🔎 **Бот перезапущен.** Проверка прав: " +
                      ("всё в порядке ✅" if not probs else "\n• " + "\n• ".join(probs)),
                      discord.Color.green() if not probs else discord.Color.orange())


@bot.listen("on_member_join")
async def _j_join(m: discord.Member):
    await journal(m.guild, f"🚪 {m.mention} входит ко двору · аккаунт создан <t:{int(m.created_at.timestamp())}:R>")


@bot.listen("on_member_remove")
async def _j_leave(m: discord.Member):
    await journal(m.guild, f"🕯️ {m.mention} ({m}) покидает двор", discord.Color.dark_grey())
