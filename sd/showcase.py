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
    if key == "court:first_day":
        return "Первый день при дворе", "court_first_badge", "📜"
    if key == "court:event":
        return "Общее дело", "court_event_badge", "🏆"
    if category == "winter":
        from .winter_state import SIGILS
        if ident == "snowball": return "Первый снежок", "wb_snowball", "❄️"
        if ident == "princess": return "Дар Принцессы", "wb_santa", "🎁"
        if ident == "rings":
            return "Кольца Зимней луны", "wb_rings", "💍"
        if ident in ("0","1","2","3"):
            return SIGILS[int(ident)], "wb_boss"+ident, "❄️"
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
    async with db.execute("SELECT 1 FROM onboarding WHERE guild_id=? AND user_id=? AND awarded=1",
                          (guild_id, uid)) as cur:
        if await cur.fetchone():
            keys.append("court:first_day")
    async with db.execute("SELECT 1 FROM court_events WHERE guild_id=? AND user_id=? AND claimed=1 LIMIT 1",
                          (guild_id, uid)) as cur:
        if await cur.fetchone():
            keys.append("court:event")
    from .winter_state import first, progress, targets
    goals = await targets(db,guild_id)
    totals, mine = await progress(db,guild_id,uid)
    keys.extend(f"winter:{i}" for i,n in enumerate(mine) if n and totals[i]>=goals[i])
    if await first(db,"SELECT 1 FROM winter26_rings WHERE g=? AND u=?",(guild_id,uid)):
        keys.append("winter:rings")
    from .snowballs import inventory
    items=await inventory(db,guild_id,uid)
    keys.extend("winter:"+k for k in ("snowball","princess") if k in items)
    return keys


async def selection(guild_id, uid, available=None, *, db=None):
    db = db if db is not None else bot.db
    async with db.execute("SELECT badges FROM profile_showcase WHERE guild_id=? AND user_id=?",
                              (guild_id, uid)) as cur:
        row = await cur.fetchone()
    if not row:
        return []
    if available is None:
        available = await earned(guild_id, uid, db=db)
    return [key for key in row[0].split(",") if key in available][:BADGE_LIMIT]


async def save(inter, values=(), *, toggle=None):
    g, uid = inter.guild_id, inter.user.id
    values = list(dict.fromkeys(values))
    async with bot.transaction() as db:
        available = await earned(g, uid, db=db)
        notice = ""
        if toggle is not None:
            values = await selection(g, uid, available, db=db)
            if toggle not in available:
                notice = "Этот значок недоступен."
            elif toggle in values:
                values.remove(toggle)
            elif len(values) == BADGE_LIMIT:
                notice = "Сначала убери один из значков с витрины."
            else:
                values.append(toggle)
        elif len(values) > BADGE_LIMIT or any(key not in available for key in values):
            notice = "Некоторые значки недоступны. Выбери их заново."
        if not notice:
            await db.execute(
                "INSERT INTO profile_showcase(guild_id,user_id,badges) VALUES(?,?,?) "
                "ON CONFLICT(guild_id,user_id) DO UPDATE SET badges=excluded.badges",
                (g, uid, ",".join(values)))
    await show(inter, notice or "Витрина обновлена.")


def badge_emoji(key):
    _, icon, fallback = badge(key)
    return button_icon(icon) or (E("sd_couple", fallback) if key == "pair:weekly" else fallback)


async def show(inter: discord.Interaction, notice=""):
    g, uid = inter.guild_id, inter.user.id
    available = await earned(g, uid)
    selected = await selection(g, uid, available)
    lines = [f"**Значки в профиле · {len(selected)}/{BADGE_LIMIT}**"]
    from .top import month_label
    async with bot.db.execute(
        "SELECT place,MAX(month) FROM season_awards WHERE guild_id=? AND user_id=? GROUP BY place", (g, uid)
    ) as cur:
        months = {f"season:{place}": month_label(month) for place, month in await cur.fetchall()}
    for key in selected:
        detail = f" · {months[key]}" if key in months else ""
        lines.append(f"{badge_emoji(key)} {badge(key)[0]}{detail}")
    if not selected:
        lines.append("Витрина пока пуста.")
    if not available:
        lines.append("Значки можно получить за достижения, месячный топ и поручения пары.")
    if notice:
        lines.extend(("", notice))
    rows = []
    if available:
        options = [
            discord.SelectOption(
                label=badge(key)[0], value=key,
                description=("Убрать" if key in selected else "Добавить")
                + (f" · {months[key]}" if key in months else " · Витрина"),
                emoji=discord.PartialEmoji.from_str(badge_emoji(key)),
            )
            for key in available
        ]
        rows.extend(["---", [discord.ui.Select(
            custom_id="sd:showcase:toggle", placeholder="Добавить или убрать значок", options=options[:25],
        )]])
        if len(options) > 25:
            rows.append([discord.ui.Select(custom_id="sd:showcase:more",
                                           placeholder="Другие значки", options=options[25:])])
    if selected:
        clear_icon = discord.PartialEmoji.from_str(button_icon("cancel") or "✖️")
        rows.append([discord.ui.Button(label="Очистить витрину", emoji=clear_icon, custom_id="sd:showcase:clear")])
    icon = button_icon("showcase") or "🏅"
    await send_card(inter, embed(f"{icon} Витрина профиля", "\n".join(lines)), "showcase", rows=rows)


@bot.tree.command(name="витрина", description="Выбрать значки для своего профиля")
@app_commands.guild_only()
async def showcase_cmd(inter: discord.Interaction):
    await show(inter)
