"""Браки: кольца, предложение, парный профиль, опыт пары, лав-рума, развод."""
import asyncio
import time

import discord
from discord import app_commands

import art
from .core import E, bot, card_name, embed, fmt, member_name, reply, send_card, send_public
from .levels import level_of, xp_for

# кольцо: (название, цена, эмодзи). Предложение делается лучшим из купленных колец.
RINGS = {
    "silver": ("Серебряное кольцо", 300, "💍"),
    "gold": ("Золотое кольцо", 1500, "💛"),
    "ruby": ("Кольцо с рубином", 5000, "❤️"),
}


def ring_emo(key: str) -> str:
    """Своя иконка кольца (ring_silver / ring_gold / ring_ruby), иначе эмодзи."""
    return E(f"sd_ring_{key}", RINGS[key][2])


RING_SHORT = {"silver": "Серебро", "gold": "Золото", "ruby": "Рубин"}
ROOM_CATEGORY_ID = 1575480244687609926
ROOM_EMPTY_GRACE = 120   # пустая рума удаляется через 2 минуты
ROOM_RENAME_PRICE = 1000  # своё название лав-румы
ROOM_NAME_MAX = 40
COUPLE_ROLE_ID = 1574169992038064318   # роль, которую получают все, у кого есть пара


async def set_couple_role(guild_id: int, user_ids, give: bool):
    """Выдаёт или снимает роль пары (без кэша участников)."""
    for uid in user_ids:
        try:
            if give:
                await bot.http.add_role(guild_id, uid, COUPLE_ROLE_ID, reason="Пара")
            else:
                await bot.http.remove_role(guild_id, uid, COUPLE_ROLE_ID, reason="Развод")
        except discord.HTTPException as ex:
            print("Роль пары не изменена:", uid, repr(ex))


@bot.listen("on_ready")
async def sync_couple_roles():
    """После запуска выдаёт роль пары всем, кто уже в браке."""
    try:
        cur = await bot.db.execute("SELECT guild_id,a,b FROM marriages")
        for gid, a, b in await cur.fetchall():
            await set_couple_role(gid, (a, b), True)
    except Exception as ex:
        print("Роли пар не синхронизированы:", repr(ex))


# ═════════ Данные ═════════
async def get_marriage(guild_id: int, user_id: int) -> dict | None:
    cur = await bot.db.execute(
        "SELECT a,b,since,ring,xp,room_id,room_created,room_name FROM marriages "
        "WHERE guild_id=? AND (a=? OR b=?)", (guild_id, user_id, user_id))
    r = await cur.fetchone()
    if not r:
        return None
    return dict(zip(["a", "b", "since", "ring", "xp", "room_id", "room_created", "room_name"], r))


async def get_rings(guild_id: int, user_id: int) -> dict[str, int]:
    cur = await bot.db.execute(
        "SELECT ring,qty FROM rings WHERE guild_id=? AND user_id=? AND qty>0", (guild_id, user_id))
    return {k: q for k, q in await cur.fetchall()}


def ring_action_select(owned: dict[str, int], current: str | None,
                       couple_owned: set[str]) -> discord.ui.Select:
    options = []
    for key, (name, price, _) in RINGS.items():
        if key not in couple_owned and key != current:
            emoji = discord.PartialEmoji.from_str(ring_emo(key))
            options.append(discord.SelectOption(
                label=f"Купить: {name}", value=f"buy:{key}",
                description=f"{price:,} монет".replace(",", " "), emoji=emoji))
    for key, (name, _, _) in RINGS.items():
        if owned.get(key, 0) > 0 and key != current:
            emoji = discord.PartialEmoji.from_str(ring_emo(key))
            options.append(discord.SelectOption(
                label=f"Выбрать в профиле: {name}", value=f"wear:{key}",
                description="Показывать это кольцо в профиле пары", emoji=emoji))
    if not options:
        options.append(discord.SelectOption(label="Все кольца уже собраны", value="noop",
                                            description="Повторно покупать их нельзя"))
    return discord.ui.Select(custom_id="sd:ringbook:action", placeholder="Купить или выбрать кольцо",
                             min_values=1, max_values=1, options=options)


