"""Браки: кольца, предложение, парный профиль, опыт пары, лав-рума, развод."""
import asyncio
import time
from uuid import uuid4

import discord
from discord import app_commands

import art
from .core import ECON_LOCK, E, bot, bot_channel, button_emoji, card_name, embed, fmt, member_name, reply, send_card, send_public
from .ledger import record as ledger_record
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
PENDING_ROOM_PREFIX = "seikatsu-pending-"
ROOM_EMPTY_GRACE = 120   # пустая рума удаляется через 2 минуты
ROOM_RENAME_PRICE = 1000  # своё название лав-румы
ROOM_NAME_MAX = 40
ANNIVERSARIES = (7, 30, 100)
room_empty_since: dict[int, float] = {}
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
async def get_marriage(guild_id: int, user_id: int, *, db=None) -> dict | None:
    db = bot.db if db is None else db
    cur = await db.execute(
        "SELECT a,b,since,ring,xp,room_id,room_created,room_name,bond_ring FROM marriages "
        "WHERE guild_id=? AND (a=? OR b=?)", (guild_id, user_id, user_id))
    r = await cur.fetchone()
    if not r:
        return None
    return dict(zip(["a", "b", "since", "ring", "xp", "room_id", "room_created", "room_name", "bond_ring"], r))


async def get_rings(guild_id: int, user_id: int) -> dict[str, int]:
    cur = await bot.db.execute(
        "SELECT ring,qty FROM rings WHERE guild_id=? AND user_id=? AND qty>0", (guild_id, user_id))
    return {k: q for k, q in await cur.fetchall()}


def collection_keys(mar, owned, partner_owned):
    return {key for key in RINGS if owned.get(key, 0) > 0 or partner_owned.get(key, 0) > 0
            or (mar and key == mar["bond_ring"])}


async def purchase_ring(guild_id: int, user_id: int, key: str) -> bool:
    price = RINGS[key][1]
    async with bot.transaction() as db:
        await bot.ensure_user(db, guild_id, user_id)
        cur = await db.execute(
            "UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=? AND balance>=?",
            (price, guild_id, user_id, price))
        if cur.rowcount != 1:
            return False
        await db.execute(
            "INSERT INTO rings(guild_id,user_id,ring,qty) VALUES(?,?,?,1) "
            "ON CONFLICT(guild_id,user_id,ring) DO UPDATE SET qty=qty+1",
            (guild_id, user_id, key))
        await ledger_record(db, guild_id, user_id, -price, "ring", RINGS[key][0])
    return True


def ring_action_select(current: str | None, couple_owned: set[str]) -> discord.ui.Select:
    options = []
    for key, (name, price, _) in RINGS.items():
        if key not in couple_owned and key != current:
            emoji = button_emoji("buy", "🛒")
            options.append(discord.SelectOption(
                label=f"Купить: {name}", value=f"buy:{key}",
                description=f"{price:,} монет".replace(",", " "), emoji=emoji))
    for key, (name, _, _) in RINGS.items():
        if key in couple_owned and key != current:
            emoji = discord.PartialEmoji.from_str(ring_emo(key))
            options.append(discord.SelectOption(
                label=f"Выбрать в профиле: {name}", value=f"wear:{key}",
                description="Показывать это кольцо в профиле пары", emoji=emoji))
    if not options:
        options.append(discord.SelectOption(label="Все кольца уже собраны", value="noop",
                                            description="Повторно покупать их нельзя"))
    return discord.ui.Select(custom_id="sd:ringbook:action", placeholder="Купить или выбрать кольцо",
                             min_values=1, max_values=1, options=options)


