"""Уровни: опыт за сообщения и голосовые, опыт пары, служебный цикл раз в минуту."""
import math
import random
import time

import discord
from discord.ext import tasks

from .core import MSG_COOLDOWN, bot, bot_channel, iconize

XP_MSG = (15, 25)      # опыт за сообщение (не чаще раза в минуту)
XP_VOICE = 10          # опыт за минуту в голосовом канале (если в канале хотя бы двое)

# путь: (эмодзи, название, титулы с 0, 10, 20 … 100 уровня)
PATHS = {
    "noble": ("👑", "Знать", ["Йонкер", "Оруженосец", "Рыцарь", "Барон", "Виконт", "Граф",
                             "Маркиз", "Герцог", "Принц", "Король", "Император"]),
    "faith": ("✝️", "Вера", ["Министрант", "Аколит", "Дьякон", "Священник", "Епископ",
                            "Архиепископ", "Верховный архиепископ", "Патриарх", "Кардинал",
                            "Легат", "Святой"]),
}
# женские титулы — для тех, у кого роль «Девушка»
PATHS_FEMALE = {
    "noble": ["Йонкфрау", "Оруженосица", "Дама-рыцарь", "Баронесса", "Виконтесса", "Графиня",
              "Маркиза", "Герцогиня", "Принцесса", "Королева", "Императрица"],
    "faith": ["Министрантка", "Аколитка", "Диаконисса", "Жрица", "Настоятельница", "Аббатиса",
              "Верховная аббатиса", "Матриарх", "Кардинал", "Легат", "Святая"],
}
# по каким ролям бот понимает пол (название роли, регистр не важен); без роли — мужские титулы
FEMALE_ROLES = {"девушка"}
MALE_ROLES = {"парень"}
MALE_ROLE_ID = 1574505794316279929     # Кавалер
FEMALE_ROLE_ID = 1574505809063444571   # Дама
RANK_STEP = 10               # новый титул каждые 10 уровней
# жалованье за /работа по ступеням титула (одинаковое для обоих путей)
WORK_PAY = [50, 80, 120, 170, 230, 300, 380, 470, 570, 680, 800]
WORK_COOLDOWN = 12 * 3600    # работать можно раз в 12 часов
PATH_CHANGE_CD = 7 * 86400   # сменить путь можно раз в неделю
# уровни, на которых меняется титул — на них бот пишет в чат
RANK_LEVELS = [i * RANK_STEP for i in range(1, len(WORK_PAY))]