def gift_ring_select(owned: dict[str, int], partner_owned: dict[str, int],
                     current: str | None) -> discord.ui.Select:
    options = [discord.SelectOption(
        label=f"Подарить: {RINGS[key][0]}", value=f"gift:{key}",
        description="Передать кольцо партнёру", emoji=discord.PartialEmoji.from_str(ring_emo(key)))
        for key, qty in owned.items()
        if key in RINGS and qty > 0 and not partner_owned.get(key, 0) and key != current]
    return discord.ui.Select(custom_id="sd:ringbook:giftselect", placeholder="Какое кольцо подарить?",
                             min_values=1, max_values=1, options=options)


async def show_ring_collection(inter: discord.Interaction, mar: dict | None = None,
                               note: str | None = None):
    mar = mar or await get_marriage(inter.guild_id, inter.user.id)
    if not mar:
        return await reply(inter, "Коллекция доступна участникам пары", rows=[["rings"]])
    owned = await get_rings(inter.guild_id, inter.user.id)
    partner_owned = await get_rings(inter.guild_id, other_of(mar, inter.user.id))
    current = mar["ring"]
    couple_owned = {key for key in RINGS
                    if owned.get(key, 0) > 0 or partner_owned.get(key, 0) > 0 or key == current}
    card = [{"key": key, "name": name, "price": price,
             "qty": 0,
             "owned": key in couple_owned,
             "current": key == current}
            for key, (name, price, _) in RINGS.items()]
    banner = getattr(bot, "banners", {}).get("marry") or getattr(bot, "banners", {}).get("help")
    try:
        png = await asyncio.to_thread(art.ring_collection_card, banner, card)
        return await reply(inter, note, image=("rings.png", png),
                           rows=[[ring_action_select(owned, current, couple_owned)],
                                 ["ringgift", "couple", "rings"]],
                           key=None)
    except Exception as ex:
        print("Коллекция колец не нарисована:", repr(ex))
    lines = [f"{ring_emo(r['key'])} **{r['name']}** — "
             + ("надето" if r["current"] else f"есть: {r['qty']}" if r["owned"] else "нет")
             for r in card]
    e = embed("Коллекция колец", (note + "\n\n" if note else "") + "\n".join(lines))
    return await reply(inter, embed=e,
                       rows=[[ring_action_select(owned, current, couple_owned)],
                             ["ringgift", "couple", "rings"]], key=None)


async def choose_gift_ring(inter: discord.Interaction):
    mar = await get_marriage(inter.guild_id, inter.user.id)
    if not mar:
        return await reply(inter, "Подарить кольцо можно только своему супругу или супруге",
                           rows=[["couple"]], key=None)
    owned = await get_rings(inter.guild_id, inter.user.id)
    partner_owned = await get_rings(inter.guild_id, other_of(mar, inter.user.id))
    available = {key: qty for key, qty in owned.items()
                 if qty > 0 and not partner_owned.get(key, 0) and key != mar["ring"]}
    if not available:
        note = ("Все кольца, которые у тебя есть, уже представлены в коллекции пары."
                if any(qty > 0 for qty in owned.values())
                else "У тебя пока нет свободных колец. Купи не представленное в коллекции кольцо.")
        return await reply(inter, note, rows=[["ringbook", "rings"]], key=None)
    return await reply(inter, "Выбери кольцо для подарка:",
                       rows=[[gift_ring_select(available, partner_owned, mar["ring"])]], key=None)


