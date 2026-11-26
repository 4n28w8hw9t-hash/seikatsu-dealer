"""Хроники двора: «летопись» и «журнал» стражи (оба — чаты для администрации) + проверка прав бота.
Каналы создаются сами в стиле сервера (берётся с канала устава): ┌|📖・летопись, └|🪶・журнал."""
import asyncio
import os
import re
import time

import discord

from .core import bot

SEIKATSU_GUILD_ID = 1365111872155684986
SEIKATSU_JOURNAL_ID = 1574878922162704546
OLD_CHRONICLE_ID = 1574880613113270433
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


CAT_NAME = "✦ ХРОНИКИ ✦"


def _cat_name(guild, word):
    return CAT_NAME


async def _meta(key, value=None):
    if value is None:
        cur = await bot.db.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = await cur.fetchone()
        return int(row[0]) if row else None
    await bot.db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(value)))
    await bot.db.commit()


def _staff_ow(guild, me):
    ow = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
          me: discord.PermissionOverwrite(view_channel=True, send_messages=True, embed_links=True, attach_files=True)}
    for rid in STAFF_ROLES:
        r = guild.get_role(rid)
        if r:
            ow[r] = discord.PermissionOverwrite(view_channel=True, send_messages=False)
    return ow


async def ensure_channels(guild: discord.Guild):
    """Категория «✦ ХРОНИКИ ✦»: летопись и журнал — обычные чаты, видны только администрации."""
    if guild.id == SEIKATSU_GUILD_ID:
        log = guild.get_channel(SEIKATSU_JOURNAL_ID)
        if not isinstance(log, discord.TextChannel):
            print(f"Журнал стражи {SEIKATSU_JOURNAL_ID} не найден")
            return None, None
        return log, log
    me = guild.me
    if not me.guild_permissions.manage_channels:
        return None, None
    cat = guild.get_channel(await _meta(f"chron_cat_{guild.id}") or 0)
    if not isinstance(cat, discord.CategoryChannel):
        cat = await guild.create_category(CAT_NAME, overwrites=_staff_ow(guild, me), reason="Хроники двора")
        await _meta(f"chron_cat_{guild.id}", cat.id)
    elif cat.name != CAT_NAME:
        await cat.edit(name=CAT_NAME, reason="Исправлено название")
    log = guild.get_channel(await _meta(f"journal_{guild.id}") or 0)
    if not isinstance(log, discord.TextChannel):
        log = await guild.create_text_channel(
            _name(guild, "└", "🪶", "журнал"), category=cat, overwrites=_staff_ow(guild, me),
            topic="Журнал стражи: устав, гербы, админ-панель, входы и выходы.", reason="Журнал стражи")
        await _meta(f"journal_{guild.id}", log.id)
    chat = guild.get_channel(await _meta(f"letopis_{guild.id}") or 0)
    if isinstance(chat, discord.ForumChannel):   # старый пустой форум → заменяем чатом
        try:
            await chat.delete(reason="Летопись теперь обычный чат")
        except discord.HTTPException as ex:
            print("Старый форум не удалён:", repr(ex))
        chat = None
    if not isinstance(chat, discord.TextChannel):
        chat = await guild.create_text_channel(
            _name(guild, "┌", "📖", "летопись"), category=cat, overwrites=_staff_ow(guild, me), position=0,
            topic="Летопись двора: свадьбы, титулы, дуэли. Записи ведёт бот.", reason="Летопись двора")
        await _meta(f"letopis_{guild.id}", chat.id)
    else:
        await chat.edit(overwrites=_staff_ow(guild, me), reason="Летопись только для администрации")
    return chat, log


