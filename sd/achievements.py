"""Достижения: редкость, прогресс и награда монетами за открытие."""
import discord
from discord import app_commands

from .core import E, AFTER_ACTION, bot, embed, fmt, send_card
from .ledger import record as ledger_record
from .levels import level_of

# редкость: (название, значок, награда в монетах)
RARITY = {
    "common": ("Обычное", "⚪", 200),
    "rare": ("Редкое", "🔵", 500),
    "epic": ("Эпическое", "🟣", 1500),
    "legendary": ("Легендарное", "🟠", 5000),
}
# (ключ, название, условие, редкость, показатель, сколько нужно)
ACHIEVEMENTS = [
    ("first", "Первое слово", "написать первое сообщение", "common", "msgs", 1),
    ("work1", "Первая служба", "выйти на /работа", "common", "works", 1),
    ("voice10", "Голос двора", "10 часов в голосовых", "common", "voice", 600),
    ("lvl10", "Первая ступень", "достичь 10 уровня", "common", "level", 10),
    ("lucky", "Везунчик", "10 побед в монетке", "common", "flips", 10),
    ("duelist", "Дуэлянт", "первая победа в дуэли", "common", "duels", 1),
    ("chatter", "Болтун", "1 000 сообщений", "rare", "msgs", 1000),
    ("daily7", "Завсегдатай", "забирать награду 7 дней подряд", "rare", "streak", 7),
    ("rich", "Тугой кошелёк", "иметь 10 000 монет", "rare", "coins", 10000),
    ("married", "Узы", "вступить в брак", "rare", "married", 1),
    ("creator", "Творец", "создать свою роль", "rare", "created", 1),
    ("voice100", "Живёт в войсе", "100 часов в голосовых", "epic", "voice", 6000),
    ("lvl50", "Полпути к трону", "достичь 50 уровня", "epic", "level", 50),
    ("daily30", "Верный двору", "забирать награду 30 дней подряд", "epic", "streak", 30),
    ("champion", "Чемпион арены", "25 побед в дуэлях", "epic", "duels", 25),
    ("designer", "Модельер", "продать свои роли 10 раз", "epic", "sold", 10),
    ("lvl100", "Вершина", "достичь 100 уровня — Император или Святой", "legendary", "level", 100),
    ("treasurer", "Казначей", "иметь 100 000 монет", "legendary", "coins", 100000),
    ("trendsetter", "Законодатель моды", "одну твою роль купили 25 человек", "legendary", "best", 25),
    ("icon", "Икона стиля", "самая продаваемая роль на сервере (от 5 продаж)", "legendary", "top", 1),
]
BY_KEY = {a[0]: a for a in ACHIEVEMENTS}


async def get_stats(guild_id: int, user_id: int) -> dict:
    u = await bot.get_user(guild_id, user_id)
    cur = await bot.db.execute(
        "SELECT xp,msgs,voice_min,duel_wins,flip_wins,works,ach FROM users "
        "WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    xp, msgs, vmin, duels, flips, works, ach = await cur.fetchone()
    from .market import role_stats
    from .marriage import get_marriage
    mar = await get_marriage(guild_id, user_id)
    roles = await role_stats(guild_id, user_id)
    return {"xp": xp or 0, "level": level_of(xp or 0), "msgs": msgs or 0, "voice": vmin or 0,
            "duels": duels or 0, "flips": flips or 0, "works": works or 0,
            "coins": u["balance"], "streak": u["streak"], "married": int(mar is not None),
            "marriage": mar, "created": roles["created"], "sold": roles["sold"],
            "best": roles["best"], "top": int(roles["top"]),
            "ach": set(filter(None, (ach or "").split(",")))}


async def unlock(guild_id: int, user_id: int) -> list[str]:
    """Открывает заработанные достижения и выдаёт за них монеты. Возвращает новые."""
    s = await get_stats(guild_id, user_id)
    new = [k for k, _, _, _, stat, need in ACHIEVEMENTS if k not in s["ach"] and s[stat] >= need]
    if not new:
        return []
    async with bot.transaction() as db:
        async with db.execute("SELECT ach FROM users WHERE guild_id=? AND user_id=?",
                              (guild_id, user_id)) as cur:
            row = await cur.fetchone()
        if row is None:
            return []
        unlocked = set(filter(None, (row[0] or "").split(",")))
        new = [key for key in new if key not in unlocked]
        if not new:
            return []
        reward = sum(RARITY[BY_KEY[key][3]][2] for key in new)
        await db.execute(
            "UPDATE users SET ach=?, balance=balance+? WHERE guild_id=? AND user_id=?",
            (",".join(sorted(unlocked.union(new))), reward, guild_id, user_id))
        await ledger_record(db, guild_id, user_id, reward, "achievement",
                            ", ".join(BY_KEY[key][1] for key in new))
    return new


def unlocked_text(new: list[str]) -> str:
    lines = []
    for k in new:
        _, name, cond, rar, _, _ = BY_KEY[k]
        rname, icon, reward = RARITY[rar]
        lines.append(f"{E(f'sd_ach_{k}', icon)} **{name}** · {rname} — {cond}\n"
                     f"Награда: +**{fmt(reward)}**")
    return "\n\n".join(lines)


async def notify(inter: discord.Interaction):
    """После каждой команды и кнопки: проверить достижения игрока и сообщить о новых."""
    if not inter.guild_id or not inter.response.is_done():
        return
    new = await unlock(inter.guild_id, inter.user.id)
    if new:
        try:
            e = embed("🏅 Новое достижение" if len(new) == 1 else "🏅 Новые достижения",
                      unlocked_text(new), discord.Color.gold())
            await inter.followup.send(embed=e)
        except discord.HTTPException:
            pass

AFTER_ACTION.append(notify)


@bot.tree.command(name="достижения", description="Все достижения: что открыто, что нет, награды")
@app_commands.describe(участник="Чьи достижения посмотреть")
async def achievements(inter: discord.Interaction, участник: discord.Member | None = None):
    m = участник or inter.user
    await unlock(inter.guild_id, m.id)
    s = await get_stats(inter.guild_id, m.id)
    e = embed(f"Достижения {m.display_name} · {len(s['ach'] & set(BY_KEY))}/{len(ACHIEVEMENTS)}",
              "🏅 открыто · 🔒 закрыто · награда выдаётся сразу при открытии")
    for rar, (rname, icon, reward) in RARITY.items():
        lines = []
        for k, name, cond, r, stat, need in ACHIEVEMENTS:
            if r != rar:
                continue
            if k in s["ach"]:
                lines.append(f"{E(f'sd_ach_{k}', '🏅')} **{name}** — {cond}")
            else:
                have = min(s[stat], need)
                if stat == "voice":   # минуты показываем часами
                    have, need = have // 60, need // 60
                prog = f" ({have:,}/{need:,}{' ч' if stat == 'voice' else ''})".replace(",", " ") \
                    if need > 1 else ""
                lines.append(f"{E(f'sd_ach_{k}_off', '🔒')} {name} — {cond}{prog}")
        e.add_field(name=f"{icon} {rname} · +{reward:,} монет".replace(",", " "),
                    value="\n".join(lines), inline=False)
    await send_card(inter, e, "top", rows=[["profile"]])