def gift_ring_select(available: dict[str, int]) -> discord.ui.Select:
    options = [discord.SelectOption(
        label=f"Подарить: {RINGS[key][0]}", value=f"gift:{key}",
        description="Передать кольцо партнёру", emoji=discord.PartialEmoji.from_str(ring_emo(key)))
        for key in available]
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
    couple_owned = collection_keys(mar, owned, partner_owned)
    card = [{"key": key, "name": name, "price": price,
             "owned": key in couple_owned,
             "current": key == current}
            for key, (name, price, _) in RINGS.items()]
    banner = getattr(bot, "banners", {}).get("marry") or getattr(bot, "banners", {}).get("help")
    try:
        png = await asyncio.to_thread(art.ring_collection_card, banner, card)
        return await reply(inter, note, image=("rings.png", png),
                           rows=[[ring_action_select(current, couple_owned)],
                                 ["ringgift", "couple", "rings"]],
                           key=None)
    except Exception as ex:
        print("Коллекция колец не нарисована:", repr(ex))
    lines = [f"{ring_emo(r['key'])} **{r['name']}** — "
             + ("надето" if r["current"] else "есть" if r["owned"] else "нет")
             for r in card]
    e = embed("Коллекция колец", (note + "\n\n" if note else "") + "\n".join(lines))
    return await reply(inter, embed=e,
                       rows=[[ring_action_select(current, couple_owned)],
                             ["ringgift", "couple", "rings"]], key=None)