def tier_of(level: int) -> int:
    """Ступень титула 0..10: 1–9 ур. → 0, 10–19 → 1, …, 100+ → 10."""
    return min(level // RANK_STEP, len(WORK_PAY) - 1)


def is_female(member) -> bool:
    """Девушка — если у участника есть роль из FEMALE_ROLES (и нет роли из MALE_ROLES)."""
    roles = getattr(member, "roles", [])
    ids = {r.id for r in roles}
    if FEMALE_ROLE_ID in ids or MALE_ROLE_ID in ids:   # роли «Дама» / «Кавалер» из канала ролей
        return FEMALE_ROLE_ID in ids and MALE_ROLE_ID not in ids
    names = {r.name.strip().lower() for r in roles}
    return bool(names & FEMALE_ROLES) and not names & MALE_ROLES


def titles(path: str, female: bool = False) -> list[str]:
    return PATHS_FEMALE[path] if female else PATHS[path][2]


def rank_of(level: int, path: str | None, female: bool = False) -> str | None:
    """Титул по уровню, пути и полу (None, если путь не выбран)."""
    return titles(path, female)[tier_of(level)] if path in PATHS else None


def title_banner(path: str | None, level: int, female: bool = False) -> str | None:
    """Баннер титула: banners/<путь>_<ступень>[_f].jpg, например noble_0_f.
    Если картинки нет — ближайший титул ниже того же пола, потом другого пола, потом баннер пути."""
    b = getattr(bot, "banners", {})
    if path not in PATHS:
        return None
    t = tier_of(level)
    for sfx in (("_f", "") if female else ("", "_f")):
        for i in range(t, -1, -1):
            if f"{path}_{i}{sfx}" in b:
                return f"{path}_{i}{sfx}"
    return f"path_{path}" if f"path_{path}" in b else None


def work_pay(level: int) -> int:
    return WORK_PAY[tier_of(level)]


def next_rank(level: int, path: str | None, female: bool = False) -> tuple[int, str] | None:
    t = tier_of(level) + 1
    if path not in PATHS or t >= len(WORK_PAY):
        return None
    return t * RANK_STEP, titles(path, female)[t]


async def get_path(guild_id: int, user_id: int) -> str | None:
    await bot.get_user(guild_id, user_id)
    cur = await bot.db.execute("SELECT path FROM users WHERE guild_id=? AND user_id=?",
                               (guild_id, user_id))
    r = await cur.fetchone()
    return r[0] if r and r[0] in PATHS else None


def level_of(xp: int) -> int:
    return math.isqrt(max(xp, 0) // 100) + 1


def xp_for(level: int) -> int:
    return 100 * (level - 1) ** 2


async def get_xp(guild_id: int, user_id: int) -> int:
    await bot.get_user(guild_id, user_id)
    cur = await bot.db.execute(
        "SELECT xp FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    return (await cur.fetchone())[0] or 0


async def add_xp(guild_id: int, user_id: int, amount: int, *, voice_at=None) -> int | None:
    """Начисляет опыт игроку и его паре. Возвращает новый уровень, если на нём меняется титул."""
    from .season import record as record_season
    async with bot.transaction() as db:
        await bot.ensure_user(db, guild_id, user_id)
        async with db.execute("SELECT xp FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id)) as cur:
            old = (await cur.fetchone())[0] or 0
        await db.execute("UPDATE users SET xp=xp+? WHERE guild_id=? AND user_id=?", (amount, guild_id, user_id))
        await db.execute("UPDATE marriages SET xp=xp+? WHERE guild_id=? AND (a=? OR b=?)",
                         (amount, guild_id, user_id, user_id))
        await record_season(db, guild_id, user_id, amount)
        if voice_at is not None:
            from .quests import record
            await db.execute("UPDATE users SET voice_min=voice_min+1 WHERE guild_id=? AND user_id=?",
                             (guild_id, user_id))
            await record(db, guild_id, user_id, "voice", voice_at)
    a, b = level_of(old), level_of(old + amount)
    reached = [lvl for lvl in RANK_LEVELS if a < lvl <= b]
    return reached[-1] if reached else None


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    key = (message.guild.id, message.author.id)
    await bot.add(*key, 1, "msgs")
    now = time.time()
    if now - bot.msg_cd.get(key, 0) < MSG_COOLDOWN:
        return
    bot.msg_cd[key] = now
    lvl = await add_xp(*key, random.randint(*XP_MSG))
    from .achievements import unlock, unlocked_text
    new = await unlock(*key)
    out = bot_channel(message.guild) or message.channel   # объявления — в канал бота
    if new:
        try:
            await out.send(
                iconize(f"🏅 {message.author.mention} открывает достижение!\n{unlocked_text(new)}"),
                allowed_mentions=discord.AllowedMentions(users=False))
        except discord.HTTPException:
            pass
    if lvl:
        await announce_title(message.guild, message.author, lvl, out)


async def announce_title(guild, member, lvl, out):
    path = await get_path(guild.id, member.id)
    title = rank_of(lvl, path, is_female(member))
    text = (f"🥀 {member.mention} достигает **{lvl} уровня** и получает титул "
            f"**{title}**!") if title else f"🥀 {member.mention} достигает **{lvl} уровня**!"
    try:
        await out.send(iconize(text))
    except discord.HTTPException:
        pass
    if title:
        from .chronicle import clog
        fem = is_female(member)
        clog(guild, "Титул", f"{member.display_name} — {title}",
             f"👑 {member.mention} достигает **{lvl} уровня** и получает титул **{title}**.",
             title_banner(path, lvl, fem))


@tasks.loop(minutes=1)
async def tick():
    try:
        from .pair_quests import record_rooms
        now = time.time()
        for guild in bot.guilds:  # опыт за голосовой чат
            occupied = {}
            for vc in guild.voice_channels:
                if guild.afk_channel and vc.id == guild.afk_channel.id:
                    continue
                ids = []
                for uid, vs in vc.voice_states.items():
                    m = guild.get_member(uid)
                    if (m and m.bot) or vs.self_deaf or vs.deaf:
                        continue
                    ids.append(uid)
                if len(ids) >= 2:  # в одиночку опыт не идёт
                    occupied[vc.id] = frozenset(ids)
                    for uid in ids:
                        lvl = await add_xp(guild.id, uid, XP_VOICE, voice_at=now)
                        member = guild.get_member(uid)
                        if lvl and member:
                            await announce_title(guild, member, lvl, bot_channel(guild) or vc)
            await record_rooms(guild.id, occupied, now)
    except Exception as ex:
        print("Ошибка начисления опыта в войсе:", repr(ex))
    from .market import recover_role_purchases
    from .marriage import clean_pending_rooms, clean_retired_rooms, clean_rooms
    from .season import close_seasons
    for job in (clean_pending_rooms, clean_rooms, clean_retired_rooms, recover_role_purchases, close_seasons):
        try:
            await job()
        except Exception as ex:
            print("Ошибка фоновой задачи:", job.__name__, repr(ex))


@tick.before_loop
async def _tick_wait():
    await bot.wait_until_ready()