async def ring_action(inter: discord.Interaction, action: str):
    verb, _, key = action.partition(":")
    if verb == "noop":
        return await show_ring_collection(inter, note="Все виды колец уже есть в коллекции пары.")
    if verb not in {"buy", "gift", "wear"} or key not in RINGS:
        return await reply(inter, "Не удалось определить действие с кольцом", key=None)
    g, uid = inter.guild_id, inter.user.id
    mar = await get_marriage(g, uid)
    if not mar:
        return await reply(inter, "Действия с коллекцией доступны только участникам пары",
                           rows=[["rings"]], key=None)
    name, price, _ = RINGS[key]
    owned = await get_rings(g, uid)
    recipient = other_of(mar, uid)
    partner_owned = await get_rings(g, recipient)
    if verb == "buy":
        if owned.get(key, 0) > 0 or partner_owned.get(key, 0) > 0 or mar["ring"] == key:
            return await show_ring_collection(inter, mar, f"Кольцо «{name}» уже есть в коллекции пары.")
        user = await bot.get_user(g, uid)
        if user["balance"] < price:
            return await show_ring_collection(
                inter, mar, f"Не хватает {fmt(price - user['balance'])} монет на {name}.")
        await bot.add(g, uid, -price)
        await bot.db.execute(
            "INSERT INTO rings(guild_id,user_id,ring,qty) VALUES(?,?,?,1) "
            "ON CONFLICT(guild_id,user_id,ring) DO UPDATE SET qty=qty+1", (g, uid, key))
        await bot.db.commit()
        return await show_ring_collection(inter, mar, f"{ring_emo(key)} Куплено: **{name}**.")
    if verb == "gift":
        if owned.get(key, 0) <= 0:
            return await show_ring_collection(inter, mar, f"У тебя нет кольца «{name}», чтобы подарить его.")
        if partner_owned.get(key, 0) > 0 or mar["ring"] == key:
            return await show_ring_collection(inter, mar, f"У партнёра уже есть кольцо «{name}».")
        await bot.db.execute("UPDATE rings SET qty=qty-1 WHERE guild_id=? AND user_id=? AND ring=? AND qty>0",
                             (g, uid, key))
        await bot.db.execute(
            "INSERT INTO rings(guild_id,user_id,ring,qty) VALUES(?,?,?,1) "
            "ON CONFLICT(guild_id,user_id,ring) DO UPDATE SET qty=qty+1", (g, recipient, key))
        await bot.db.commit()
        target = await member_name(inter.guild, recipient)
        receiver_count = (await get_rings(g, recipient)).get(key, 0)
        return await show_ring_collection(
            inter, mar, f"{ring_emo(key)} Ты подарил(а) кольцо «{name}» участнику **{target}**. "
            f"Теперь у него/неё в запасе: **{receiver_count}**.")
    if owned.get(key, 0) <= 0 and mar["ring"] != key:
        return await show_ring_collection(inter, mar, f"У тебя нет кольца «{name}», чтобы выбрать его.")
    await bot.db.execute("UPDATE marriages SET ring=? WHERE guild_id=? AND a=?", (key, g, mar["a"]))
    await bot.db.commit()
    mar["ring"] = key
    return await show_ring_collection(inter, mar, f"{ring_emo(key)} В профиле пары теперь отображается **{name}**.")


def best_ring(owned: dict[str, int]) -> str | None:
    keys = [k for k in RINGS if owned.get(k)]
    return max(keys, key=lambda k: RINGS[k][1]) if keys else None


def other_of(mar: dict, uid: int) -> int:
    return mar["b"] if mar["a"] == uid else mar["a"]


# ═════════ Кольца ═════════
@bot.tree.command(name="кольца", description="Лавка колец для предложения руки и сердца")
async def rings_shop(inter: discord.Interaction):
    owned = await get_rings(inter.guild_id, inter.user.id)
    mar = await get_marriage(inter.guild_id, inter.user.id)
    partner_owned = await get_rings(inter.guild_id, other_of(mar, inter.user.id)) if mar else {}
    available = []
    lines = []
    for k, (name, price, _) in RINGS.items():
        has = owned.get(k, 0) > 0 or partner_owned.get(k, 0) > 0 or (mar and mar["ring"] == k)
        lines.append(f"{ring_emo(k)} **{name}** — {fmt(price)}" +
                     (" · **есть в коллекции**" if has else ""))
        if not has:
            available.append(f"ring:{k}")
    e = embed("💍 Лавка колец", "\n".join(lines) +
              "\n\nКаждый вид кольца можно добавить в коллекцию один раз. "
              "Уже купленные или подаренные кольца повторно купить нельзя.\n"
              "Для предложения нужно любое кольцо из коллекции: `/брак @участник`.")
    await send_card(inter, e, "shop", rows=[available or ["couple"]])


