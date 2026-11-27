"""Панели осады, дуэлей и зимней лавки."""

import asyncio
import time
from functools import lru_cache

import discord
from PIL import Image, ImageDraw

import art

from . import snowballs as s
from . import winter_state as w
from . import winter_guests as guests
from .core import _B, BUTTONS, bot, btn, button_emoji, reply
from .winter_snow import BANNER_HEIGHT, BANNER_WIDTH, snowfall, winter_px

KIND_LABELS = {"frame":"Рамка аватара","skin":"Фон карточки профиля","pair":"Комплект колец для пары"}

TARGET_ICONS = (
    ("wb_shield",) * 3,
    ("wb_wolf_track",) * 3,
    ("wb_bell_copper", "wb_bell_silver", "wb_bell_gold"),
    ("wb_ice_mirror",) * 3,
)

NAMES = {
    "journal": ("Журнал Следопыта", "wolf_track"),
    "clue": ("Осмотреть улику", "wolf_track"),
    "workshop": ("К ювелиру", "moon_brooch"),
    "brooch": ("Забрать брошь", "moon_brooch"),
    "engrave": ("Нанести гравировку", "rings"),
    "siege": ("На осаду", "shield"),
    "pack": ("Слепить снежки", "basket"),
    "duels": ("Вызвать друга", "snowball"),
    "invite": ("Выбрать соперника", "snowball"),
    "accept": ("Принять вызов", "shield"),
    "cancel": ("Закрыть дуэль", "raid"),
    "move": ("Сделать ход", "snowball"),
    "relay": ("Прикрой меня", "rings"),
    "step": ("Мой ход", "shield"),
    "princess": ("Дар Принцессы", "santa"),
    "unwrap": ("Распаковать", "santa"),
    "store": ("Лавка бала", "flake"),
    "choose": ("Витрина лавки", "card"),
}
for key, (name, price, kind) in s.SHOP.items():
    icon = key
    for prefix, label in (("item", name), ("try", "Примерить"), ("pay", "Купить"), ("wear", "Надеть")):
        NAMES[prefix + key] = (label, icon)
for i in range(3):
    NAMES["aim" + str(i)] = ("Бросить снежок", "snowball")
for key, (label, icon) in NAMES.items():
    BUTTONS["wb:" + key] = (label, "❄️", "wb_" + icon, _B)


def button(key, label=None, token="", *, icon=None):
    b = btn("wb:" + key, label)
    if icon:
        b.emoji = button_emoji(icon, "❄️")
    if token:
        b.custom_id += "@" + token
    return b


@lru_cache(maxsize=6)
def battlefield(idx, damage, goal, used, last, marks):
    from .winter import ART

    im = Image.new("RGB", (BANNER_WIDTH, winter_px(478)), "#101b30")
    with Image.open(ART / ("victory.jpg" if idx == 3 and damage >= goal else f"boss{idx}.jpg")) as bg:
        im.paste(bg, (0, 0))
    with Image.open(ART / "courtyard.jpg") as yard:
        im.paste(yard.resize((BANNER_WIDTH, winter_px(94)), Image.Resampling.LANCZOS), (0, BANNER_HEIGHT))
    d = ImageDraw.Draw(im)
    for i, label in enumerate(s.TARGETS[idx]):
        x = 20 + 324 * i
        d.rounded_rectangle(
            winter_px(x, 331, x + 310, 407), winter_px(10), fill="#243950", outline="#a7cade" if i == last else "#52697f", width=winter_px(2)
        )
        icon = art._icon(TARGET_ICONS[idx][i], winter_px(48))
        im.paste(icon, winter_px(x + 10, 344), icon)
        d.text(winter_px(x + 62, 367), label, font=art._pfont("sc6", winter_px(26)), anchor="lm", fill="#eef3f3")
        if i == last:
            for dx, dy, r in [(0, 0, 9), (-12, -8, 3), (9, -11, 4), (13, 6, 2)]:
                d.ellipse(winter_px(x + 277 + dx - r, 365 + dy - r, x + 277 + dx + r, 365 + dy + r), fill="#f1f8ff")
        if idx == 3 and marks & (1 << i):
            d.line(winter_px(x + 20, 397, x + 285, 338), fill="#b7d6ed", width=winter_px(2))
    d.text(winter_px(22, 418), f"Урон двора  {min(damage, goal)} / {goal}", font=art._pfont("sc6", winter_px(25)), fill="#cee2ee")
    d.text(
        winter_px(977, 418),
        f"Снежки  {max(0, 5 - used) if used >= 0 else 0} / 5",
        anchor="ra",
        font=art._pfont("sc6", winter_px(25)),
        fill="#cee2ee",
    )
    d.rounded_rectangle(winter_px(22, 455, 977, 464), winter_px(4), fill="#30455b")
    if damage:
        d.rounded_rectangle(winter_px(22, 455, 22 + round(955 * min(damage, goal) / goal), 464), winter_px(4), fill="#accfde")
    return snowfall(im)


