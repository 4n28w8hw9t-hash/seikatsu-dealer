"""
Discord-бот с экономикой.
discord.py 2.x + SQLite (aiosqlite). Все команды — слэш-команды.
"""
import math
import os
import random
import asyncio
import io
import time
from datetime import datetime, timedelta, timezone

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

import art

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # необязательно: команды появятся на сервере мгновенно

# ───────── Настройки экономики ─────────
CURRENCY = "🪙"
START_BALANCE = 100
DAILY_BASE = 200            # награда /ежедневно
DAILY_STREAK_BONUS = 25     # +за каждый день серии
DAILY_STREAK_MAX = 10       # максимум дней бонуса
WORK_MIN, WORK_MAX = 50, 150
WORK_COOLDOWN = 60 * 60     # 1 час
MSG_REWARD = (1, 5)         # монеты за сообщение в чате
MSG_COOLDOWN = 60           # не чаще раза в минуту
ROB_COOLDOWN = 2 * 60 * 60  # 2 часа
ROB_CHANCE = 0.4
DATA_DIR = os.getenv("DATA_DIR", ".")  # на хостинге — постоянная папка
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.getenv("DB_PATH") or os.path.join(DATA_DIR, "economy.db")

WORK_TEXTS = [
    "Ты отработал смену на складе и получил {x}",
    "Ты выдал 50 заказов в ПВЗ и заработал {x}",
    "Ты провёл стрим и собрал донатов на {x}",
    "Ты починил соседу компьютер и получил {x}",
    "Ты станцевал на шоу и заработал {x}",
    "Ты нарисовал аватарку на заказ за {x}",
]


def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " " + E("sd_coin", CURRENCY)


def fmt_time(sec: int) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h: parts.append(f"{h} ч")
    if m: parts.append(f"{m} мин")
    if s and not h: parts.append(f"{s} сек")
    return " ".join(parts) or "0 сек"


ECON_LOCK = asyncio.Lock()   # операции с монетами идут строго по одной — защита от дюпа
LAST_CMD: dict[int, float] = {}
CMD_GAP = 1.5                # минимальная пауза между действиями одного игрока, сек


def too_fast(user_id: int) -> bool:
    now = time.time()
    if now - LAST_CMD.get(user_id, 0) < CMD_GAP:
        return True
    LAST_CMD[user_id] = now
    return False