# ───────── журнал стражи ─────────
async def journal(guild: discord.Guild | None, text: str, color=None):
    if not guild:
        return
    try:
        channel_id = SEIKATSU_JOURNAL_ID if guild.id == SEIKATSU_GUILD_ID else await _meta(f"journal_{guild.id}")
        ch = guild.get_channel(channel_id or 0)
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
    """Строка-лог в летопись (только для администрации)."""
    if not guild:
        return
    try:
        channel_id = SEIKATSU_JOURNAL_ID if guild.id == SEIKATSU_GUILD_ID else await _meta(f"letopis_{guild.id}")
        ch = guild.get_channel(channel_id or 0)
        if not isinstance(ch, discord.TextChannel):
            return
        emoji = dict(TAGS).get(tag, "📜")
        text = re.sub(r"^\W+\s", "", text)   # своё эмодзи в начале текста убираем — оно уже у тега
        e = discord.Embed(description=f"{emoji} **{tag}** · {text}", color=CRIMSON)
        e.set_footer(text=time.strftime("%d.%m %H:%M"))
        await ch.send(embed=e, allowed_mentions=discord.AllowedMentions.none())
    except Exception as ex:
        print("Летопись:", repr(ex))


def clog(guild, tag, title, text, banner=None):
    try:
        asyncio.get_running_loop().create_task(chronicle(guild, tag, title, text, banner))
    except RuntimeError:
        pass


async def move_old_chronicle(guild: discord.Guild) -> str:
    """Переносит записи Seikatsu и удаляет старый канал после успешного копирования."""
    old = guild.get_channel(OLD_CHRONICLE_ID)
    dest = guild.get_channel(SEIKATSU_JOURNAL_ID)
    if guild.id != SEIKATSU_GUILD_ID or not isinstance(dest, discord.TextChannel):
        return "Журнал стражи не найден."
    if old is None:
        return "Старая Летопись уже отсутствует. Новые записи идут в Журнал."
    if not isinstance(old, discord.TextChannel):
        return "Старая Летопись имеет неожиданный тип канала. Удаление отменено."

    me = guild.me
    source_perms = old.permissions_for(me)
    dest_perms = dest.permissions_for(me)
    if not (source_perms.view_channel and source_perms.read_message_history
            and source_perms.manage_channels and dest_perms.view_channel
            and dest_perms.read_message_history and dest_perms.send_messages and dest_perms.embed_links):
        return "Боту нужны права на чтение обоих каналов, запись в Журнал и удаление Летописи."

    def reader_overwrites(channel):
        return {target.id: (overwrite.view_channel, overwrite.read_message_history)
                for target, overwrite in channel.overwrites.items()
                if target.id != me.id and (overwrite.view_channel is not None
                                           or overwrite.read_message_history is not None)}

    if (dest.permissions_for(guild.default_role).view_channel
            or reader_overwrites(old) != reader_overwrites(dest)):
        return "Права чтения Летописи и Журнала различаются. Перенос отменён."

    try:
        public_archive = old.archived_threads(limit=1)
        private_archive = old.archived_threads(limit=1, private=True, joined=not source_perms.manage_threads)
        if (old.threads or await anext(public_archive, None) is not None
                or await anext(private_archive, None) is not None):
            return "В Летописи есть ветки. Перенос и удаление отменены."
        entries = [msg async for msg in old.history(limit=None, oldest_first=True)]
        if any(msg.author.id != me.id or msg.content or len(msg.embeds) != 1
               or msg.attachments or msg.components for msg in entries):
            return "В Летописи есть сообщения, отличные от записей бота. Перенос и удаление отменены."

        if entries:
            marker = re.compile(r" · Летопись #(\d+)$")
            copied = set()
            async for msg in dest.history(limit=None, after=entries[0].created_at):
                if msg.author.id == me.id and len(msg.embeds) == 1:
                    match = marker.search(msg.embeds[0].footer.text or "")
                    if match:
                        copied.add(int(match.group(1)))
            for msg in entries:
                if msg.id in copied:
                    continue
                entry = msg.embeds[0].copy()
                footer = entry.footer.text or "Архив"
                entry.set_footer(text=f"{footer} · Летопись #{msg.id}")
                entry.timestamp = msg.created_at
                await dest.send(embed=entry, allowed_mentions=discord.AllowedMentions.none())
        after = entries[-1] if entries else None
        if await anext(old.history(limit=1, after=after), None) is not None:
            return "В Летописи появились новые записи. Повтори команду, чтобы перенести их."
        await old.delete(reason="Записи Летописи перенесены в Журнал стражи")
    except discord.HTTPException as ex:
        print("Перенос Летописи:", repr(ex))
        return "Discord прервал перенос или удаление. Команду можно повторить."
    return f"Летопись удалена. Записей Летописи в Журнале: {len(entries)}."


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