def invite_view(ident, turn):
    view = discord.ui.View(timeout=None)
    view.add_item(button("accept", token=f"{ident}.{turn}"))
    view.stop()
    return view


async def preview(inter, key):
    from .economy import profile
    from .marriage import couple

    if key == "rings" and not await s.couple(bot.db, inter.guild_id, inter.user.id):
        return await reply(
            inter, "Примерка колец доступна в профиле пары после свадьбы.", rows=[["wb:itemrings"]], nav=False
        )
    inter.extras["snow_preview"] = key
    return await (couple if key == "rings" else profile).callback(inter, None)


async def show(inter, key, stamp="", *, send=None):
    from .winter import snow_banner

    send = send or reply
    g, u, day = inter.guild_id, inter.user.id, w.today()
    idx = w.stage(day)
    if key.startswith("try"):
        return await preview(inter, key[3:])
    vals = (getattr(inter, "data", None) or {}).get("values") or []
    value = str(vals[0]) if vals else ""
    notice = ""
    async with bot.transaction() as db:
        await w.act(db, g, u, "ball", day)
        if key == "pack":
            notice = await s.pack(db, g, u, day)
        elif key.startswith("aim"):
            notice = await s.throw(db, g, u, day, int(key[-1]), stamp)
        elif key == "unwrap":
            notice = await s.princess(db, g, u, day)
        elif key == "step":
            notice = await s.relay(db, g, u, day, stamp)
        elif key.startswith("pay"):
            if key == "payrings":
                current = await s.couple(db, g, u)
                price = 120 if await s.pair_step(db, g, current) >= 4 else 160
                expected = f"{u}.{current[0]}.{current[1]}.{current[2]}.{price}" if current else ""
                if stamp != expected:
                    notice = "Состав пары или цена изменились. Проверь комплект ещё раз."
                else:
                    notice = await s.purchase(db, g, u, key[3:], day)
            else:
                notice = await s.purchase(db, g, u, key[3:], day)
        elif key.startswith("wear"):
            notice = await s.equip(db, g, u, key[4:])
        elif key == "invite":
            resolved = (inter.data or {}).get("resolved", {}).get("users", {}).get(value, {})
            if value.isdecimal() and resolved and not resolved.get("bot"):
                notice = await s.invite(db, g, u, int(value), day)
            else:
                notice = "Выбери участника сервера."
        elif key in ("accept", "cancel", "move"):
            notice = await s.duel_move(
                db, g, u, key, stamp, int(value) if value in tuple(map(str, range(9))) else -1, day
            )
        balance = await w.first(db, "SELECT flakes FROM winter26_players WHERE g=? AND u=?", (g, u))
        owned = await s.inventory(db, g, u)
        mar = await s.couple(db, g, u)
        step = await s.pair_step(db, g, mar)
        used, last = await s.basket(db, g, u, day)
        totals, _ = await w.progress(db, g, u)
        goals = await w.targets(db, g)
        fort = await s.fort(db, g, idx) if idx is not None else (0, 0, 0, 0)
        match = await s.duel(db, g, u)
        recent = match or await s.duel(db, g, u, latest=True)
        rings = bool(
            mar
            and await w.first(
                db, "SELECT count(*)=2 FROM winter26_rings WHERE g=? AND u IN (?,?)", (g, *mar[:2])
            )
        )
        if key in ("journal", "clue"):
            story, chapter, choices = await guests.journal(db, g, u, day, stamp if key == "clue" else "")
        if key in ("workshop", "brooch", "engrave"):
            pair_rings = rings or (mar and await w.pair_days(db, g, *mar) >= 3)
            craft, craft_rows = await guests.workshop(db, g, u, key, mar, pair_rings, totals[3] >= goals[3])
    rows = []
    lines = []
    image = None
    if key in ("journal", "clue"):
        banner, lines = "tracker", story
        if choices:
            rows.append([button("clue", label, f"{u}.{chapter}.{i}") for i,label in enumerate(choices)])
        if idx == 1 and used < 5:
            direction = s.target(g, u, day, max(used, 0))
            lines.append(f"Следопыт подносит фонарь к снегу: пар идёт {s.DIRECTIONS[direction]}. Цель следующего броска — **{s.TARGETS[1][direction]}**.")
        rows.append(["wb:siege", "wb:workshop"])
    elif key in ("workshop", "brooch", "engrave"):
        banner, lines, rows = "jeweler", craft, craft_rows
        rows[0][0] = button("trylace", "Примерить рамку")
    elif key in ("siege", "pack") or key.startswith("aim"):
        banner = "siege"
        if idx is None:
            lines = ["Четыре осады · 15 декабря — 10 января. Новый противник каждую неделю."]
            rows = [["wb:archive"]]
        else:
            hits, previous, mirrors, volley = fort
            choice = s.target(g, u, day, max(0, used))
            clues = (
                "На щите проступила трещина",
                "Из снега поднимается тёплый пар",
                "На санях качнулся бубенец",
            )
            clue = (
                f"{clues[idx]} {s.DIRECTIONS[choice]}."
                if idx < 3
                else "Все зеркала разбиты! Бросайте в любую цель."
                if volley > time.time()
                else "Целься в целое зеркало. Остались: "
                + ", ".join(t for i, t in enumerate(s.TARGETS[3]) if not mirrors & (1 << i))
                + "."
            )
            if idx == 0 and hits and hits % 3 == 0 and previous != u:
                clue = "Другой игрок расколол щит. Ударь через брешь в любую точку!"
            lines = [clue, "Бросок приносит 5 снежинок, точный — ещё 3."]
            if idx == 2:
                lines.append("Три сбитых бубенца спасают подарок для всех участников главы.")
            if totals[idx] >= goals[idx]:
                lines.insert(0, "**Победа двора!** На площади продолжается праздничный дозор.")
            image = await asyncio.to_thread(battlefield, idx, totals[idx], goals[idx], used, last, mirrors)
            if used < 0:
                rows.append([button("pack")])
            elif used < 5:
                rows.append(
                    [
                        button("aim" + str(i), name, f"{day}.{u}.{used}", icon=TARGET_ICONS[idx][i])
                        for i, name in enumerate(s.TARGETS[idx])
                    ]
                )
            else:
                lines.append("Корзинка пуста. Новая порция снега — в полночь по Москве.")
        rows.append(["wb:journal"])
    elif key in ("duels", "invite", "cancel", "move", "accept"):
        banner = "snowduel"
        if idx is None:
            lines = ["Снежные дуэли откроются в дни бала."]
        elif match:
            ident, a, b, phase, turn, _ma, _mb, sa, sb, report = match
            token = f"{ident}.{turn}"
            lines = [f"<@{a}> против <@{b}> · **{sa} : {sb}**", report]
            if phase == "invite":
                lines.append(f"Только <@{b}> может принять приглашение.")
                rows.append([button("accept", token=token), button("cancel", token=token)])
            else:
                lines.append(f"Раунд {turn}/3. Выбери направление броска и своё укрытие одним тайным ходом.")
                opts = [
                    discord.SelectOption(
                        label=f"Бросок {s.DIRECTIONS[i // 3]} · укрытие {s.DIRECTIONS[i % 3]}", value=str(i)
                    )
                    for i in range(9)
                ]
                rows.append(
                    [
                        discord.ui.Select(
                            custom_id="sd:wb:move@" + token, placeholder="Бросить и спрятаться", options=opts
                        )
                    ]
                )
                rows.append([button("duels", "Проверить счёт"), button("cancel", token=token)])
        else:
            lines = [
                "Выбери соперника. У каждого три тайных броска и три укрытия. Дуэль играется своим запасом снега."
            ]
            if recent and recent[3] == "done":
                _, a, b, _, _, _, _, sa, sb, report = recent
                lines.append(
                    f"{report}\nИтог <@{a}> **{sa} : {sb}** <@{b}> · "
                    + ("ничья" if sa == sb else f"победил <@{a if sa > sb else b}>")
                )
            rows.append(
                [discord.ui.UserSelect(custom_id="sd:wb:invite", placeholder="Кого вызвать в снежки?")]
            )
    elif key in ("relay", "step"):
        banner = "pair"
        lines = [
            "Один отвлекает караул, второй бросает. Затем поменяйтесь ролями, чтобы снизить цену колец со 160 до 120 снежинок."
        ]
        if not mar:
            lines.append("Для совместного выхода нужна пара.")
        elif step == 4:
            lines.append("Скидка открыта для обоих супругов.")
        else:
            uid = mar[(0, 1, 1, 0)[step]]
            label = ("Выманить караул", "Бросить снежок", "Выманить караул", "Бросить снежок")[step]
            lines.append(f"Шаг {step + 1}/4 · ход <@{uid}>")
            if idx is not None:
                rows.append([button("step", label, f"{mar[2]}.{step}")])
        rows.append([button("itemrings")])
    elif key in ("princess", "unwrap"):
        banner = "princessgift"
        lines = [
            "Под ёлкой для каждого гостя лежат 250 монет, 25 снежинок и знак для витрины. Забери подарок с 1 по 10 января."
        ]
        if "princess" in owned:
            lines.append("Твой подарок распакован.")
        elif w.REVEAL <= day < w.END:
            rows.append([button("unwrap")])
    else:
        banner = "shop"
        item = value if key == "choose" else key.removeprefix("item").removeprefix("pay").removeprefix("wear")
        lines = [f"❄ Твои снежинки · **{balance}**"]
        if item in s.SHOP:
            name, price, kind = s.SHOP[item]
            if item == "rings" and step == 4:
                price = 120
            lines.append(f"**{KIND_LABELS[kind]} «{name}»** · {price} ❄")
            lines.append(
                {
                    "frame": "Рамка для твоего аватара.",
                    "skin": "Фон всего профиля с заснеженными воротами и фонарями.",
                    "pair": "Два кольца за одну покупку, по одному каждому супругу.",
                }[kind]
            )
            actions = [button("try" + item)]
            if rings if kind == "pair" else item in owned:
                lines.append("В коллекции.")
                if kind != "pair":
                    actions.append(button("wear" + item))
            elif idx is not None:
                actions.append(
                    button(
                        "pay" + item,
                        f"Купить за {price} ❄",
                        f"{u}.{mar[0]}.{mar[1]}.{mar[2]}.{price}" if item == "rings" and mar else "",
                    )
                )
            rows.extend([actions, [button("store")]])
        else:
            opts = []
            for code, (name, price, kind) in s.SHOP.items():
                price = 120 if code == "rings" and step == 4 else price
                opts.append(
                    discord.SelectOption(
                        label=name,
                        value=code,
                        description=f"{KIND_LABELS[kind]} · {price} снежинок",
                        emoji=button_emoji("wb_" + code, "❄️"),
                    )
                )
                lines.append(
                    f"**{KIND_LABELS[kind]}** «{name}» · {price} ❄"
                    + (" · получено" if code in owned or code == "rings" and rings else "")
                )
            rows.append(
                [discord.ui.Select(custom_id="sd:wb:choose", placeholder="Выбрать награду", options=opts)]
            )
            lines.append("**Фон карточки профиля** «Северная ночь» · 80 ❄")
            rows.append((["wb:buy"] if idx is not None else []) + ["wb:dress", "wb:workshop"])
    if key == "invite" and match and notice.startswith("<@"):
        _, a, b, _, turn, *_ = match
        try:
            await inter.channel.send(
                f"<@{b}>, <@{a}> зовёт тебя в снежки. Открой **/бал → Вызвать друга** или нажми кнопку ниже.",
                view=invite_view(match[0], turn),
                allowed_mentions=discord.AllowedMentions(
                    users=[discord.Object(id=b)], roles=False, everyone=False
                ),
            )
        except discord.HTTPException:
            notice += " Приглашение доступно сопернику через меню бала."
    if notice:
        lines.insert(0, notice)
    rows.append(["wb:ball", "menu"])
    await send(
        inter,
        embed=discord.Embed(description="\n".join(filter(None, lines)), color=0x9FBED9),
        image=("snow.gif", image or await asyncio.to_thread(snow_banner, banner)),
        rows=rows,
        nav=False,
        key=None,
        allowed_mentions=discord.AllowedMentions.none(),
    )