async def choose_gift_ring(inter: discord.Interaction):
    mar = await get_marriage(inter.guild_id, inter.user.id)
    if not mar:
        return await reply(inter, "Подарить кольцо можно только своему супругу или супруге",
                           rows=[["couple"]], key=None)
    owned = await get_rings(inter.guild_id, inter.user.id)
    partner_owned = await get_rings(inter.guild_id, other_of(mar, inter.user.id))
    available = {key: qty for key, qty in owned.items()
                 if key in RINGS and qty > 0 and not partner_owned.get(key, 0) and key != mar["bond_ring"]}
    if not available:
        note = ("Все кольца, которые у тебя есть, уже представлены в коллекции пары."
                if any(qty > 0 for qty in owned.values())
                else "У тебя пока нет свободных колец. Купи не представленное в коллекции кольцо.")
        return await reply(inter, note, rows=[["ringbook", "rings"]], key=None)
    return await reply(inter, "Выбери кольцо для подарка:",
                       rows=[[gift_ring_select(available)]], key=None)


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
    shared = collection_keys(mar, owned, partner_owned)
    if verb == "buy":
        if key in shared:
            return await show_ring_collection(inter, mar, f"Кольцо «{name}» уже есть в коллекции пары.")
        if not await purchase_ring(g, uid, key):
            return await show_ring_collection(inter, mar, f"Для покупки нужно {fmt(price)}.")
        return await show_ring_collection(inter, mar, f"{ring_emo(key)} Куплено: **{name}**.")
    if verb == "gift":
        if owned.get(key, 0) <= 0:
            return await show_ring_collection(inter, mar, f"У тебя нет кольца «{name}», чтобы подарить его.")
        if partner_owned.get(key, 0) > 0 or mar["bond_ring"] == key:
            return await show_ring_collection(inter, mar, f"У партнёра уже есть кольцо «{name}».")
        async with bot.transaction() as db:
            cur = await db.execute("UPDATE rings SET qty=qty-1 WHERE guild_id=? AND user_id=? AND ring=? AND qty>0",
                                   (g, uid, key))
            gifted = cur.rowcount == 1
            if gifted:
                await db.execute(
                    "INSERT INTO rings(guild_id,user_id,ring,qty) VALUES(?,?,?,1) "
                    "ON CONFLICT(guild_id,user_id,ring) DO UPDATE SET qty=qty+1", (g, recipient, key))
        if not gifted:
            return await show_ring_collection(inter, mar, "Этого кольца больше нет в запасе.")
        target = await member_name(inter.guild, recipient)
        receiver_count = (await get_rings(g, recipient)).get(key, 0)
        return await show_ring_collection(
            inter, mar, f"{ring_emo(key)} Ты подарил(а) кольцо «{name}» участнику **{target}**. "
            f"Теперь у него/неё в запасе: **{receiver_count}**.")
    if key not in shared:
        return await show_ring_collection(inter, mar, f"Кольца «{name}» нет в коллекции пары.")
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
    shared = collection_keys(mar, owned, partner_owned)
    for k, (name, price, _) in RINGS.items():
        has = k in shared
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
    if key in collection_keys(mar, owned, partner_owned):
        return await reply(inter, f"Кольцо «{name}» уже есть в коллекции" +
                           (" пары" if mar else "") + ". Повторно купить его нельзя.",
                           rows=[["ringbook", "couple"]] if mar else [["rings", "couple"]])
    if not await purchase_ring(inter.guild_id, inter.user.id, key):
        return await reply(inter, f"Не хватает монет: {name} стоит **{fmt(price)}**",
                           rows=[["rings", "daily"]])
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
        self.accept.emoji = button_emoji("marry_accept", "💞")
        self.decline.emoji = button_emoji("marry_decline", "💔")

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

    @discord.ui.button(label="Согласиться", style=discord.ButtonStyle.success)
    async def accept(self, inter: discord.Interaction, button: discord.ui.Button):
        await inter.response.defer()
        async with ECON_LOCK:
            if self.done or self.is_finished():
                return await inter.followup.send("Предложение уже закрыто", ephemeral=True)
            self.done = True
            self.stop()
            g = inter.guild_id
            a, b = sorted((self.a.id, self.b.id))
            async with bot.transaction() as db:
                if await get_marriage(g, a, db=db) or await get_marriage(g, b, db=db):
                    error = "Предложение больше не действует: кто-то уже в браке."
                else:
                    cur = await db.execute(
                        "UPDATE rings SET qty=qty-1 WHERE guild_id=? AND user_id=? AND ring=? AND qty>0",
                        (g, self.a.id, self.ring))
                    error = "Предложение больше не действует: кольца уже нет." if cur.rowcount != 1 else None
                    if not error:
                        await db.execute(
                            "INSERT INTO marriages(guild_id,a,b,since,ring,bond_ring,xp) VALUES(?,?,?,?,?,?,0)",
                            (g, a, b, int(time.time()), self.ring, self.ring))
            if error:
                return await inter.edit_original_response(view=None, embed=self.card(error, discord.Color.dark_grey()))
            await set_couple_role(g, (a, b), True)
        name, _, _ = RINGS[self.ring]
        from .chronicle import clog
        clog(inter.guild, "Свадьба", f"Венчание: {self.a.display_name} и {self.b.display_name}",
             f"💍 Двор празднует! {self.a.mention} и {self.b.mention} скрепили союз кольцом «{name}».", "marry")
        emo = ring_emo(self.ring)
        await inter.edit_original_response(view=None, embed=self.card(
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
    days = anniversary_days(mar)
    milestone = latest_anniversary(days)
    ring_name = RING_SHORT.get(mar["ring"], "—")
    names = [await member_name(inter.guild, mar["a"]), await member_name(inter.guild, mar["b"])]
    data = {"names": names, "level": lvl, "anniversary": milestone, "have": mar["xp"] - xp_for(lvl),
            "need": xp_for(lvl + 1) - xp_for(lvl),
            "cells": [("Вместе", f"{days} дн."), ("Кольцо", ring_name),
                      ("С", time.strftime("%d.%m.%Y", time.gmtime(mar["since"] + 3 * 3600)))]}
    from .winter_state import pair_days
    data["moon_rings"] = await pair_days(bot.db,inter.guild_id,mar["a"],mar["b"],mar["since"]) >= 3
    from .winter_state import first
    data["moon_rings"] = data["moon_rings"] or await first(bot.db,"SELECT COUNT(*)=2 FROM winter26_rings WHERE g=? AND u IN (?,?)",(inter.guild_id,mar["a"],mar["b"]))
    data["engraved"] = await first(bot.db, "SELECT 1 FROM winter26_engraving WHERE g=? AND a=? AND b=? AND since=?",
                                  (inter.guild_id,mar["a"],mar["b"],mar["since"]))
    preview=inter.extras.get("snow_preview")=="rings"
    if preview: data["moon_rings"]=True
    avs = [await avatar_of(inter.guild, mar["a"]), await avatar_of(inter.guild, mar["b"])]
    mine = inter.user.id in (mar["a"], mar["b"])
    rows = [["loveroom", "pairquest"], ["ringbook", "anniversary", "roomname", "divorce"]] if mine else []
    if preview: rows=[["wb:itemrings","wb:store"]]
    banners = getattr(bot, "banners", {})
    try:
        png = await asyncio.to_thread(
            art.couple_card, banners.get("marry") or banners.get("help"), data, *avs)
        return await reply(inter, "Примерка · Кольца Зимней луны" if preview else None, image=("couple.png", png), rows=rows)
    except Exception as ex:
        print("Парная карточка не нарисована:", repr(ex))
    if data["moon_rings"]:
        data["cells"].append(("Памятные кольца", "Первая зимняя луна" if data["engraved"] else "Зимняя луна"))
    e = embed(f"💞 {names[0]} & {names[1]}", f"Уровень пары **{lvl}**")
    for n, v in data["cells"]:
        e.add_field(name=n, value=v)
    if milestone:
        e.add_field(name="🏅 Годовщина", value=f"{milestone} дней вместе")
    await reply(inter, embed=e, rows=rows)


def anniversary_days(mar):
    return max(0, (int(time.time()) - mar["since"]) // 86400)


def latest_anniversary(days):
    return max((milestone for milestone in ANNIVERSARIES if days >= milestone), default=None)


async def anniversary(inter: discord.Interaction, *, celebrate=False, milestone: int | None = None):
    g, uid = inter.guild_id, inter.user.id
    mar = await get_marriage(g, uid)
    if not mar:
        return await reply(inter, "Отметки за годовщины доступны участникам пары.", rows=[["couple"]])
    days = anniversary_days(mar)
    async with bot.db.execute(
        "SELECT days FROM anniversaries WHERE guild_id=? AND a=? AND b=? AND since=?",
        (g, mar["a"], mar["b"], mar["since"])
    ) as cur:
        published = {row[0] for row in await cur.fetchall()}

    note = ""
    available = [target for target in ANNIVERSARIES if days >= target and target not in published]
    if celebrate and milestone is None and available:
        milestone = available[-1]  # старая кнопка из уже отправленных сообщений
    if celebrate and milestone in available:
        channel = bot_channel(inter.guild) or inter.channel
        names = [await member_name(inter.guild, uid) for uid in (mar["a"], mar["b"])]
        card = embed("🏅 Годовщина пары",
                     f"**{discord.utils.escape_markdown(names[0])} и {discord.utils.escape_markdown(names[1])}** "
                     f"отмечают **{milestone} дней вместе**. Двор поздравляет вас!")
        try:
            await channel.send(embed=card, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            note = "Бот не смог отправить поздравление в Казну. Можно попробовать ещё раз."
        else:
            await bot.db.execute(
                "INSERT OR IGNORE INTO anniversaries(guild_id,a,b,since,days) VALUES(?,?,?,?,?)",
                (g, mar["a"], mar["b"], mar["since"], milestone))
            await bot.db.commit()
            published.add(milestone)
            available.remove(milestone)
            note = "Поздравление опубликовано в Казне."
    elif celebrate:
        if milestone in published:
            note = "Эту дату уже отпраздновали."
        elif milestone is not None or days < ANNIVERSARIES[0]:
            note = "Эта дата ещё не открылась."
        else:
            note = "Все достигнутые даты уже отпраздновали."

    lines = [f"{'🏅' if days >= target else '◇'} **{target} дней** · "
             + ("отпраздновали" if target in published else "открыто" if days >= target
                else f"осталось {target - days} дн.")
             for target in ANNIVERSARIES]
    text = "\n".join([f"Вы вместе **{days} дн.**", "", *lines, "", note]).strip()
    rows = [["couple"]]
    if available:
        rows.insert(0, [discord.ui.Select(
            custom_id="sd:anniversary:pick", placeholder="Какую годовщину отпраздновать?",
            options=[discord.SelectOption(label=f"{target} дней вместе", value=str(target),
                                           emoji=button_emoji("anniversary", "🏅"))
                     for target in available])])
    await send_card(inter, embed("🏅 Годовщины пары", text), "marry", rows=rows)


@bot.tree.command(name="годовщина", description="Посмотреть даты и отпраздновать годовщину пары")
@app_commands.guild_only()
async def anniversary_cmd(inter: discord.Interaction):
    await anniversary(inter)


# ═════════ Лав-рума ═════════
async def love_room(inter: discord.Interaction):
    g = inter.guild
    mar = await get_marriage(g.id, inter.user.id)
    if not mar:
        return await reply(inter, "Лав-рума есть только у пар", rows=[["rings"]])
    ch = g.get_channel(mar["room_id"]) if mar["room_id"] else None
    if ch is None and mar["room_id"]:
        try:
            ch = await g.fetch_channel(mar["room_id"])
        except discord.NotFound:
            pass
        except discord.HTTPException:
            return await reply(inter, "Discord не подтвердил состояние лав-румы. Попробуй позже.",
                               rows=[["couple"]])
    if isinstance(ch, discord.VoiceChannel):
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
        pending_name = PENDING_ROOM_PREFIX + uuid4().hex
        async with bot.transaction() as db:
            await db.execute("INSERT INTO pending_love_rooms(guild_id,name,created) VALUES(?,?,?)",
                             (g.id, pending_name, int(time.time())))
        ch = await g.create_voice_channel(pending_name, category=cat, overwrites=over, user_limit=2,
                                          reason="Лав-рума пары")
    except discord.Forbidden:
        return await reply(inter, "У бота нет права «Управлять каналами» — попроси админа его выдать")
    async with bot.transaction() as db:
        updated = await db.execute(
            "UPDATE marriages SET room_id=?, room_created=? WHERE guild_id=? AND a=? AND b=? AND since=? "
            "AND room_id IS ?",
            (ch.id, int(time.time()), g.id, mar["a"], mar["b"], mar["since"], mar["room_id"]))
        if updated.rowcount == 1:
            await db.execute("DELETE FROM pending_love_rooms WHERE guild_id=? AND name=?", (g.id, pending_name))
    if updated.rowcount != 1:
        return await reply(inter, "Пара или её рума изменились. Открой парный профиль ещё раз.",
                           rows=[["couple"]])
    await name_open_room(ch, g, mar)
    if not ch.voice_states:
        room_empty_since[ch.id] = time.monotonic()
    await reply(inter, embed=embed(
        "💞 Лав-рума открыта", f"Заходи: {ch.mention}\nРуму видят все, но зайти можете только вы двое.\n"
        f"Своё название — `/название_румы` ({fmt(ROOM_RENAME_PRICE)}).\n"
        "Когда рума опустеет, она сама закроется через пару минут."), rows=[["couple", "roomname"]],
        key="marry")


async def name_open_room(channel, guild, marriage):
    try:
        await channel.edit(name=await room_title(guild, marriage), reason="Название лав-румы")
    except discord.HTTPException as ex:
        print("Название лав-румы будет обновлено позже:", channel.id, repr(ex))


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
    async with bot.transaction() as db:
        await db.execute("UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=?",
                         (ROOM_RENAME_PRICE, g.id, inter.user.id))
        await db.execute("UPDATE marriages SET room_name=? WHERE guild_id=? AND a=?", (name, g.id, mar["a"]))
        await ledger_record(db, g.id, inter.user.id, -ROOM_RENAME_PRICE, "room_name",
                            discord.utils.escape_markdown(name))
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


@bot.listen("on_voice_state_update")
async def track_empty_love_room(member, before, after):
    if before.channel == after.channel:
        return
    category = member.guild.get_channel(ROOM_CATEGORY_ID)
    for ch in (before.channel, after.channel):
        if not isinstance(ch, discord.VoiceChannel) or ch.category != category or category is None:
            continue
        if ch.voice_states:
            room_empty_since.pop(ch.id, None)
        else:
            room_empty_since[ch.id] = time.monotonic()


async def clean_pending_rooms():
    async with ECON_LOCK:
        async with bot.db.execute("SELECT guild_id,name FROM pending_love_rooms WHERE created<=?",
                                  (int(time.time()) - ROOM_EMPTY_GRACE,)) as cur:
            pending = await cur.fetchall()
        for guild_id in {guild_id for guild_id, _ in pending}:
            guild = bot.get_guild(guild_id)
            if guild is None or guild.unavailable:
                continue
            try:
                channels = {ch.name: ch for ch in await guild.fetch_channels()
                            if isinstance(ch, discord.VoiceChannel) and ch.category_id == ROOM_CATEGORY_ID}
            except discord.HTTPException as ex:
                print("Не удалось сверить временные лав-румы:", guild_id, repr(ex))
                continue
            for gid, name in pending:
                if gid != guild_id:
                    continue
                channel = channels.get(name)
                if channel:
                    cached = guild.get_channel(channel.id) or channel
                    if cached.voice_states:
                        continue
                    try:
                        await channel.delete(reason="Незавершённое создание лав-румы")
                    except discord.NotFound:
                        pass
                    except discord.HTTPException as ex:
                        print("Временная лав-рума ожидает удаления:", channel.id, repr(ex))
                        continue
                async with bot.transaction() as db:
                    await db.execute("DELETE FROM pending_love_rooms WHERE guild_id=? AND name=?", (gid, name))


async def clean_rooms():
    """Закрывает лав-руму после двух полных минут без участников."""
    cur = await bot.db.execute("SELECT guild_id,a,room_id FROM marriages WHERE room_id IS NOT NULL")
    rooms = await cur.fetchall()
    tracked = {room_id for _, _, room_id in rooms}
    for room_id in room_empty_since.keys() - tracked:
        room_empty_since.pop(room_id, None)
    now = time.monotonic()
    for gid, a, room_id in rooms:
        guild = bot.get_guild(gid)
        if guild is None or guild.unavailable:
            continue
        ch = guild.get_channel(room_id)
        if ch is None:
            try:
                ch = await guild.fetch_channel(room_id)
            except discord.NotFound:
                pass
            except discord.HTTPException:
                continue
        if isinstance(ch, discord.VoiceChannel):
            if ch.name.startswith(PENDING_ROOM_PREFIX):
                mar = await get_marriage(gid, a)
                if mar and mar["room_id"] == room_id:
                    await name_open_room(ch, guild, mar)
            if ch.voice_states:
                room_empty_since.pop(room_id, None)
                continue
            empty = room_empty_since.setdefault(room_id, now)
            if now - empty < ROOM_EMPTY_GRACE:
                continue
            try:
                await ch.delete(reason="Лав-рума пуста не менее двух минут")
            except discord.NotFound:
                pass
            except discord.HTTPException:
                continue
        room_empty_since.pop(room_id, None)
        await bot.db.execute(
            "UPDATE marriages SET room_id=NULL, room_created=NULL WHERE guild_id=? AND a=? AND room_id=?",
            (gid, a, room_id))
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
        "Опыт пары сбросится, обручальное кольцо пропадёт, лав-рума закроется."), rows=[["divorce:yes", "couple"]],
        key="marry")


async def divorce_confirm(inter: discord.Interaction):
    mar = await get_marriage(inter.guild_id, inter.user.id)
    if not mar:
        return await reply(inter, "Ты не в браке")
    await dissolve(inter.guild, mar)
    await reply(inter, embed=embed("💔 Брак расторгнут", "Каждый идёт своей дорогой."),
                rows=[["rings"]], key="marry")


async def delete_retired_room(guild: discord.Guild, room_id: int) -> bool:
    try:
        channel = guild.get_channel(room_id) or await guild.fetch_channel(room_id)
        if not isinstance(channel, discord.VoiceChannel):
            print("Удаление лав-румы отменено: другой тип канала", guild.id, room_id)
            return False
        await channel.delete(reason="Лав-рума после развода")
    except discord.NotFound:
        pass
    except discord.HTTPException:
        return False
    async with bot.transaction() as db:
        await db.execute("DELETE FROM room_cleanup WHERE guild_id=? AND room_id=?", (guild.id, room_id))
    room_empty_since.pop(room_id, None)
    return True


async def clean_retired_rooms():
    async with bot.db.execute("SELECT guild_id,room_id FROM room_cleanup") as cur:
        pending = await cur.fetchall()
    for guild_id, room_id in pending:
        guild = bot.get_guild(guild_id)
        if guild is None or guild.unavailable:
            continue
        try:
            await delete_retired_room(guild, room_id)
        except Exception as ex:
            print("Лав-рума ожидает удаления:", guild_id, room_id, repr(ex))


async def retire_marriage(db, guild_id, mar):
    if mar["room_id"]:
        await db.execute("INSERT OR IGNORE INTO room_cleanup(guild_id,room_id) VALUES(?,?)",
                         (guild_id, mar["room_id"]))
    await db.execute("DELETE FROM marriages WHERE guild_id=? AND a=? AND b=? AND since=?",
                     (guild_id, mar["a"], mar["b"], mar["since"]))


async def finish_dissolve(guild, mar):
    room_id = mar["room_id"]
    await set_couple_role(guild.id, (mar["a"], mar["b"]), False)
    if room_id and not await delete_retired_room(guild, room_id):
        print("Лав-рума поставлена в очередь удаления:", guild.id, room_id)


async def dissolve(guild: discord.Guild, mar: dict):
    async with bot.transaction() as db:
        await retire_marriage(db, guild.id, mar)
    await finish_dissolve(guild, mar)