async def buy_ring(inter: discord.Interaction, key: str):
    if key not in RINGS:
        return
    name, price, _ = RINGS[key]
    emo = ring_emo(key)
    mar = await get_marriage(inter.guild_id, inter.user.id)
    owned = await get_rings(inter.guild_id, inter.user.id)
    partner_owned = await get_rings(inter.guild_id, other_of(mar, inter.user.id)) if mar else {}
    if owned.get(key, 0) > 0 or partner_owned.get(key, 0) > 0 or (mar and mar["ring"] == key):
        return await reply(inter, f"Кольцо «{name}» уже есть в коллекции" +
                           (" пары" if mar else "") + ". Повторно купить его нельзя.",
                           rows=[["ringbook", "couple"]] if mar else [["rings", "couple"]])
    u = await bot.get_user(inter.guild_id, inter.user.id)
    if u["balance"] < price:
        return await reply(inter, f"Не хватает монет: {name} стоит **{fmt(price)}**",
                           rows=[["rings", "daily"]])
    await bot.add(inter.guild_id, inter.user.id, -price)
    await bot.db.execute(
        "INSERT INTO rings(guild_id,user_id,ring,qty) VALUES(?,?,?,1) "
        "ON CONFLICT(guild_id,user_id,ring) DO UPDATE SET qty=qty+1",
        (inter.guild_id, inter.user.id, key))
    await bot.db.commit()
    note = ("Кольцо добавлено в коллекцию пары. Его можно подарить или выбрать для профиля."
            if mar else "Теперь можно сделать предложение: `/брак @участник`.")
    e = embed(f"{emo} Куплено: {name}", f"Списано **{fmt(price)}**.\n{note}", discord.Color.green())
    await send_card(inter, e, "shop", rows=[["ringbook", "couple"]] if mar else [["rings", "couple"]])


