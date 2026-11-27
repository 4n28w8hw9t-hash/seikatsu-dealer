"""Меню и игровые страницы Бала зимней луны."""

import asyncio
from functools import lru_cache
from pathlib import Path

import discord
from PIL import Image, ImageDraw

import art

from . import snow_court, winter_state as w
from .core import _B, _G, _OK, BUTTONS, bot, btn, reply
from .winter_snow import snowfall

ART = Path(__file__).resolve().parents[1] / "winter_art"
ACTIONS = {
    "ball": ("Бал зимней луны", "🌙", "ball"),
    "raid": ("Битва недели", "⚔️", "raid"),
    "counter": ("Ответный ход", "🛡️", "raid"),
    "strike": ("В бой", "⚔️", "raid"),
    "santa": ("Тайный Санта", "🎁", "santa"),
    "offer": ("Положить подарок", "🎁", "santa"),
    "shop": ("Лавка", "❄️", "flake"),
    "buy": ("Северная ночь · 80 ❄", "❄️", "flake"),
    "game": ("Загадка дня", "🃏", "game"),
    "pair": ("Парное поручение", "💍", "rings"),
    "pairday": ("Выполнить свою часть", "💍", "rings"),
    "gifts": ("Мои награды", "🎖️", "crown"),
    "claim": ("Открыть сундук", "🎁", "santa"),
    "dress": ("Оформление", "🖼️", "card"),
    "hall": ("Лунный зал", "🌙", "card"),
    "night": ("Северная ночь", "🌌", "card"),
    "classic": ("Дворцовая", "🏰", "card"),
    "frost": ("Иней", "❄️", "frame"),
    "crown": ("Серебряный венец", "👑", "crown"),
    "bare": ("Снять рамку", "◯", "frame"),
    "archive": ("Летопись", "📜", "ball"),
}
for action, (label, emoji, icon) in ACTIONS.items():
    BUTTONS["wb:" + action] = (
        label,
        emoji,
        "wb_" + icon,
        _OK if action in ("strike", "offer", "claim") else _B,
    )
for i in range(3):
    BUTTONS[f"wb:answer{i}"] = ("Ответ", "❄️", "wb_game", _G)


@lru_cache(maxsize=12)
def snow_banner(key):
    with Image.open(ART / (key + ".jpg")) as image:
        return snowfall(image)


@lru_cache(maxsize=4)
def raid_card(idx, total, mine, goal):
    won = total >= goal
    path = ART / ("victory.jpg" if idx == 3 and won else f"boss{idx}.jpg")
    img = Image.new("RGB", (1000, 416), "#101b30")
    with Image.open(path) as banner:
        img.paste(banner, (0, 0))
    d = ImageDraw.Draw(img)
    label = "Победа двора" if won else "Урон двора"
    d.text((32, 328), f"{label} · {min(total, goal)} / {goal}", font=art._pfont("sc6", 28), fill="#d9e7f3")
    d.text((968, 328), f"Твои выходы · {mine}", font=art._pfont("sc6", 28), fill="#d9e7f3", anchor="ra")
    d.rounded_rectangle((32, 380, 968, 394), 7, fill="#26364d", outline="#8099ad")
    width = round(932 * min(total, goal) / goal)
    if width:
        d.rounded_rectangle((34, 382, 34 + width, 392), 5, fill="#a9d8e7")
    return snowfall(img)


PAGES = {
    "strike": "raid",
    "counter": "raid",
    "offer": "santa",
    "buy": "shop",
    "pairday": "pair",
    "claim": "gifts",
    **{k: "dress" for k in ("hall", "night", "classic", "frost", "crown", "bare")},
    **{f"answer{i}": "game" for i in range(3)},
}
PAIR_TASKS = (
    "Зажгите два фонаря на мосту.",
    "Разнесите приглашения в два крыла дворца.",
    "Украсьте ель двумя лунными звёздами.",
)
SKINS = {"": "Дворцовая", "hall": "Лунный зал", "night": "Северная ночь"}
SKINS["yard"]="Заснеженный двор"
FRAMES = {"lace":"Морозное кружево","aurora":"Северное сияние","": "без рамки", "frost": "Иней", "crown": "Серебряный венец"}


