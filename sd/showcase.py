"""Витрина профиля: до трёх заработанных значков."""
import discord
from discord import app_commands

from .achievements import ACHIEVEMENTS, BY_KEY
from .core import E, bot, button_icon, embed, send_card

SEASON_LABELS = ("Золото сезона", "Серебро сезона", "Бронза сезона")
BADGE_LIMIT = 3


def badge(key):
    category, _, ident = key.partition(":")
    if category == "ach" and ident in BY_KEY:
        return BY_KEY[ident][1], f"ach_{ident}", "🏅"
    if category == "season" and ident in ("1", "2", "3"):
        place = int(ident)
        return SEASON_LABELS[place - 1], f"top_{place}", ("🥇", "🥈", "🥉")[place - 1]
    if key == "pair:weekly":
        return "Союз двора", "pair_medal", "💞"
    raise ValueError(key)


async def earned(guild_id, uid, *, db=None):
    db = db if db is not None else bot.db
    async with db.execute("SELECT ach FROM users WHERE guild_id=? AND user_id=?", (guild_id, uid)) as cur:
        row = await cur.fetchone()
    unlocked = set((row[0] or "").split(",")) if row else set()
    keys = [f"ach:{key}" for key, *_ in ACHIEVEMENTS if key in unlocked]
    async with db.execute("SELECT DISTINCT place FROM season_awards WHERE guild_id=? AND user_id=? ORDER BY place",
                          (guild_id, uid)) as cur:
        keys.extend(f"season:{place}" for (place,) in await cur.fetchall() if place in (1,2,3))
    async with db.execute(
        "SELECT 1 FROM pair_weekly WHERE guild_id=? AND (a=? OR b=?) AND claimed=1 LIMIT 1", (guild_id, uid, uid)
    ) as cur:
        if await cur.fetchone():
            keys.append("pair:weekly")
    return keys


async def selection(guild_id, uid, available=None):
    async with bot.db.execute("SELECT badges FROM profile_showcase WHERE guild_id=? AND user_id=?",
                              (guild_id, uid)) as cur:
        row = await cur.fetchone()
    if not row:
        return []
    if available is None:
        available = await earned(guild_id, uid)
    return [key for key in row[0].split(",") if key in available][:BADGE_LIMIT]


async def save(inter, values):
    g, uid = inter.guild_id, inter.user.id
    values = list(dict.fromkeys(values))
    async with bot.transaction() as db:
        available = await earned(g, uid, db=db)
        valid = len(values) <= BADGE_LIMIT and all(key in available for key in values)
        if valid:
            await db.execute(
                "INSERT INTO profile_showcase(guild_id,user_id,badges) VALUES(?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET badges=excluded.badges",
                (g, uid, ",".join(values)))
    await show(inter, "Витрина обновлена." if valid else "Некоторые значки недоступны. Выбери их заново.")


async def show(inter: discord.Interaction, notice=""):
    g, uid = inter.guild_id, inter.user.id
    available = await earned(g, uid)
    selected = await selection(g, uid, available)
    text = "Выбери до трёх заработанных значков для своего профиля."
    if selected:
        text += "\n\n**В профиле:** " + " · ".join(badge(key)[0] for key in selected)
    if not available:
        text += "\n\nПервые значки можно получить за достижения, месячный топ или поручение пары."
    if notice:
        text = f"{notice}\n\n{text}"
    rows = []
    if available:
        options = []
        for key in available[:25]:
            name, icon, fallback = badge(key)
            emoji = E(f"sd_{icon}", E("sd_couple", fallback) if key == "pair:weekly" else fallback)
            options.append(discord.SelectOption(label=name, value=key, default=key in selected,
                                                 emoji=discord.PartialEmoji.from_str(emoji)))
        rows.append([discord.ui.Select(custom_id="sd:showcase:save", placeholder="Выбери значки",
                                       max_values=min(BADGE_LIMIT, len(options)), options=options)])
    if selected:
        rows.append([discord.ui.Button(label="Очистить витрину", custom_id="sd:showcase:clear")])
    icon = button_icon("showcase") or "🏅"
    await send_card(inter, embed(f"{icon} Витрина профиля", text), "profile", rows=rows)


@bot.tree.command(name="витрина", description="Выбрать значки для своего профиля")
@app_commands.guild_only()
async def showcase_cmd(inter: discord.Interaction):
    await show(inter)