# ═════════ Предложение ═════════
class MarryView(discord.ui.View):
    def __init__(self, a: discord.Member, b: discord.Member, ring: str):
        super().__init__(timeout=120)
        self.a, self.b, self.ring = a, b, ring
        self.message = None
        self.done = False

    def card(self, text: str, color=discord.Color.from_rgb(209, 53, 57)) -> discord.Embed:
        e = embed("💍 Предложение", text, color)
        if "marry" in getattr(bot, "banners", {}):
            e.set_image(url=f"attachment://{card_name(bot.banners['marry'])}")
        return e

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.b.id:
            await inter.response.send_message("Это предложение не тебе", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Согласиться", emoji="💞", style=discord.ButtonStyle.success)
    async def accept(self, inter: discord.Interaction, button: discord.ui.Button):
        if self.done:
            return
        self.done = True
        self.stop()
        g = inter.guild_id
        if await get_marriage(g, self.a.id) or await get_marriage(g, self.b.id):
            return await inter.response.edit_message(view=None, embed=self.card(
                "Предложение больше не действует: кто-то уже в браке.", discord.Color.dark_grey()))
        if not (await get_rings(g, self.a.id)).get(self.ring):
            return await inter.response.edit_message(view=None, embed=self.card(
                "Предложение больше не действует: кольца уже нет.", discord.Color.dark_grey()))
        await bot.db.execute("UPDATE rings SET qty=qty-1 WHERE guild_id=? AND user_id=? AND ring=?",
                             (g, self.a.id, self.ring))
        a, b = sorted((self.a.id, self.b.id))
        await bot.db.execute(
            "INSERT INTO marriages(guild_id,a,b,since,ring,xp) VALUES(?,?,?,?,?,0)",
            (g, a, b, int(time.time()), self.ring))
        await bot.db.commit()
        await set_couple_role(g, (a, b), True)
        name, _, _ = RINGS[self.ring]
        from .chronicle import clog
        clog(inter.guild, "Свадьба", f"Венчание: {self.a.display_name} и {self.b.display_name}",
             f"💍 Двор празднует! {self.a.mention} и {self.b.mention} скрепили союз кольцом «{name}».", "marry")
        emo = ring_emo(self.ring)
        await inter.response.edit_message(view=None, embed=self.card(
            f"{emo} {self.b.mention} говорит «да»!\n"
            f"{self.a.mention} и {self.b.mention} теперь пара. Кольцо: **{name}**.\n"
            "Парный профиль — `/пара`.", discord.Color.green()))

    @discord.ui.button(label="Отказать", style=discord.ButtonStyle.danger)
    async def decline(self, inter: discord.Interaction, button: discord.ui.Button):
        if self.done:
            return
        self.done = True
        self.stop()
        await inter.response.edit_message(view=None, embed=self.card(
            f"{self.b.mention} отказывает {self.a.mention}. Кольцо остаётся у тебя.",
            discord.Color.dark_grey()))

    async def on_timeout(self):
        if self.message and not self.done:
            try:
                await self.message.edit(view=None, embed=self.card(
                    f"{self.b.mention} не ответил(а) на предложение {self.a.mention}.",
                    discord.Color.dark_grey()))
            except discord.HTTPException:
                pass


@bot.tree.command(name="брак", description="Сделать предложение руки и сердца")
@app_commands.describe(участник="Кому делаешь предложение")
async def marry(inter: discord.Interaction, участник: discord.Member):
    g = inter.guild_id
    if участник.bot or участник.id == inter.user.id:
        return await reply(inter, "Так нельзя 🙃")
    if await get_marriage(g, inter.user.id):
        return await reply(inter, "Ты уже в браке", rows=[["couple"]])
    if await get_marriage(g, участник.id):
        return await reply(inter, f"{участник.display_name} уже в браке")
    ring = best_ring(await get_rings(g, inter.user.id))
    if not ring:
        return await reply(inter, "Для предложения нужно кольцо — купи его в лавке",
                           rows=[["rings"]])
    name, _, _ = RINGS[ring]
    emo = ring_emo(ring)
    view = MarryView(inter.user, участник, ring)
    view.message = await send_public(inter, view.card(
        f"{inter.user.mention} встаёт на одно колено перед {участник.mention}\n"
        f"и протягивает {emo} **{name}**.\n\nНа ответ есть 2 минуты."),
        "marry", view=view, content=участник.mention)


# ═════════ Парный профиль ═════════
async def avatar_of(guild: discord.Guild, uid: int) -> bytes | None:
    try:
        m = guild.get_member(uid) or await guild.fetch_member(uid)
        return await m.display_avatar.replace(size=128, format="png").read()
    except Exception:
        return None


@bot.tree.command(name="пара", description="Парный профиль")
@app_commands.describe(участник="Чью пару посмотреть")
async def couple(inter: discord.Interaction, участник: discord.Member | None = None):
    m = участник or inter.user
    mar = await get_marriage(inter.guild_id, m.id)
    if not mar:
        who = "Ты не в браке" if m.id == inter.user.id else f"{m.display_name} не в браке"
        return await reply(inter, embed=embed(
            "💔 Пары нет", f"{who}.\nКупи кольцо в лавке и сделай предложение: `/брак @участник`."),
            rows=[["rings"]], key="marry")
    lvl = level_of(mar["xp"])
    days = (int(time.time()) - mar["since"]) // 86400
    ring_name = RING_SHORT.get(mar["ring"], "Кольцо")
    names = [await member_name(inter.guild, mar["a"]), await member_name(inter.guild, mar["b"])]
    data = {"names": names, "level": lvl, "have": mar["xp"] - xp_for(lvl),
            "need": xp_for(lvl + 1) - xp_for(lvl),
            "cells": [("Вместе", f"{days} дн."), ("Кольцо", ring_name),
                      ("С", time.strftime("%d.%m.%Y", time.gmtime(mar["since"] + 3 * 3600)))]}
    avs = [await avatar_of(inter.guild, mar["a"]), await avatar_of(inter.guild, mar["b"])]
    mine = inter.user.id in (mar["a"], mar["b"])
    rows = [["loveroom"], ["ringbook", "roomname", "divorce"]] if mine else []
    banners = getattr(bot, "banners", {})
    try:
        png = await asyncio.to_thread(
            art.couple_card, banners.get("marry") or banners.get("help"), data, *avs)
        return await reply(inter, image=("couple.png", png), rows=rows)
    except Exception as ex:
        print("Парная карточка не нарисована:", repr(ex))
    e = embed(f"💞 {names[0]} & {names[1]}", f"Уровень пары **{lvl}**")
    for n, v in data["cells"]:
        e.add_field(name=n, value=v)
    await reply(inter, embed=e, rows=rows)


# ═════════ Лав-рума ═════════
async def love_room(inter: discord.Interaction):
    g = inter.guild
    mar = await get_marriage(g.id, inter.user.id)
    if not mar:
        return await reply(inter, "Лав-рума есть только у пар", rows=[["rings"]])
    ch = g.get_channel(mar["room_id"]) if mar["room_id"] else None
    if ch:
        return await reply(inter, f"💞 Ваша лав-рума уже открыта: {ch.mention}", rows=[["couple"]])
    me = g.me
    try:
        cat = g.get_channel(ROOM_CATEGORY_ID)
        if not isinstance(cat, discord.CategoryChannel):
            return await reply(
                inter,
                f"Не нашёл категорию лав-рум по ID `{ROOM_CATEGORY_ID}`. "
                "Проверь, что категория есть на этом сервере и бот её видит.",
                rows=[["couple"]],
            )
        lovers = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True,
                                             stream=True, use_voice_activation=True)
        # руму видят все (и кто в ней сидит), но зайти могут только двое
        over = {g.default_role: discord.PermissionOverwrite(view_channel=True, connect=False),
                me: discord.PermissionOverwrite(view_channel=True, connect=True,
                                                manage_channels=True, move_members=True),
                discord.Object(id=mar["a"]): lovers, discord.Object(id=mar["b"]): lovers}
        ch = await g.create_voice_channel(await room_title(g, mar), category=cat,
                                          overwrites=over, user_limit=2,
                                          reason="Лав-рума пары")
    except discord.Forbidden:
        return await reply(inter, "У бота нет права «Управлять каналами» — попроси админа его выдать")
    await bot.db.execute("UPDATE marriages SET room_id=?, room_created=? WHERE guild_id=? AND a=?",
                         (ch.id, int(time.time()), g.id, mar["a"]))
    await bot.db.commit()
    await reply(inter, embed=embed(
        "💞 Лав-рума открыта", f"Заходи: {ch.mention}\nРуму видят все, но зайти можете только вы двое.\n"
        f"Своё название — `/название_румы` ({fmt(ROOM_RENAME_PRICE)}).\n"
        "Когда рума опустеет, она сама закроется через пару минут."), rows=[["couple", "roomname"]],
        key="marry")