async def show(inter, key="ball"):
    day = w.today()
    idx = w.stage(day)
    g, u = inter.guild_id, inter.user.id
    if g is None:
        return await reply(inter, "Бал проходит на сервере.", nav=False, key=None)
    key, _, stamp = key.partition("@")
    if key in ("raid","strike","counter") and idx is not None:
        key = "siege"
    if key == "shop": key = "store"
    if key in snow_court.NAMES:
        return await snow_court.show(inter,key,stamp,send=reply)
    expired = key in ("strike", "counter", "answer0", "answer1", "answer2") and stamp != day.isoformat()
    if expired:
        key = PAGES[key]
    async with bot.transaction() as db:
        notice = await w.act(db, g, u, key, day)
        goals = await w.targets(db, g)
        totals, mine = await w.progress(db, g, u)
        flakes, skin, frame, night, chest = (
            await w.rows(
                db, "SELECT flakes,skin,frame,night,chest FROM winter26_players WHERE g=? AND u=?", (g, u)
            )
        )[0]
        gift = await w.rows(db, "SELECT recipient FROM winter26_gifts WHERE g=? AND u=?", (g, u))
        mar = await w.rows(db, "SELECT a,b,since FROM marriages WHERE guild_id=? AND (a=? OR b=?)", (g, u, u))
        pairdays = await w.pair_days(db, g, *mar[0]) if mar else 0
        played = await w.first(
            db, "SELECT 1 FROM winter26_games WHERE g=? AND u=? AND day=?", (g, u, str(day))
        )
    page = PAGES.get(key, key)
    banner = page
    lines, actions = [], []
    image = None
    if page == "ball":
        status = (
            "До открытия бала · 15 декабря"
            if day < w.START
            else "Бал завершён · награды доступны"
            if idx is None
            else f"Глава {idx + 1} · {w.BOSSES[idx]}"
        )
        lines = [
            f"**{status}**",
            "Каждую неделю двор сражается с новым боссом. Первый выход открывает рамку «Иней».",
            f"❄ Твои снежинки · **{flakes}**",
        ]
        if idx is not None:
            lines.append(
                f"⚔ Урон двора · **{min(totals[idx], goals[idx])}/{goals[idx]}** · Твои выходы · **{mine[idx]}**"
            )
        banner="siege"
        lines[1]="Слепи пять снежков и помоги двору отстоять крепость. Подсказка караула укажет, куда бросать."
        actions = [["wb:pack","wb:siege","wb:duels","wb:store"],["archive","game","santa","wb:relay"],["wb:princess","gifts","dress"]]
    elif page in ("raid", "archive"):
        if page == "raid" and idx is not None:
            image = await asyncio.to_thread(raid_card, idx, totals[idx], mine[idx], goals[idx])
            lines = [
                "Один выход в день · 20 снежинок. После победы можно присоединиться к дозору и получить знак этой главы."
            ]
            if totals[idx] >= goals[idx]:
                actions = [[btn("wb:strike", "В дозор"), "archive", "gifts"]]
            else:
                moves, signals = w.TACTICS[idx]
                lines.insert(0, f"**{signals[w.stance(day, idx)]}** Подходящий приём наносит ещё 5 урона.")
                actions = [[btn("wb:strike", moves[0]), btn("wb:counter", moves[1])], ["archive", "gifts"]]
        else:
            banner = "victory" if totals[3] >= goals[3] else "archive"
            for i, name in enumerate(w.BOSSES):
                status = (
                    "победа"
                    if totals[i] >= goals[i]
                    else (
                        "битва идёт"
                        if idx == i
                        else "впереди"
                        if day < w.START or idx is not None and i > idx
                        else "цель не достигнута"
                    )
                )
                lines.append(f"**{name}** · {w.DATES[i]} · {status} · {min(totals[i], goals[i])}/{goals[i]}")
            actions = [["gifts"]]
            if idx is not None:
                actions[0].insert(0, "raid")
    elif page == "santa":
        lines = [
            "До 1 января оставь под ёлкой **500 монет и 50 снежинок**. Каждый даритель получит такой же подарок от случайного другого участника. Если участник один, всё вернётся на его счёт.",
            f"Твои снежинки · **{flakes}**",
        ]
        if gift:
            receiver = gift[0][0]
            lines.append(
                "🎁 Подарок под ёлкой."
                if receiver is None
                else "🎁 Твой взнос вернулся на счёт."
                if receiver == u
                else "🎁 Обмен завершён. Монеты и снежинки зачислены."
            )
        if idx is not None and day < w.REVEAL and not gift:
            actions = [["offer"]]
    elif page == "game":
        if idx is None:
            lines = ["Дух Метели принимает гостей с 15 декабря по 10 января."]
        else:
            question, answers, _ = w.PUZZLES[(day - w.START).days % len(w.PUZZLES)]
            lines = [f"**{question}**", "За верный ответ — 20 снежинок, за попытку — 5."]
            if played:
                lines.append("Следующая загадка откроется в полночь по Москве.")
            else:
                actions = [[btn(f"wb:answer{i}", a) for i, a in enumerate(answers)]]
    elif page == "pair":
        lines = [
            "Каждый из супругов выполняет свою часть в один день. Три совместных дня открывают памятные кольца в карточке этой пары.",
            f"**Совместные дни · {min(pairdays, 3)}/3**",
        ]
        if idx is not None and mar and pairdays < 3:
            lines.append(PAIR_TASKS[(day - w.START).days % 3])
            actions = [["pairday"]]
        if pairdays >= 3:
            lines.append("💍 Кольца Зимней луны получены.")
        actions.append(["couple"])
    elif page == "shop":
        lines = [
            f"❄ Твои снежинки · **{flakes}**",
            "**Северная ночь · 80 снежинок**\nСеверное сияние за портретом персонажа и бирюзовые панели профиля.",
        ]
        if night:
            lines.append("Карточка в коллекции.")
        actions = [(["buy", "dress"] if idx is not None and not night else ["dress"])]
    elif page == "dress":
        banner = "shop"
        lines = [
            f"Карточка · **{SKINS[skin]}**   |   Рамка · **{FRAMES[frame]}**",
            "«Иней» — один выход. «Лунный зал» — участие в трёх разных главах. «Серебряный венец» — четыре личных знака победы.",
        ]
        actions = [["classic", "hall", "night", btn("wb:wearyard","Заснеженный двор")], ["bare", "frost", "crown", btn("wb:wearlace","Кружево"),btn("wb:wearaurora","Сияние")], ["profile", "shop"]]
    elif page == "gifts":
        lines = [f"❄ **{flakes}** · Глав с твоим участием **{sum(bool(n) for n in mine)}/4**"]
        for i, mark in enumerate(w.SIGILS):
            lines.append(("◆" if mine[i] and totals[i] >= goals[i] else "◇") + f" {mark} · {w.BOSSES[i]}")
        lines.append(
            "Финальный сундук · 1 000 монет каждому участнику битвы. Откроется после победы над Королевой или 11 января."
        )
        actions = [["dress", "showcase","wb:princess","pair"]]
        if not chest and any(mine) and (day >= w.END or totals[3] >= goals[3]):
            actions[0].append("claim")
        if chest:
            lines.append("Сундук получен.")
    if expired:
        notice = "Наступил новый день. Выбери действие на обновлённой странице."
    if notice:
        lines.insert(0, f"**{notice}**")
    actions.append(["menu"] if page == "ball" else ["ball", "menu"])
    rows = [
        [("wb:" + item if isinstance(item, str) and item in ACTIONS else item) for item in row]
        for row in actions
    ]
    for row in rows:
        for item in row:
            if isinstance(item, discord.ui.Button) and item.custom_id in {
                "sd:wb:strike",
                "sd:wb:counter",
                "sd:wb:answer0",
                "sd:wb:answer1",
                "sd:wb:answer2",
            }:
                item.custom_id += "@" + day.isoformat()
    await reply(
        inter,
        embed=discord.Embed(description="\n".join(lines), color=0x9FBED9),
        image=("winter.gif", image or await asyncio.to_thread(snow_banner, banner)),
        rows=rows,
        nav=False,
        key=None,
    )


@bot.tree.command(name="бал", description="Бал зимней луны — битвы, подарки и оформление")
@discord.app_commands.guild_only()
async def ball(inter: discord.Interaction):
    await show(inter)