class DeferTree(app_commands.CommandTree):
    """Антиспам, мгновенное личное подтверждение и очередь для операций с монетами."""
    async def _call(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.application_command:
            try:
                if too_fast(interaction.user.id):
                    return await interaction.response.send_message(
                        "⏳ Не так быстро, подожди пару секунд", ephemeral=True)
                await interaction.response.defer(ephemeral=True, thinking=True)
            except discord.HTTPException:
                pass
        async with ECON_LOCK:
            await super()._call(interaction)


async def reply(inter: discord.Interaction, content=None, **kw):
    """Ответ, который видит только сам игрок."""
    if content is not None:
        kw["content"] = content
    kw.setdefault("ephemeral", True)
    if inter.response.is_done():
        return await inter.followup.send(**kw)
    return await inter.response.send_message(**kw)


def E(name: str, fallback: str = "") -> str:
    return getattr(bot, "emo", {}).get(name, fallback)


async def send_card(inter: discord.Interaction, e: discord.Embed, key: str, **kw):
    path = getattr(bot, "banners", {}).get(key)
    if path and os.path.exists(path):
        e.set_image(url="attachment://card.png")
        kw["file"] = discord.File(path, filename="card.png")
    return await reply(inter, embed=e, **kw)


async def send_public(inter: discord.Interaction, e: discord.Embed, key: str, **kw):
    """Сообщение, которое видят все (дуэли и ограбления)."""
    path = getattr(bot, "banners", {}).get(key)
    if path and os.path.exists(path):
        e.set_image(url="attachment://card.png")
        kw["file"] = discord.File(path, filename="card.png")
    try:
        msg = await inter.channel.send(embed=e, **kw)
    except discord.HTTPException:
        await reply(inter, "Не могу написать в этот канал — у бота нет прав")
        return None
    try:
        await inter.delete_original_response()
    except discord.HTTPException:
        pass
    return msg


class EconomyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = False  # для награды за сообщения текст не нужен
        intents.members = False
        super().__init__(command_prefix="!", intents=intents, tree_cls=DeferTree)
        self.db: aiosqlite.Connection | None = None
        self.msg_cd: dict[tuple[int, int], float] = {}

    async def setup_hook(self):
        self.db = await aiosqlite.connect(DB_PATH)
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA synchronous=NORMAL")
        await self.db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            guild_id INTEGER, user_id INTEGER,
            balance INTEGER DEFAULT 0, bank INTEGER DEFAULT 0,
            last_daily INTEGER DEFAULT 0, streak INTEGER DEFAULT 0,
            last_work INTEGER DEFAULT 0, last_rob INTEGER DEFAULT 0,
            PRIMARY KEY(guild_id, user_id));
        CREATE TABLE IF NOT EXISTS shop(
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER,
            name TEXT, price INTEGER, description TEXT, role_id INTEGER);
        CREATE TABLE IF NOT EXISTS inventory(
            guild_id INTEGER, user_id INTEGER, item_id INTEGER,
            qty INTEGER DEFAULT 0, PRIMARY KEY(guild_id, user_id, item_id));
        """)
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
        try:
            await self.db.execute("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0")
        except Exception:
            pass  # колонка уже есть
        for col in ("cls TEXT", "cls_xp INTEGER DEFAULT 0", "cls_changed INTEGER DEFAULT 0",
                    "skill_ready INTEGER DEFAULT 0", "skill_active INTEGER DEFAULT 0",
                    "msgs INTEGER DEFAULT 0", "voice_min INTEGER DEFAULT 0"):
            try:
                await self.db.execute(f"ALTER TABLE users ADD COLUMN {col}")
            except Exception:
                pass
        await self.db.commit()
        tick.start()
        self.add_view(MenuView())  # кнопки панели работают и после перезапуска

        try:  # баннеры команд (рисуются один раз и лежат в data/)
            self.banners = await asyncio.to_thread(
                art.build_all, BANNER_PATH, os.path.join(DATA_DIR, "art_v2"),
                os.path.join(os.path.dirname(BANNER_PATH), "chars.png"))
        except Exception as ex:
            print("Баннеры не созданы:", ex)
            self.banners = {}
        ready = os.path.join(os.path.dirname(BANNER_PATH), "banners")
        if os.path.isdir(ready):  # готовые баннеры с персонажами
            for fn in os.listdir(ready):
                if fn.endswith(".png"):
                    self.banners[fn[:-4]] = os.path.join(ready, fn)
        try:  # свои эмодзи бота
            have = {em.name: em for em in await self.fetch_application_emojis()}
            for name in art.EMOJIS:
                if name not in have:
                    buf = io.BytesIO()
                    art.emoji_png(name).save(buf, "PNG")
                    have[name] = await self.create_application_emoji(name=name, image=buf.getvalue())
            self.emo = {n: str(em) for n, em in have.items()}
        except Exception as ex:
            print("Эмодзи не загружены:", ex)
            self.emo = {}

        if GUILD_ID:
            g = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=g)
            await self.tree.sync(guild=g)
        else:
            await self.tree.sync()

    async def close(self):
        if self.db:
            await self.db.close()
        await super().close()

    # ───── работа с БД ─────
    async def get_user(self, guild_id: int, user_id: int) -> dict:
        await self.db.execute(
            "INSERT OR IGNORE INTO users(guild_id,user_id,balance) VALUES(?,?,?)",
            (guild_id, user_id, START_BALANCE))
        cur = await self.db.execute(
            "SELECT balance,bank,last_daily,streak,last_work,last_rob FROM users "
            "WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        r = await cur.fetchone()
        return dict(zip(["balance", "bank", "last_daily", "streak", "last_work", "last_rob"], r))

    async def add(self, guild_id: int, user_id: int, amount: int, field: str = "balance"):
        await self.get_user(guild_id, user_id)
        await self.db.execute(
            f"UPDATE users SET {field}={field}+? WHERE guild_id=? AND user_id=?",
            (amount, guild_id, user_id))
        await self.db.commit()

    async def set_field(self, guild_id: int, user_id: int, **fields):
        sets = ",".join(f"{k}=?" for k in fields)
        await self.db.execute(
            f"UPDATE users SET {sets} WHERE guild_id=? AND user_id=?",
            (*fields.values(), guild_id, user_id))
        await self.db.commit()


bot = EconomyBot()


def embed(title: str, desc: str = "", color=discord.Color.gold()) -> discord.Embed:
    return discord.Embed(title=title, description=desc, color=color)


@bot.event
async def on_ready():
    print(f"Бот запущен как {bot.user} (id {bot.user.id})")


BANNER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "banner.png")


def welcome_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """Системный канал сервера или первый канал, куда бот может писать."""
    me = guild.me
    if guild.system_channel and guild.system_channel.permissions_for(me).send_messages:
        return guild.system_channel
    for ch in sorted(guild.text_channels, key=lambda c: c.position):
        p = ch.permissions_for(me)
        if p.send_messages and p.embed_links:
            return ch
    return None


@bot.event
async def on_guild_join(guild: discord.Guild):
    ch = welcome_channel(guild)
    if ch is None:
        return
    e = discord.Embed(
        title="🃏 Seikatsu Dealer за столом",
        description=(
            f"Добро пожаловать в экономику **{guild.name}**.\n"
            "Здесь у каждой монеты есть хозяин — и все они проходят через меня.\n\n"
            "**С чего начать**\n"
            "💰 `/баланс` — твой кошелёк и банк\n"
            "🎁 Зарплата приходит сама каждый день в 03:00 МСК\n"
            "💼 `/меню` — всё кнопками; `/работа` — выбрать специальность\n"
            "🏦 `/положить` — спрятать деньги от грабителей\n"
            "🎲 `/монетка` · `/слоты` — испытать удачу\n"
            "🛒 `/магазин` — потратить заработанное\n"
            "🏆 `/топ` — самые богатые\n\n"
            "Играй честно, рискуй с умом."
        ),
        color=discord.Color.from_rgb(209, 53, 57),
    )
    e.set_footer(text="Админам: /эко — управление экономикой и магазином")
    bpath = getattr(bot, "banners", {}).get("welcome", BANNER_PATH)
    if os.path.exists(bpath):
        file = discord.File(bpath, filename="banner.png")
        e.set_image(url="attachment://banner.png")
        await ch.send(embed=e, file=file)
    else:
        await ch.send(embed=e)


# ═════════ Уровни и профессии ═════════
MSK = timezone(timedelta(hours=3))
PAY_HOUR = 3                # зарплата в 03:00 по Москве
XP_MSG = (15, 25)           # опыт за сообщение (не чаще раза в минуту)
XP_VOICE = 10               # опыт за минуту в голосовом канале
WORKER_XP_BONUS = 1.25      # бонус к опыту у тех, кто на рабочей карьере (без специальности)
# (с какого уровня, должность, зарплата в день)
JOBS = [(1, "Разнорабочий", 100), (5, "Прораб", 200), (11, "Инженер", 350),
        (21, "Директор", 550), (36, "Магнат", 800)]


def level_of(xp: int) -> int:
    return math.isqrt(max(xp, 0) // 100) + 1


def xp_for(level: int) -> int:
    return 100 * (level - 1) ** 2


def job_of(level: int) -> tuple[str, int]:
    name, pay = JOBS[0][1], JOBS[0][2]
    for lvl, n, p in JOBS:
        if level >= lvl:
            name, pay = n, p
    return name, pay


async def get_xp(guild_id: int, user_id: int) -> int:
    await bot.get_user(guild_id, user_id)
    cur = await bot.db.execute(
        "SELECT xp FROM users WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    return (await cur.fetchone())[0] or 0


async def add_xp(guild_id: int, user_id: int, amount: int) -> str | None:
    """Начисляет опыт. Возвращает название новой профессии, если она сменилась."""
    old = await get_xp(guild_id, user_id)
    spec = (await get_cls(guild_id, user_id))["cls"]
    if not spec:  # рабочая карьера: пассивный бонус к опыту
        amount = round(amount * WORKER_XP_BONUS)
    await bot.add(guild_id, user_id, amount, "xp")
    if spec:
        return None
    a, b = job_of(level_of(old))[0], job_of(level_of(old + amount))[0]
    return b if a != b else None


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
    job = await add_xp(*key, random.randint(*XP_MSG))
    if job:
        try:
            await message.channel.send(
                f"🎉 {message.author.mention} получает новую должность: **{job}**!")
        except discord.HTTPException:
            pass


async def pay_salaries(today: str):
    await bot.db.execute("UPDATE meta SET value=? WHERE key='last_pay'", (today,))
    cur = await bot.db.execute(
        "SELECT guild_id,user_id,xp,cls,cls_xp,skill_active FROM users")
    count: dict[int, int] = {}
    for g, u, xp, cls, cxp, active in await cur.fetchall():
        pay = job_of(level_of(xp or 0))[1]
        if cls == "mage" and active:  # зелье удачи
            pay = int(pay * mage_mult(cls_level(cxp or 0)))
            await bot.db.execute(
                "UPDATE users SET skill_active=0, skill_ready=?, cls_xp=cls_xp+1 "
                "WHERE guild_id=? AND user_id=?",
                (int(time.time()) + CLASSES["mage"][3], g, u))
        await bot.db.execute(
            "UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?", (pay, g, u))
        count[g] = count.get(g, 0) + 1
    await bot.db.commit()


@tasks.loop(minutes=1)
async def tick():
    try:
        for guild in bot.guilds:  # опыт за голосовой чат
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
                    for uid in ids:
                        await add_xp(guild.id, uid, XP_VOICE)
                        await bot.add(guild.id, uid, 1, "voice_min")
        now = datetime.now(MSK)
        today = now.strftime("%Y-%m-%d")
        cur = await bot.db.execute("SELECT value FROM meta WHERE key='last_pay'")
        row = await cur.fetchone()
        if row is None:  # первый запуск: ближайшая выплата — в следующие 03:00
            start = today if now.hour >= PAY_HOUR else \
                (now - timedelta(days=1)).strftime("%Y-%m-%d")
            await bot.db.execute("INSERT INTO meta VALUES('last_pay',?)", (start,))
            await bot.db.commit()
        elif row[0] != today and now.hour >= PAY_HOUR:
            await pay_salaries(today)
    except Exception as ex:
        print("Ошибка в tick:", repr(ex))


@tick.before_loop
async def _tick_wait():
    await bot.wait_until_ready()


# ═════════ Помощь ═════════
@bot.tree.command(name="помощь", description="Что умеет Seikatsu Dealer")
async def help_cmd(inter: discord.Interaction):
    e = discord.Embed(
        title="🃏 Seikatsu Dealer",
        description=("Банкир и крупье сервера **Seikatsu**.\n"
                     "Зарабатывай, копи, рискуй и трать — все монеты проходят через меня.\n"
                     "**`/меню`** — все действия кнопками, ответы видишь только ты."),
        color=discord.Color.from_rgb(209, 53, 57),
    )
    e.add_field(name=f"{E('sd_gift', '💰')} Заработок",
                value="Зарплата каждый день в 03:00 МСК\nОпыт за чат и голосовые\n`/профиль` · `/работа`",
                inline=True)
    e.add_field(name=f"{E('sd_bank', '🏦')} Деньги",
                value="`/баланс` · `/перевод`\n`/положить` · `/снять`\nБанк защищает от кражи",
                inline=True)
    e.add_field(name="\u200b", value="\u200b", inline=False)
    e.add_field(name=f"{E('sd_dice', '🎲')} Удача",
                value="`/дуэль` — на монеты с игроком\n`/монетка` — x2\n`/слоты` — до x30\n`/ограбить` — 40% успеха\n`/работа` · `/навык` — баффы",
                inline=True)
    e.add_field(name=f"{E('sd_shop', '🛒')} Магазин",
                value="`/магазин` · `/купить`\n`/инвентарь`\nРоли за монеты",
                inline=True)
    e.add_field(name=f"{E('sd_top', '🏆')} Рейтинг", value="`/топ` — самые богатые", inline=False)
    e.set_footer(text="Админам: /эко — управление экономикой и магазином")
    if bot.user:
        e.set_thumbnail(url=bot.user.display_avatar.url)
    await send_card(inter, e, "help")


# ═════════ Основные команды ═════════
@bot.tree.command(name="баланс", description="Показать баланс")
@app_commands.describe(участник="Чей баланс посмотреть")
async def balance(inter: discord.Interaction, участник: discord.Member | None = None):
    m = участник or inter.user
    u = await bot.get_user(inter.guild_id, m.id)
    e = embed(f"Баланс {m.display_name}")
    e.add_field(name="Кошелёк", value=fmt(u["balance"]))
    e.add_field(name="Банк", value=fmt(u["bank"]))
    e.add_field(name="Всего", value=fmt(u["balance"] + u["bank"]))
    e.set_thumbnail(url=m.display_avatar.url)
    await send_card(inter, e, "balance")


def job_title(lvl: int, spec: str | None) -> str:
    return CLASSES[spec][1] if spec else job_of(lvl)[0]


@bot.tree.command(name="профиль", description="Уровень, работа, опыт и статистика")
@app_commands.describe(участник="Чей профиль посмотреть")
async def profile(inter: discord.Interaction, участник: discord.Member | None = None):
    m = участник or inter.user
    g = inter.guild_id
    u = await bot.get_user(g, m.id)
    xp = await get_xp(g, m.id)
    c = await get_cls(g, m.id)
    cur = await bot.db.execute(
        "SELECT msgs,voice_min FROM users WHERE guild_id=? AND user_id=?", (g, m.id))
    msgs, vmin = await cur.fetchone()
    msgs, vmin = msgs or 0, vmin or 0
    lvl = level_of(xp)
    pay = job_of(lvl)[1]
    have, need = xp - xp_for(lvl), xp_for(lvl + 1) - xp_for(lvl)
    spec = c["cls"]
    if spec:
        left = c["ready"] - int(time.time())
        state = "активен" if c["active"] else (f"через {fmt_time(left)}" if left > 0 else "готов")
        extra = [(f"Навык «{CLASSES[spec][2]}»", state),
                 ("Ур. специальности", str(cls_level(c["xp"])))]
        key = f"cls_{spec}"
    else:
        nxt = [(l, n) for l, n, p in JOBS if l > lvl]
        extra = [("Бонус", f"+{round((WORKER_XP_BONUS - 1) * 100)}% опыта"),
                 ("След. должность", f"{nxt[0][1]} с {nxt[0][0]} ур." if nxt else "максимум")]
        key = f"job{max(i for i, j in enumerate(JOBS) if lvl >= j[0]) + 1}"
    data = {"name": m.display_name, "title": job_title(lvl, spec), "level": lvl,
            "have": have, "need": need,
            "cells": [("Зарплата", f"{pay} в день"),
                      ("Монеты", f"{u['balance'] + u['bank']:,}".replace(",", " ")),
                      ("Сообщений", str(msgs)),
                      ("В голосовых", f"{vmin // 60} ч {vmin % 60} мин")] + extra}
    try:
        avatar = await m.display_avatar.replace(size=128, format="png").read()
    except Exception:
        avatar = None
    banners = getattr(bot, "banners", {})
    try:
        png = await asyncio.to_thread(
            art.profile_card, banners.get(key) or banners.get("work"), data, avatar)
        e = discord.Embed(color=discord.Color.from_rgb(209, 53, 57))
        e.set_image(url="attachment://profile.png")
        return await reply(inter, embed=e,
                           file=discord.File(io.BytesIO(png), filename="profile.png"))
    except Exception as ex:
        print("Карточка профиля не нарисована:", repr(ex))
    e = embed(f"Профиль {m.display_name}",
              f"**{data['title']}** · уровень **{lvl}**\nОпыт: {have} / {need}")
    for n, v in data["cells"]:
        e.add_field(name=n, value=v)
    await reply(inter, embed=e)


@bot.tree.command(name="перевод", description="Перевести монеты другому участнику")
@app_commands.describe(участник="Кому", сумма="Сколько")
async def pay(inter: discord.Interaction, участник: discord.Member,
              сумма: app_commands.Range[int, 1]):
    if участник.bot or участник.id == inter.user.id:
        return await reply(inter, "Так нельзя 🙃", ephemeral=True)
    u = await bot.get_user(inter.guild_id, inter.user.id)
    if u["balance"] < сумма:
        return await reply(inter, "Недостаточно монет в кошельке", ephemeral=True)
    await bot.add(inter.guild_id, inter.user.id, -сумма)
    await bot.add(inter.guild_id, участник.id, сумма)
    await reply(inter, 
        f"✅ {inter.user.mention} перевёл {участник.mention} **{fmt(сумма)}**")


@bot.tree.command(name="положить", description="Положить монеты в банк (защита от кражи)")
@app_commands.describe(сумма="Сколько (0 = всё)")
async def deposit(inter: discord.Interaction, сумма: app_commands.Range[int, 0]):
    u = await bot.get_user(inter.guild_id, inter.user.id)
    amount = u["balance"] if сумма == 0 else сумма
    if amount <= 0 or amount > u["balance"]:
        return await reply(inter, "Недостаточно монет", ephemeral=True)
    await bot.add(inter.guild_id, inter.user.id, -amount)
    await bot.add(inter.guild_id, inter.user.id, amount, "bank")
    await reply(inter, f"🏦 Положил в банк **{fmt(amount)}**")


@bot.tree.command(name="снять", description="Снять монеты из банка")
@app_commands.describe(сумма="Сколько (0 = всё)")
async def withdraw(inter: discord.Interaction, сумма: app_commands.Range[int, 0]):
    u = await bot.get_user(inter.guild_id, inter.user.id)
    amount = u["bank"] if сумма == 0 else сумма
    if amount <= 0 or amount > u["bank"]:
        return await reply(inter, "В банке столько нет", ephemeral=True)
    await bot.add(inter.guild_id, inter.user.id, amount)
    await bot.add(inter.guild_id, inter.user.id, -amount, "bank")
    await reply(inter, f"🏦 Снял из банка **{fmt(amount)}**")


@bot.tree.command(name="ограбить", description="Попробовать украсть монеты из кошелька")
@app_commands.describe(участник="Кого грабим")
async def rob(inter: discord.Interaction, участник: discord.Member):
    if участник.bot or участник.id == inter.user.id:
        return await reply(inter, "Так нельзя 🙃", ephemeral=True)
    me = await bot.get_user(inter.guild_id, inter.user.id)
    now = int(time.time())
    if now - me["last_rob"] < ROB_COOLDOWN:
        return await reply(inter, 
            f"🚓 Затаись ещё на **{fmt_time(ROB_COOLDOWN - (now - me['last_rob']))}**",
            ephemeral=True)
    victim = await bot.get_user(inter.guild_id, участник.id)
    if victim["balance"] < 50:
        return await reply(inter, "У него в кошельке почти пусто", ephemeral=True)
    if me["balance"] < 100:
        return await reply(inter, 
            "Нужно хотя бы 100 монет в кошельке (на штраф, если поймают)", ephemeral=True)
    await bot.set_field(inter.guild_id, inter.user.id, last_rob=now)
    boost = await use_skill(inter.guild_id, inter.user.id, "thief")
    if random.random() < (thief_chance(boost) if boost else ROB_CHANCE):
        stolen = random.randint(victim["balance"] // 10, victim["balance"] // 3)
        await bot.add(inter.guild_id, участник.id, -stolen)
        await bot.add(inter.guild_id, inter.user.id, stolen)
        await send_public(inter, embed(
            "🦹 Ограбление", f"{inter.user.mention} украл у {участник.mention} **{fmt(stolen)}**!",
            discord.Color.green()), "rob")
    else:
        fine = random.randint(50, min(300, me["balance"]))
        await bot.add(inter.guild_id, inter.user.id, -fine)
        await bot.add(inter.guild_id, участник.id, fine)
        await send_public(inter, embed(
            "🚨 Ограбление", f"{inter.user.mention} попался и выплатил {участник.mention} штраф **{fmt(fine)}**",
            discord.Color.red()), "rob")


@bot.tree.command(name="топ", description="Самые богатые участники")
async def top(inter: discord.Interaction):
    cur = await bot.db.execute(
        "SELECT user_id, balance+bank AS t FROM users WHERE guild_id=? "
        "ORDER BY t DESC LIMIT 10", (inter.guild_id,))
    rows = await cur.fetchall()
    medals = ["🥇", "🥈", "🥉"]
    lines = [f"{medals[i] if i < 3 else f'`{i+1}.`'} <@{uid}> — **{fmt(t)}**"
             for i, (uid, t) in enumerate(rows)]
    await send_card(inter, embed("🏆 Топ богачей", "\n".join(lines) or "Пусто"), "top",
                    allowed_mentions=discord.AllowedMentions.none())


# ═════════ Казино ═════════
async def take_bet(inter: discord.Interaction, bet: int) -> bool:
    u = await bot.get_user(inter.guild_id, inter.user.id)
    if u["balance"] < bet:
        await reply(inter, "Недостаточно монет для ставки", ephemeral=True)
        return False
    await bot.add(inter.guild_id, inter.user.id, -bet)
    return True


@bot.tree.command(name="монетка", description="Орёл или решка — x2")
@app_commands.describe(ставка="Сколько ставишь", выбор="Орёл или решка")
@app_commands.choices(выбор=[app_commands.Choice(name="Орёл", value="орёл"),
                             app_commands.Choice(name="Решка", value="решка")])
async def coinflip(inter: discord.Interaction, ставка: app_commands.Range[int, 10],
                   выбор: app_commands.Choice[str]):
    if not await take_bet(inter, ставка):
        return
    result = random.choice(["орёл", "решка"])
    if result == выбор.value:
        await bot.add(inter.guild_id, inter.user.id, ставка * 2)
        msg, col = f"Выпал **{result}** — ты выиграл **{fmt(ставка)}**! 🎉", discord.Color.green()
    else:
        msg, col = f"Выпал **{result}** — ты проиграл **{fmt(ставка)}** 😢", discord.Color.red()
    if result != выбор.value:
        msg += await gambler_refund(inter, ставка)
    await send_card(inter, embed("🪙 Монетка", msg, col), "coinflip")


SLOTS = ["🍒", "🍋", "🍇", "🔔", "💎", "7️⃣"]
SLOT_WEIGHTS = [30, 25, 20, 13, 8, 4]
SLOT_PAYOUT = {"🍒": 3, "🍋": 4, "🍇": 5, "🔔": 8, "💎": 15, "7️⃣": 30}


@bot.tree.command(name="слоты", description="Крутить слоты")
@app_commands.describe(ставка="Сколько ставишь")
async def slots(inter: discord.Interaction, ставка: app_commands.Range[int, 10]):
    if not await take_bet(inter, ставка):
        return
    r = random.choices(SLOTS, weights=SLOT_WEIGHTS, k=3)
    line = " | ".join(r)
    if r[0] == r[1] == r[2]:
        win = ставка * SLOT_PAYOUT[r[0]]
        text, col = f"ДЖЕКПОТ! +**{fmt(win)}** 🎰", discord.Color.green()
    elif len(set(r)) == 2:
        win = int(ставка * 1.5)
        text, col = f"Два одинаковых! +**{fmt(win)}**", discord.Color.green()
    else:
        win = 0
        text, col = f"Мимо. −**{fmt(ставка)}**", discord.Color.red()
    if win:
        await bot.add(inter.guild_id, inter.user.id, win)
    if not win:
        text += await gambler_refund(inter, ставка)
    await send_card(inter, embed("🎰 Слоты", f"## {line}\n{text}", col), "slots")


# ═════════ Классы и навыки ═════════
# класс: (эмодзи, название, навык, кулдаун в секундах, баннер)
CLASSES = {
    "thief": ("🦹", "Грабитель", "Отмычка", 24 * 3600, "rob"),
    "mage": ("🧙", "Маг", "Зелье удачи", 3 * 86400, "shop"),
    "gambler": ("🎰", "Шулер", "Счастливая фишка", 12 * 3600, "coinflip"),
}
CLS_LEVELS = [0, 3, 8, 15, 25]   # сколько раз навык должен сработать для уровней 1-5
CLS_CHANGE_CD = 7 * 86400        # сменить класс можно раз в неделю


def cls_level(uses: int) -> int:
    return sum(1 for t in CLS_LEVELS if uses >= t)


def thief_chance(lvl: int) -> float:
    return 0.50 + 0.05 * lvl      # 55% ... 75%


def mage_mult(lvl: int) -> float:
    return 1.25 + 0.25 * lvl      # x1.5 ... x2.5


def gambler_cap(lvl: int) -> int:
    return 50 + 150 * lvl         # 200 ... 800


def skill_text(cls: str, lvl: int) -> str:
    if cls == "thief":
        return f"следующее `/ограбить` — с шансом {round(thief_chance(lvl) * 100)}%"
    if cls == "mage":
        return f"следующая зарплата — x{mage_mult(lvl):g}"
    return f"следующая проигранная ставка в `/монетка` или `/слоты` вернётся (до {gambler_cap(lvl)})"


def cls_banner(cls: str) -> str | None:
    b = getattr(bot, "banners", {})
    return b.get(f"cls_{cls}") or b.get(CLASSES[cls][4])


async def get_cls(guild_id: int, user_id: int) -> dict:
    await bot.get_user(guild_id, user_id)
    cur = await bot.db.execute(
        "SELECT cls,cls_xp,cls_changed,skill_ready,skill_active FROM users "
        "WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    r = await cur.fetchone()
    return {"cls": r[0], "xp": r[1] or 0, "changed": r[2] or 0,
            "ready": r[3] or 0, "active": r[4] or 0}


async def use_skill(guild_id: int, user_id: int, cls: str) -> int:
    """Если у игрока активен навык этого класса — тратит его и возвращает уровень класса."""
    c = await get_cls(guild_id, user_id)
    if c["cls"] != cls or not c["active"]:
        return 0
    await bot.db.execute(
        "UPDATE users SET skill_active=0, skill_ready=?, cls_xp=cls_xp+1 "
        "WHERE guild_id=? AND user_id=?",
        (int(time.time()) + CLASSES[cls][3], guild_id, user_id))
    await bot.db.commit()
    return cls_level(c["xp"])


async def gambler_refund(inter: discord.Interaction, bet: int) -> str:
    lvl = await use_skill(inter.guild_id, inter.user.id, "gambler")
    if not lvl:
        return ""
    back = min(bet, gambler_cap(lvl))
    await bot.add(inter.guild_id, inter.user.id, back)
    return f"\n🎰 Счастливая фишка вернула **{fmt(back)}**"


def cls_embed(cls: str, lvl: int, title: str, text: str) -> discord.Embed:
    e = embed(title, text, discord.Color.from_rgb(209, 53, 57))
    if cls_banner(cls):
        e.set_image(url="attachment://card.png")
    return e


class ClassView(discord.ui.View):
    def __init__(self, owner_id: int):
        super().__init__(timeout=60)
        self.owner_id = owner_id
        btn = discord.ui.Button(label="Разнорабочий", emoji="🧰", style=discord.ButtonStyle.secondary)
        btn.callback = self.picker(None)
        self.add_item(btn)
        for key, (emo, name, _, _, _) in CLASSES.items():
            btn = discord.ui.Button(label=name, emoji=emo, style=discord.ButtonStyle.primary)
            btn.callback = self.picker(key)
            self.add_item(btn)

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.owner_id:
            await inter.response.send_message("Вызови `/работа` сам", ephemeral=True)
            return False
        return True

    def picker(self, key: str | None):
        async def pick(inter: discord.Interaction):
            c = await get_cls(inter.guild_id, inter.user.id)
            now = int(time.time())
            if c["cls"] == key:
                return await inter.response.send_message("Это уже твоя работа", ephemeral=True)
            if c["changed"] and now - c["changed"] < CLS_CHANGE_CD:
                left = fmt_time(CLS_CHANGE_CD - (now - c["changed"]))
                return await inter.response.send_message(
                    f"Сменить работу можно через **{left}**", ephemeral=True)
            await bot.db.execute(
                "UPDATE users SET cls=?, cls_xp=0, cls_changed=?, skill_ready=0, skill_active=0 "
                "WHERE guild_id=? AND user_id=?", (key, now, inter.guild_id, inter.user.id))
            await bot.db.commit()
            self.stop()
            if key is None:
                lvl = level_of(await get_xp(inter.guild_id, inter.user.id))
                e = embed("🧰 Ты снова на рабочей карьере",
                          f"Должность: **{job_of(lvl)[0]}**.\n"
                          f"Бонус: +{round((WORKER_XP_BONUS - 1) * 100)}% опыта за чат и голосовые.",
                          discord.Color.from_rgb(209, 53, 57))
                return await inter.response.edit_message(embed=e, view=None, attachments=[])
            emo, name, skill, cd, _ = CLASSES[key]
            e = cls_embed(key, 1, f"{emo} Теперь ты {name}",
                          f"Навык **{skill}**: {skill_text(key, 1)}.\n"
                          f"Активируй его командой `/навык`. Перезарядка — {fmt_time(cd)}.")
            path = cls_banner(key)
            files = [discord.File(path, filename="card.png")] if path else []
            await inter.response.edit_message(embed=e, view=None, attachments=files)
        return pick


@bot.tree.command(name="работа", description="Выбрать работу: разнорабочий, грабитель, маг или шулер")
async def choose_class(inter: discord.Interaction):
    lines = [f"🧰 **Разнорабочий** (по умолчанию) — карьера по уровню: "
             f"{' → '.join(j[1] for j in JOBS)}. "
             f"Бонус: +{round((WORKER_XP_BONUS - 1) * 100)}% опыта, постоянно."]
    for key, (emo, name, skill, cd, _) in CLASSES.items():
        lines.append(f"{emo} **{name}** — навык «{skill}»: {skill_text(key, 1)}. "
                     f"Перезарядка {fmt_time(cd)}.")
    e = embed("Выбор работы", "\n\n".join(lines) +
              "\n\nЗарплата у всех зависит от уровня. Навык специальности усиливается, "
              "когда срабатывает. Сменить работу можно раз в 7 дней, "
              "уровень специальности при смене сбрасывается.",
              discord.Color.from_rgb(209, 53, 57))
    await reply(inter, embed=e, view=ClassView(inter.user.id))


@bot.tree.command(name="навык", description="Активировать навык своей специальности")
async def skill(inter: discord.Interaction):
    c = await get_cls(inter.guild_id, inter.user.id)
    if not c["cls"]:
        return await reply(
            inter, f"Ты на рабочей карьере: бонус пассивный, "
                   f"+{round((WORKER_XP_BONUS - 1) * 100)}% опыта за чат и голосовые. "
                   "Специальность с навыком можно выбрать в `/работа`.")
    emo, name, sname, cd, _ = CLASSES[c["cls"]]
    lvl = cls_level(c["xp"])
    now = int(time.time())
    if c["active"]:
        return await reply(inter, f"Навык **{sname}** уже активен: {skill_text(c['cls'], lvl)}.")
    if now < c["ready"]:
        return await reply(
            inter, f"⏳ Навык **{sname}** перезаряжается ещё **{fmt_time(c['ready'] - now)}**")
    await bot.set_field(inter.guild_id, inter.user.id, skill_active=1)
    e = cls_embed(c["cls"], lvl, f"{emo} Навык активирован: {sname}",
                  f"{skill_text(c['cls'], lvl).capitalize()}.\n"
                  f"**{name}**, уровень специальности **{lvl}**. "
                  "Перезарядка начнётся, когда навык сработает.")
    kw = {}
    path = cls_banner(c["cls"])
    if path:
        kw["file"] = discord.File(path, filename="card.png")
    await reply(inter, embed=e, **kw)


# ═════════ Дуэли ═════════
class DuelView(discord.ui.View):
    def __init__(self, a: discord.Member, b: discord.Member, bet: int):
        super().__init__(timeout=60)
        self.a, self.b, self.bet = a, b, bet
        self.message = None

    def card(self, text: str, color=discord.Color.gold()) -> discord.Embed:
        e = embed("⚔️ Дуэль", text, color)
        if "duel" in getattr(bot, "banners", {}):
            e.set_image(url="attachment://card.png")
        return e

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.b.id:
            await inter.response.send_message("Это не твоя дуэль", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success)
    async def accept(self, inter: discord.Interaction, button: discord.ui.Button):
        if getattr(self, "done", False):  # защита от двойного нажатия
            return
        self.done = True
        self.stop()
        g = inter.guild_id
        ua, ub = await bot.get_user(g, self.a.id), await bot.get_user(g, self.b.id)
        if ua["balance"] < self.bet or ub["balance"] < self.bet:
            return await inter.response.edit_message(view=None, embed=self.card(
                "Дуэль отменена: у кого-то не хватает монет в кошельке.",
                discord.Color.dark_grey()))
        win, lose = random.sample([self.a, self.b], 2)
        await bot.add(g, lose.id, -self.bet)
        await bot.add(g, win.id, self.bet)
        await inter.response.edit_message(view=None, embed=self.card(
            f"{win.mention} побеждает {lose.mention} и забирает **{fmt(self.bet)}**!",
            discord.Color.green()))

    @discord.ui.button(label="Отказаться", style=discord.ButtonStyle.danger)
    async def decline(self, inter: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await inter.response.edit_message(view=None, embed=self.card(
            f"{self.b.mention} отказался от дуэли с {self.a.mention}.",
            discord.Color.dark_grey()))

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None, embed=self.card(
                    f"{self.b.mention} не ответил на вызов {self.a.mention}.",
                    discord.Color.dark_grey()))
            except discord.HTTPException:
                pass


@bot.tree.command(name="дуэль", description="Вызвать участника на дуэль на монеты")
@app_commands.describe(участник="Кого вызываешь", ставка="Сколько ставит каждый")
async def duel(inter: discord.Interaction, участник: discord.Member,
               ставка: app_commands.Range[int, 10]):
    if участник.bot or участник.id == inter.user.id:
        return await reply(inter, "Так нельзя 🙃", ephemeral=True)
    me = await bot.get_user(inter.guild_id, inter.user.id)
    if me["balance"] < ставка:
        return await reply(inter, "Недостаточно монет в кошельке", ephemeral=True)
    him = await bot.get_user(inter.guild_id, участник.id)
    if him["balance"] < ставка:
        return await reply(inter, "У соперника не хватает монет на такую ставку", ephemeral=True)
    view = DuelView(inter.user, участник, ставка)
    view.message = await send_public(inter, view.card(
        f"{inter.user.mention} вызывает {участник.mention} на дуэль!\n"
        f"Ставка: **{fmt(ставка)}** с каждого, победитель забирает всё.\n"
        "На ответ есть 60 секунд."), "duel", view=view, content=участник.mention)


# ═════════ Магазин ═════════
@bot.tree.command(name="магазин", description="Товары магазина")
async def shop(inter: discord.Interaction):
    cur = await bot.db.execute(
        "SELECT id,name,price,description,role_id FROM shop WHERE guild_id=? ORDER BY price",
        (inter.guild_id,))
    rows = await cur.fetchall()
    e = embed("🛒 Магазин", "Купить: `/купить номер`" if rows else "Магазин пока пуст")
    for i, name, price, desc, role_id in rows:
        extra = f"\nРоль: <@&{role_id}>" if role_id else ""
        e.add_field(name=f"#{i} · {name} — {fmt(price)}", value=(desc or "—") + extra, inline=False)
    await send_card(inter, e, "shop")


@bot.tree.command(name="купить", description="Купить товар")
@app_commands.describe(номер="Номер товара из /магазин")
async def buy(inter: discord.Interaction, номер: int):
    cur = await bot.db.execute(
        "SELECT name,price,role_id FROM shop WHERE id=? AND guild_id=?", (номер, inter.guild_id))
    item = await cur.fetchone()
    if not item:
        return await reply(inter, "Нет такого товара", ephemeral=True)
    name, price, role_id = item
    u = await bot.get_user(inter.guild_id, inter.user.id)
    if u["balance"] < price:
        return await reply(inter, 
            f"Не хватает {fmt(price - u['balance'])}", ephemeral=True)
    if role_id:
        role = inter.guild.get_role(role_id)
        if role is None:
            return await reply(inter, "Роль товара удалена, сообщи админу",
                                                     ephemeral=True)
        if role in inter.user.roles:
            return await reply(inter, "У тебя уже есть эта роль", ephemeral=True)
        try:
            await inter.user.add_roles(role, reason="Покупка в магазине")
        except discord.Forbidden:
            return await reply(inter, 
                "У бота нет прав выдать эту роль (его роль должна быть выше)", ephemeral=True)
    await bot.add(inter.guild_id, inter.user.id, -price)
    await bot.db.execute(
        "INSERT INTO inventory(guild_id,user_id,item_id,qty) VALUES(?,?,?,1) "
        "ON CONFLICT(guild_id,user_id,item_id) DO UPDATE SET qty=qty+1",
        (inter.guild_id, inter.user.id, номер))
    await bot.db.commit()
    await reply(inter, f"🛍️ Ты купил **{name}** за **{fmt(price)}**")


@bot.tree.command(name="инвентарь", description="Твои покупки")
@app_commands.describe(участник="Чей инвентарь")
async def inventory(inter: discord.Interaction, участник: discord.Member | None = None):
    m = участник or inter.user
    cur = await bot.db.execute(
        "SELECT s.name, i.qty FROM inventory i JOIN shop s ON s.id=i.item_id "
        "WHERE i.guild_id=? AND i.user_id=? AND i.qty>0", (inter.guild_id, m.id))
    rows = await cur.fetchall()
    text = "\n".join(f"• {n} ×{q}" for n, q in rows) or "Пусто"
    await reply(inter, embed=embed(f"🎒 Инвентарь {m.display_name}", text))


# ═════════ Меню ═════════
MENU_BUTTONS = [  # (ключ, подпись, эмодзи, ряд)
    ("profile", "Профиль", "👤", 0), ("balance", "Баланс", "💰", 0),
    ("top", "Топ", "🏆", 0), ("help", "Помощь", "❓", 0),
    ("coin", "Монетка", "🪙", 1), ("slots", "Слоты", "🎰", 1),
    ("skill", "Навык", "✨", 1), ("class", "Работа", "🧰", 1),
    ("dep", "Положить", "🏦", 2), ("wd", "Снять", "💵", 2),
    ("shop", "Магазин", "🛒", 2), ("inv", "Инвентарь", "🎒", 2),
]
MENU_MODALS = {"coin": "Монетка", "slots": "Слоты",
               "dep": "Положить в банк (0 = всё)", "wd": "Снять из банка (0 = всё)"}


async def menu_action(key: str, inter: discord.Interaction, n: int = 0, side: str = ""):
    if key == "profile":
        await profile.callback(inter, None)
    elif key == "balance":
        await balance.callback(inter, None)
    elif key == "top":
        await top.callback(inter)
    elif key == "help":
        await help_cmd.callback(inter)
    elif key == "skill":
        await skill.callback(inter)
    elif key == "class":
        await choose_class.callback(inter)
    elif key == "shop":
        await shop.callback(inter)
    elif key == "inv":
        await inventory.callback(inter, None)
    elif key == "dep":
        await deposit.callback(inter, n)
    elif key == "wd":
        await withdraw.callback(inter, n)
    elif key in ("coin", "slots"):
        if n < 10:
            return await reply(inter, "Минимальная ставка — 10")
        if key == "slots":
            return await slots.callback(inter, n)
        s = "решка" if side.strip().lower().startswith("р") else "орёл"
        await coinflip.callback(inter, n, app_commands.Choice(name=s, value=s))


class AmountModal(discord.ui.Modal):
    def __init__(self, key: str):
        super().__init__(title=MENU_MODALS[key])
        self.key = key
        self.amount = discord.ui.TextInput(label="Сумма", placeholder="например 100", max_length=9)
        self.add_item(self.amount)
        self.side = None
        if key == "coin":
            self.side = discord.ui.TextInput(label="Орёл или решка", default="орёл", max_length=10)
            self.add_item(self.side)

    async def on_submit(self, inter: discord.Interaction):
        raw = self.amount.value.strip()
        if not raw.isdigit():
            return await inter.response.send_message("Нужно целое число", ephemeral=True)
        await inter.response.defer(ephemeral=True, thinking=True)
        async with ECON_LOCK:
            await menu_action(self.key, inter, int(raw), self.side.value if self.side else "")


class MenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        for key, label, emo, row in MENU_BUTTONS:
            btn = discord.ui.Button(label=label, emoji=emo, row=row, custom_id=f"sd:{key}",
                                    style=discord.ButtonStyle.secondary)
            btn.callback = self.handler(key)
            self.add_item(btn)

    def handler(self, key: str):
        async def run(inter: discord.Interaction):
            if too_fast(inter.user.id):
                return await inter.response.send_message(
                    "⏳ Не так быстро, подожди пару секунд", ephemeral=True)
            if key in MENU_MODALS:
                return await inter.response.send_modal(AmountModal(key))
            await inter.response.defer(ephemeral=True, thinking=True)
            async with ECON_LOCK:
                await menu_action(key, inter)
        return run


def menu_message() -> dict:
    e = discord.Embed(
        title="🃏 Seikatsu Dealer — меню",
        description=("Жми кнопки — ответ увидишь только ты, чат не засоряется.\n"
                     "Командами остались только действия с другим игроком: "
                     "`/дуэль`, `/ограбить`, `/перевод`, а ещё `/купить`."),
        color=discord.Color.from_rgb(209, 53, 57))
    kw = {"embed": e, "view": MenuView()}
    b = getattr(bot, "banners", {})
    path = b.get("menu") or b.get("help")
    if path and os.path.exists(path):
        e.set_image(url="attachment://card.png")
        kw["file"] = discord.File(path, filename="card.png")
    return kw


@bot.tree.command(name="меню", description="Все действия кнопками")
async def menu(inter: discord.Interaction):
    await reply(inter, **menu_message())


# ═════════ Админ-команды ═════════
admin = app_commands.Group(name="эко", description="Управление экономикой",
                           default_permissions=discord.Permissions(administrator=True),
                           guild_only=True)


@admin.command(name="выдать", description="Выдать монеты")
async def a_give(inter: discord.Interaction, участник: discord.Member, сумма: int):
    await bot.add(inter.guild_id, участник.id, сумма)
    await reply(inter, f"✅ Выдано {участник.mention}: **{fmt(сумма)}**")


@admin.command(name="забрать", description="Забрать монеты из кошелька")
async def a_take(inter: discord.Interaction, участник: discord.Member, сумма: int):
    await bot.add(inter.guild_id, участник.id, -сумма)
    await reply(inter, f"✅ Забрано у {участник.mention}: **{fmt(сумма)}**")


@admin.command(name="сбросить", description="Обнулить участника")
async def a_reset(inter: discord.Interaction, участник: discord.Member):
    await bot.db.execute("DELETE FROM users WHERE guild_id=? AND user_id=?",
                         (inter.guild_id, участник.id))
    await bot.db.execute("DELETE FROM inventory WHERE guild_id=? AND user_id=?",
                         (inter.guild_id, участник.id))
    await bot.db.commit()
    await reply(inter, f"♻️ {участник.mention} обнулён")


@admin.command(name="товар_добавить", description="Добавить товар в магазин")
@app_commands.describe(название="Название", цена="Цена", описание="Описание",
                       роль="Роль, которую получит покупатель (необязательно)")
async def a_add_item(inter: discord.Interaction, название: str,
                     цена: app_commands.Range[int, 1], описание: str | None = None,
                     роль: discord.Role | None = None):
    cur = await bot.db.execute(
        "INSERT INTO shop(guild_id,name,price,description,role_id) VALUES(?,?,?,?,?)",
        (inter.guild_id, название, цена, описание, роль.id if роль else None))
    await bot.db.commit()
    await reply(inter, f"✅ Товар #{cur.lastrowid} **{название}** добавлен")


@admin.command(name="товар_удалить", description="Удалить товар")
async def a_del_item(inter: discord.Interaction, номер: int):
    await bot.db.execute("DELETE FROM shop WHERE id=? AND guild_id=?", (номер, inter.guild_id))
    await bot.db.commit()
    await reply(inter, f"🗑️ Товар #{номер} удалён")


@admin.command(name="панель", description="Поставить в этот канал постоянное меню с кнопками")
async def a_panel(inter: discord.Interaction):
    try:
        await inter.channel.send(**menu_message())
    except discord.HTTPException:
        return await reply(inter, "Не могу написать в этот канал — у бота нет прав")
    await reply(inter, "✅ Панель поставлена. Закрепи сообщение, чтобы оно не уезжало.")


bot.tree.add_command(admin)


@bot.tree.error
async def on_app_error(inter: discord.Interaction, error: app_commands.AppCommandError):
    msg = "Нет прав на эту команду" if isinstance(error, app_commands.MissingPermissions) \
        else f"Ошибка: {error}"
    print("Ошибка команды:", repr(error))
    try:
        await reply(inter, msg, ephemeral=True)
    except discord.HTTPException:
        pass


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Не найден DISCORD_TOKEN. Создай файл .env (см. README.md)")
    bot.run(TOKEN)