async def room_title(g: discord.Guild, mar: dict) -> str:
    if mar.get("room_name"):
        return f"💞 {mar['room_name']}"[:100]
    names = [await member_name(g, mar["a"]), await member_name(g, mar["b"])]
    return f"💞 {names[0]} & {names[1]}"[:100]


async def rename_room(inter: discord.Interaction, name: str):
    g = inter.guild
    mar = await get_marriage(g.id, inter.user.id)
    if not mar:
        return await reply(inter, "Название румы могут менять только пары", rows=[["rings"]])
    name = " ".join(name.split())[:ROOM_NAME_MAX]
    if not name:
        return await reply(inter, "Название не может быть пустым", rows=[["couple"]])
    u = await bot.get_user(g.id, inter.user.id)
    if u["balance"] < ROOM_RENAME_PRICE:
        return await reply(inter, f"Смена названия стоит **{fmt(ROOM_RENAME_PRICE)}**, "
                                  f"у тебя **{fmt(u['balance'])}**", rows=[["balance", "daily"]])
    await bot.add(g.id, inter.user.id, -ROOM_RENAME_PRICE)
    await bot.db.execute("UPDATE marriages SET room_name=? WHERE guild_id=? AND a=?",
                         (name, g.id, mar["a"]))
    await bot.db.commit()
    mar["room_name"] = name
    note = "Название поставится, когда вы откроете лав-руму."
    ch = g.get_channel(mar["room_id"]) if mar["room_id"] else None
    if ch:
        try:
            await asyncio.wait_for(ch.edit(name=await room_title(g, mar), reason="Новое название"), 10)
            note = f"Открытая рума уже переименована: {ch.mention}"
        except Exception:
            note = "Открытую руму Discord сейчас не дал переименовать — название встанет при следующем открытии."
    await reply(inter, embed=embed("🏷️ Название лав-румы", f"Теперь ваша рума — **{name}**.\n"
                                   f"Списано: {fmt(ROOM_RENAME_PRICE)}\n{note}"),
                rows=[["loveroom", "couple"]], key="marry")


