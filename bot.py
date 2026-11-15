"""
Discord-бот с экономикой.
discord.py 2.x + SQLite (aiosqlite). Все команды — слэш-команды.
"""
import os
import random
import asyncio
import io
import time

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
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


class DeferTree(app_commands.CommandTree):
    """Сразу подтверждаем команду, чтобы Discord не ждал дольше 3 секунд."""
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.type == discord.InteractionType.application_command \
                and not interaction.response.is_done():
            try:
                await interaction.response.defer(thinking=True)
            except discord.HTTPException:
                pass
        return True


async def reply(inter: discord.Interaction, content=None, **kw):
    if content is not None:
        kw["content"] = content
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
        await self.db.commit()

        try:  # баннеры команд (рисуются один раз и лежат в data/)
            self.banners = await asyncio.to_thread(
                art.build_all, BANNER_PATH, os.path.join(DATA_DIR, "art_v1"))
        except Exception as ex:
            print("Баннеры не созданы:", ex)
            self.banners = {}
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
            "🎁 `/ежедневно` — награда каждый день\n"
            "💼 `/работа` — заработать монет\n"
            "🏦 `/положить` — спрятать деньги от грабителей\n"
            "🎲 `/монетка` · `/слоты` — испытать удачу\n"
            "🛒 `/магазин` — потратить заработанное\n"
            "🏆 `/топ` — самые богатые\n\n"
            "Играй честно, рискуй с умом."
        ),
        color=discord.Color.from_rgb(209, 53, 57),
    )
    e.set_footer(text="Админам: /эко — управление экономикой и магазином")
    if os.path.exists(BANNER_PATH):
        file = discord.File(BANNER_PATH, filename="banner.png")
        e.set_image(url="attachment://banner.png")
        await ch.send(embed=e, file=file)
    else:
        await ch.send(embed=e)


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    key = (message.guild.id, message.author.id)
    now = time.time()
    if now - bot.msg_cd.get(key, 0) >= MSG_COOLDOWN:
        bot.msg_cd[key] = now
        await bot.add(*key, random.randint(*MSG_REWARD))


# ═════════ Помощь ═════════
@bot.tree.command(name="помощь", description="Что умеет Seikatsu Dealer")
async def help_cmd(inter: discord.Interaction):
    e = discord.Embed(
        title="🃏 Seikatsu Dealer",
        description=("Банкир и крупье сервера **Seikatsu**.\n"
                     "Зарабатывай, копи, рискуй и трать — все монеты проходят через меня."),
        color=discord.Color.from_rgb(209, 53, 57),
    )
    e.add_field(name=f"{E('sd_gift', '💰')} Заработок",
                value="`/ежедневно` — награда раз в сутки\n`/работа` — раз в час\nМонеты за общение в чате",
                inline=True)
    e.add_field(name=f"{E('sd_bank', '🏦')} Деньги",
                value="`/баланс` · `/перевод`\n`/положить` · `/снять`\nБанк защищает от кражи",
                inline=True)
    e.add_field(name="\u200b", value="\u200b", inline=False)
    e.add_field(name=f"{E('sd_dice', '🎲')} Удача",
                value="`/монетка` — x2\n`/слоты` — до x30\n`/ограбить` — 40% успеха",
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


@bot.tree.command(name="ежедневно", description="Забрать ежедневную награду")
async def daily(inter: discord.Interaction):
    u = await bot.get_user(inter.guild_id, inter.user.id)
    now = int(time.time())
    passed = now - u["last_daily"]
    if passed < 86400:
        return await reply(inter, 
            f"⏳ Следующая награда через **{fmt_time(86400 - passed)}**", ephemeral=True)
    streak = u["streak"] + 1 if passed < 2 * 86400 else 1
    reward = DAILY_BASE + DAILY_STREAK_BONUS * (min(streak, DAILY_STREAK_MAX) - 1)
    await bot.add(inter.guild_id, inter.user.id, reward)
    await bot.set_field(inter.guild_id, inter.user.id, last_daily=now, streak=streak)
    await send_card(inter, embed(
        "🎁 Ежедневная награда", f"Ты получил **{fmt(reward)}**\nСерия: **{streak}** дн."), "daily")


@bot.tree.command(name="работа", description="Поработать и заработать монет")
async def work(inter: discord.Interaction):
    u = await bot.get_user(inter.guild_id, inter.user.id)
    now = int(time.time())
    if now - u["last_work"] < WORK_COOLDOWN:
        left = WORK_COOLDOWN - (now - u["last_work"])
        return await reply(inter, 
            f"😮‍💨 Ты устал. Отдохни ещё **{fmt_time(left)}**", ephemeral=True)
    amount = random.randint(WORK_MIN, WORK_MAX)
    await bot.add(inter.guild_id, inter.user.id, amount)
    await bot.set_field(inter.guild_id, inter.user.id, last_work=now)
    text = random.choice(WORK_TEXTS).format(x=f"**{fmt(amount)}**")
    await send_card(inter, embed("💼 Работа", text, discord.Color.green()), "work")


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
    if random.random() < ROB_CHANCE:
        stolen = random.randint(victim["balance"] // 10, victim["balance"] // 3)
        await bot.add(inter.guild_id, участник.id, -stolen)
        await bot.add(inter.guild_id, inter.user.id, stolen)
        await reply(inter, 
            f"🦹 {inter.user.mention} украл у {участник.mention} **{fmt(stolen)}**!")
    else:
        fine = random.randint(50, min(300, me["balance"]))
        await bot.add(inter.guild_id, inter.user.id, -fine)
        await bot.add(inter.guild_id, участник.id, fine)
        await reply(inter, 
            f"🚨 {inter.user.mention} попался и выплатил {участник.mention} штраф **{fmt(fine)}**")


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
    await send_card(inter, embed("🎰 Слоты", f"## {line}\n{text}", col), "slots")


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
