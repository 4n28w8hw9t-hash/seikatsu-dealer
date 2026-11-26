"""Топ двора (текстом): две вкладки — по уровню и по монетам. У каждой свой персонаж-баннер
(banners/top_lvl, banners/top_coin; пока их нет — общий баннер «top»)."""
import discord

from .core import _B, _G, RED, E, bot, btn, button_icon, send_card
from .levels import get_path, is_female, level_of, rank_of
from .season import month_window, ranked as season_ranked

TOP_N = 10
TABS = {   # вкладка: (столбец, баннер, заголовок, подпись)
    "lvl": ("xp", "top_lvl", "Летопись славы", "Самые опытные при дворе"),
    "coin": ("balance", "top_coin", "Казна домов", "Богатейшие дома двора"),
    "season": (None, "top_lvl", "Топ за месяц", "Медали для трёх лидеров по итогам месяца"),
}


async def _ranked(guild: discord.Guild, col: str) -> list[tuple[int, int]]:
    """Все, кто сейчас на сервере (без ботов), по убыванию: [(user_id, значение)]."""
    cur = await bot.db.execute(
        f"SELECT user_id, {col} FROM users WHERE guild_id=? AND {col}>0 ORDER BY {col} DESC",
        (guild.id,))
    out = []
    for uid, val in await cur.fetchall():
        m = guild.get_member(uid)
        if m and not m.bot:
            out.append((uid, val or 0))
    return out


async def show_top(inter: discord.Interaction, tab: str = "lvl"):
    """Топ текстом: баннер персонажа сверху, ниже десятка лучших и твоё место."""
    tab = tab if tab in TABS else "lvl"
    col, banner, title, sub = TABS[tab]
    g = inter.guild
    if tab == "season":
        month, ends = month_window()
        ranked = await season_ranked(g, month)
        sub += f" · итоги <t:{ends}:R>"
    else:
        ranked = await _ranked(g, col)
    medals = [E("sd_top_1", "🥇"), E("sd_top_2", "🥈"), E("sd_top_3", "🥉")]
    lines = []
    for i, (uid, val) in enumerate(ranked[:TOP_N], 1):
        mark = medals[i - 1] if i <= 3 else f"`{i:>2}.`"
        if tab == "lvl":
            lvl = level_of(val)
            rank = rank_of(lvl, await get_path(g.id, uid), is_female(g.get_member(uid)))
            lines.append(f"{mark} <@{uid}> — **{lvl}** ур." + (f" · {rank}" if rank else ""))
        elif tab == "season":
            lines.append(f"{mark} <@{uid}> — **{_n(val)}** опыта")
        else:
            lines.append(f"{mark} <@{uid}> — **{_n(val)}** {E('sd_coin', '🪙')}")
    if not lines:
        lines = ["Пока пусто — двор только собирается"]

    me = inter.user.id
    place = next((i for i, (uid, _) in enumerate(ranked, 1) if uid == me), None)
    if not place:
        mine = "Тебя пока нет в списке"
    elif place == 1:
        mine = f"Ты — **#1** из {len(ranked)}. Держи корону"
    else:
        gap = ranked[place - 2][1] - ranked[place - 1][1] + 1
        unit = "монет" if tab == "coin" else "опыта"
        mine = f"Ты — **#{place}** из {len(ranked)} · до #{place - 1}: **+{_n(gap)}** {unit}"

    icon = E(f"sd_top_{tab}", "⭐" if tab == "lvl" else "💰")
    if tab == "season":
        icon = button_icon("season_top") or "🏅"
    e = discord.Embed(title=f"{icon} {title}", color=RED,
                      description=f"-# {sub}\n\n" + "\n".join(lines) + f"\n\n{mine}")
    rows = [[btn(f"top:{kind}", style=_B if tab == kind else _G) for kind in TABS]]
    key = banner if banner in getattr(bot, "banners", {}) else "top"
    await send_card(inter, e, key, rows=rows)


def _n(v: int) -> str:
    return f"{v:,}".replace(",", " ")


@bot.tree.command(name="топ", description="Лучшие при дворе: по уровню и по монетам")
async def top_cmd(inter: discord.Interaction):
    await show_top(inter, "lvl")