@bot.tree.command(name="название_румы",
                  description=f"Своё название лав-румы — {ROOM_RENAME_PRICE} монет")
@app_commands.describe(название="Как будет называться ваша рума")
async def room_name_cmd(inter: discord.Interaction,
                        название: app_commands.Range[str, 1, ROOM_NAME_MAX]):
    await rename_room(inter, название)


async def clean_rooms():
    """Удаляет пустые лав-румы (вызывается раз в минуту)."""
    cur = await bot.db.execute(
        "SELECT guild_id,a,room_id,room_created FROM marriages WHERE room_id IS NOT NULL")
    now = int(time.time())
    for gid, a, room_id, created in await cur.fetchall():
        guild = bot.get_guild(gid)
        ch = guild.get_channel(room_id) if guild else None
        if ch and (ch.voice_states or now - (created or 0) < ROOM_EMPTY_GRACE):
            continue
        if ch:
            try:
                await ch.delete(reason="Лав-рума опустела")
            except discord.HTTPException:
                continue
        await bot.db.execute("UPDATE marriages SET room_id=NULL WHERE guild_id=? AND a=?", (gid, a))
    await bot.db.commit()


# ═════════ Развод ═════════
@bot.tree.command(name="развод", description="Расторгнуть брак")
async def divorce(inter: discord.Interaction):
    mar = await get_marriage(inter.guild_id, inter.user.id)
    if not mar:
        return await reply(inter, "Ты не в браке")
    name = await member_name(inter.guild, other_of(mar, inter.user.id))
    await reply(inter, embed=embed(
        "💔 Развод", f"Точно расторгнуть брак с **{name}**?\n"
        "Опыт пары и кольцо пропадут, лав-рума закроется."), rows=[["divorce:yes", "couple"]],
        key="marry")


async def divorce_confirm(inter: discord.Interaction):
    mar = await get_marriage(inter.guild_id, inter.user.id)
    if not mar:
        return await reply(inter, "Ты не в браке")
    await dissolve(inter.guild, mar)
    await reply(inter, embed=embed("💔 Брак расторгнут", "Каждый идёт своей дорогой."),
                rows=[["rings"]], key="marry")


async def dissolve(guild: discord.Guild, mar: dict):
    ch = guild.get_channel(mar["room_id"]) if mar.get("room_id") else None
    if ch:
        try:
            await ch.delete(reason="Развод")
        except discord.HTTPException:
            pass
    await bot.db.execute("DELETE FROM marriages WHERE guild_id=? AND a=?", (guild.id, mar["a"]))
    await bot.db.commit()
    await set_couple_role(guild.id, (mar["a"], mar["b"]), False)

