"""Рынок ролей: игроки создают свои роли, выставляют их на продажу и получают процент."""
import asyncio
import base64
import binascii
from dataclasses import dataclass, replace
import re
import time

import discord
from discord import app_commands

import art
from .core import ECON_LOCK, _B, _G, bot, btn, button_icon, icon_emoji, embed, fmt, member_name, reply, send_card

from .ledger import record as ledger_record, role_status

ROLE_CREATE_PRICE = 10_000   # создание роли
ROLE_LIMIT = 3               # сколько ролей может создать один человек
SELLER_SHARE = 0.9           # владельцу идёт 90% от продажи, 10% — комиссия двора
PRICE_MIN, PRICE_MAX = 100, 1_000_000
NAME_MAX = 32
MARKET_PAGE_SIZE = 10


# ═════════ Данные ═════════
FIELDS = ["id", "owner_id", "role_id", "name", "color", "price", "sold", "earned"]


async def get_role(guild_id: int, ref: int) -> dict | None:
    cur = await bot.db.execute(
        f"SELECT {','.join(FIELDS)} FROM custom_roles WHERE guild_id=? AND id=?", (guild_id, ref))
    r = await cur.fetchone()
    return dict(zip(FIELDS, r)) if r else None


async def owned_roles(guild_id: int, user_id: int) -> list[dict]:
    """Все роли игрока: созданные и купленные."""
    cur = await bot.db.execute(
        f"SELECT {','.join('c.' + f for f in FIELDS)}, o.worn FROM role_owners o "
        "JOIN custom_roles c ON c.id=o.role_ref WHERE o.guild_id=? AND o.user_id=? "
        "ORDER BY (c.owner_id=o.user_id) DESC, c.name", (guild_id, user_id))
    return [dict(zip(FIELDS + ["worn"], r)) for r in await cur.fetchall()]


async def role_stats(guild_id: int, user_id: int) -> dict:
    """Для достижений: сколько создал, сколько продал, лучшая роль, первое место на рынке."""
    cur = await bot.db.execute(
        "SELECT COUNT(*), COALESCE(SUM(sold),0), COALESCE(MAX(sold),0) FROM custom_roles "
        "WHERE guild_id=? AND owner_id=?", (guild_id, user_id))
    created, sold, best = await cur.fetchone()
    cur = await bot.db.execute(
        "SELECT owner_id, sold FROM custom_roles WHERE guild_id=? ORDER BY sold DESC LIMIT 1",
        (guild_id,))
    top = await cur.fetchone()
    return {"created": created, "sold": sold, "best": best,
            "top": bool(top and top[0] == user_id and top[1] >= 5)}


def color_of(r: dict) -> str:
    return f"#{r['color']:06X}"


async def forget_missing(guild: discord.Guild, r: dict) -> bool:
    """Если роль удалили в настройках Discord — убираем её и из бота."""
    if guild.get_role(r["role_id"]):
        return False
    try:
        await guild.fetch_role(r["role_id"])
    except discord.NotFound:
        async with bot.transaction() as db:
            await db.execute("DELETE FROM role_owners WHERE guild_id=? AND role_ref=?", (guild.id, r["id"]))
            await db.execute("DELETE FROM custom_roles WHERE guild_id=? AND id=?", (guild.id, r["id"]))
        return True
    except discord.HTTPException as ex:
        print("Не удалось сверить роль:", guild.id, r["role_id"], repr(ex))
    return False


NO_RIGHTS = ("Не получилось: боту нужно право «Управлять ролями», "
             "и его роль должна стоять выше ролей игроков")


# ═════════ Магазин ═════════
@bot.tree.command(name="магазин", description="Роли, которые игроки выставили на продажу")
async def market(inter: discord.Interaction):
    await show_market(inter)


MARKET_SORTS = {
    "p": ("Популярные", "sold DESC, price ASC, id ASC"),
    "c": ("Сначала дешевле", "price ASC, id ASC"),
    "h": ("Сначала дороже", "price DESC, id ASC"),
    "n": ("Сначала новые", "created DESC, id DESC"),
}


@dataclass(frozen=True)
class MarketView:
    sort: str = "p"
    page: int = 0
    query: str = ""

    def token(self):
        encoded = base64.urlsafe_b64encode(self.query.encode()).decode().rstrip("=")
        return f"{self.sort}.{self.page}.{encoded}"

    @classmethod
    def parse(cls, token):
        if not token:
            return cls()
        parts = token.split(".", 2)
        if len(parts) != 3 or parts[0] not in MARKET_SORTS or not re.fullmatch(r"[0-9]{1,9}", parts[1]):
            return cls()
        try:
            encoded = parts[2]
            if len(encoded) > 48 or not re.fullmatch(r"[A-Za-z0-9_-]*", encoded):
                return cls()
            query = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode().strip()
        except (UnicodeError, binascii.Error):
            return cls()
        return cls(parts[0], int(parts[1]), query)


def market_back(state):
    return discord.ui.Button(label="К списку", custom_id=f"sd:mk:list:{state.token()}", style=_G)


class MarketSearch(discord.ui.Modal, title="Поиск ролей"):
    query = discord.ui.TextInput(label="Название или часть названия", required=False, max_length=18)

    def __init__(self, state):
        super().__init__()
        self.state = state
        self.query.default = state.query

    async def on_submit(self, inter: discord.Interaction):
        query = self.query.value.strip()
        if len(query.encode()) > 36:
            return await inter.response.send_message("Сократи фразу для поиска.", ephemeral=True)
        from .menu import run_fn
        state = replace(self.state, query=query, page=0)
        await run_fn(inter, lambda i: show_market(i, state), "поиск ролей")


async def show_market(inter: discord.Interaction, state: MarketView | None = None):
    state = state or MarketView()
    params = [inter.guild_id]
    where = "guild_id=? AND price IS NOT NULL"
    if state.query:
        where += " AND instr(casefold(name),?)>0"
        params.append(state.query.casefold())
    async with bot.db.execute(f"SELECT COUNT(*) FROM custom_roles WHERE {where}", params) as cur:
        total = (await cur.fetchone())[0]
    pages = max(1, (total + MARKET_PAGE_SIZE - 1) // MARKET_PAGE_SIZE)
    page = max(0, min(state.page, pages - 1))
    state = replace(state, page=page)
    offset = page * MARKET_PAGE_SIZE
    _, order = MARKET_SORTS[state.sort]
    cur = await bot.db.execute(
        f"SELECT {','.join(FIELDS)} FROM custom_roles WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        (*params, MARKET_PAGE_SIZE, offset))
    rows = [dict(zip(FIELDS, r)) for r in await cur.fetchall()]
    lines = []
    for i, r in enumerate(rows, start=offset + 1):
        owner = await member_name(inter.guild, r["owner_id"])
        lines.append(f"**{i}.** <@&{r['role_id']}> — **{fmt(r['price'])}** · "
                     f"продаж: {r['sold']} · от {owner}")
    text = "\n".join(lines) if lines else ("По этому запросу ролей нет." if state.query
                                          else "Пока никто ничего не выставил.")
    if state.query:
        text = f"**Поиск:** {discord.utils.escape_markdown(state.query)}\n\n{text}"
    e = embed("🛒 Магазин ролей", text +
              f"\n\nСвою роль можно создать за **{fmt(ROLE_CREATE_PRICE)}**.\n"
              f"-# Найдено: {total} · Страница {page + 1} из {pages} · Продавцу {round(SELLER_SHARE * 100)}%")
    sort = discord.ui.Select(
        custom_id=f"sd:mk:sort:{state.token()}", placeholder="Сортировка",
        options=[discord.SelectOption(label=label, value=key, default=key == state.sort)
                 for key, (label, _) in MARKET_SORTS.items()])
    rows_ui = [[sort]]
    if rows:
        rows_ui.append([discord.ui.Select(
            custom_id=f"sd:mk:pick:{state.token()}", placeholder="Открой роль, чтобы посмотреть цвет",
            options=[discord.SelectOption(label=r["name"][:100], value=str(r["id"]),
                                          description=f"{r['price']} монет · продаж: {r['sold']}"[:100])
                     for r in rows])])
    search_icon = discord.PartialEmoji.from_str(button_icon("role_search") or "🔎")
    actions = [discord.ui.Button(label="Поиск", emoji=search_icon,
                                 custom_id=f"sd:mk:search:{state.token()}", style=_B)]
    if state.query:
        actions.append(discord.ui.Button(label="Сбросить поиск",
                         custom_id=f"sd:mk:list:{MarketView(sort=state.sort).token()}", style=_G))
    if pages > 1:
        for jump, label in ((-1,"Назад"), (1,"Дальше")):
            target = page + jump
            key = replace(state, page=target).token() if 0 <= target < pages else label
            actions.append(discord.ui.Button(label=label, custom_id=f"sd:mk:list:{key}",
                                            style=_G, disabled=not 0 <= target < pages))
    rows_ui.extend([actions, ["rolecreate", "roles"]])
    await send_card(inter, e, "shop", rows=rows_ui, allowed_mentions=discord.AllowedMentions.none())


async def show_for_sale(inter: discord.Interaction, ref: int, state: MarketView | None = None):
    state = state or MarketView()
    back = market_back(state)
    r = await get_role(inter.guild_id, ref)
    if not r or r["price"] is None or await forget_missing(inter.guild, r):
        return await reply(inter, "Эта роль уже не продаётся", rows=[[back]])
    owner = await member_name(inter.guild, r["owner_id"])
    e = embed(f"🎭 {r['name']}", f"Цвет: **{color_of(r)}**\nСоздатель: **{owner}**\n"
              f"Продаж: **{r['sold']}**\nЦена: **{fmt(r['price'])}**",
              discord.Colour(r["color"]))
    buy = discord.ui.Button(label=f"Купить за {r['price']}", emoji=icon_emoji("🛍️"),
                            style=discord.ButtonStyle.success, custom_id=f"sd:mk:buy:{ref}:{state.token()}")
    try:
        png = await asyncio.to_thread(art.role_swatch, r["name"], r["color"])
    except Exception as ex:
        print("Не нарисован образец роли:", repr(ex))
        return await send_card(inter, e, "shop", rows=[[buy, back]])
    await reply(inter, embed=e, image=("role-color.png", png), rows=[[buy, back]])


async def reserve_role_purchase(guild_id: int, user_id: int, role: dict) -> str:
    async with bot.transaction() as db:
        key = (guild_id, user_id, role["id"])
        async with db.execute(
            "SELECT 1 FROM pending_role_purchases WHERE guild_id=? AND user_id=? AND role_ref=?", key
        ) as cur:
            if await cur.fetchone():
                return "pending"
        async with db.execute(
            "SELECT 1 FROM role_owners WHERE guild_id=? AND user_id=? AND role_ref=?", key
        ) as cur:
            if await cur.fetchone():
                return "owned"
        await bot.ensure_user(db, guild_id, user_id)
        debit = await db.execute(
            "UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=? AND balance>=?",
            (role["price"], guild_id, user_id, role["price"]))
        if debit.rowcount != 1:
            return "insufficient"
        await db.execute(
            "INSERT INTO pending_role_purchases(guild_id,user_id,role_ref,role_id,price) VALUES(?,?,?,?,?)",
            (*key, role["role_id"], role["price"]))
        await ledger_record(db, guild_id, user_id, -role["price"], "role_buy",
                            discord.utils.escape_markdown(role["name"]), status="pending", role_ref=role["id"])
        return "reserved"


async def settle_role_purchase(guild_id: int, user_id: int, ref: int, *, granted: bool) -> str | None:
    """Завершает покупку или возвращает резерв. Повторный вызов ничего не начисляет."""
    key = (guild_id, user_id, ref)
    async with bot.transaction() as db:
        async with db.execute(
            "SELECT role_id,price FROM pending_role_purchases WHERE guild_id=? AND user_id=? AND role_ref=?",
            key
        ) as cur:
            pending = await cur.fetchone()
        if not pending:
            return None
        role_id, price = pending
        async with db.execute(
            "SELECT owner_id,name FROM custom_roles WHERE guild_id=? AND id=? AND role_id=?",
            (guild_id, ref, role_id)
        ) as cur:
            seller = await cur.fetchone()
        sold = False
        if granted and seller:
            row = await db.execute(
                "INSERT OR IGNORE INTO role_owners(guild_id,user_id,role_ref,worn) VALUES(?,?,?,1)", key)
            sold = row.rowcount == 1
        detail = discord.utils.escape_markdown(seller[1]) if seller else f"Роль №{ref}"
        if sold:
            owner_id = seller[0]
            share = int(price * SELLER_SHARE)
            await bot.ensure_user(db, guild_id, owner_id)
            await db.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?",
                             (share, guild_id, owner_id))
            await db.execute("UPDATE custom_roles SET sold=sold+1, earned=earned+? WHERE guild_id=? AND id=?",
                             (share, guild_id, ref))
            await role_status(db, guild_id, user_id, ref, "done")
            await ledger_record(db, guild_id, owner_id, share, "role_sell", detail)
        else:
            await bot.ensure_user(db, guild_id, user_id)
            await db.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?",
                             (price, guild_id, user_id))
            await role_status(db, guild_id, user_id, ref, "refunded")
            await ledger_record(db, guild_id, user_id, price, "role_refund", detail)
        await db.execute("DELETE FROM pending_role_purchases WHERE guild_id=? AND user_id=? AND role_ref=?", key)
        return "sold" if sold else "refunded"


async def recover_role_purchases():
    async with bot.db.execute("SELECT guild_id,user_id,role_ref,role_id FROM pending_role_purchases") as cur:
        purchases = await cur.fetchall()
    for guild_id, user_id, ref, role_id in purchases:
        guild = bot.get_guild(guild_id)
        if guild is None or guild.unavailable:
            continue
        try:
            async with ECON_LOCK:
                try:
                    member = await guild.fetch_member(user_id)
                    granted = any(role.id == role_id for role in member.roles)
                except discord.NotFound:
                    granted = False
                await settle_role_purchase(guild_id, user_id, ref, granted=granted)
        except Exception as ex:
            print("Покупка роли ожидает сверки:", guild_id, ref, repr(ex))


async def buy_role(inter: discord.Interaction, ref: int, state: MarketView | None = None):
    back = market_back(state or MarketView())
    g, uid = inter.guild_id, inter.user.id
    r = await get_role(g, ref)
    if not r or r["price"] is None or await forget_missing(inter.guild, r):
        return await reply(inter, "Эта роль уже не продаётся", rows=[[back]])
    state = await reserve_role_purchase(g, uid, r)
    pending_note = "Покупка ещё проверяется. Бот завершит её или вернёт монеты автоматически."
    if state == "owned":
        return await reply(inter, "Эта роль у тебя уже есть", rows=[["roles", back]])
    if state == "pending":
        return await reply(inter, pending_note, rows=[["inventory", back]])
    if state == "insufficient":
        return await reply(inter, f"Не хватает монет: нужно **{fmt(r['price'])}**",
                           rows=[["daily", back]])

    try:
        try:
            await inter.user.add_roles(discord.Object(id=r["role_id"]), reason="Покупка в магазине ролей")
        except (discord.Forbidden, discord.NotFound):
            await settle_role_purchase(g, uid, ref, granted=False)
            return await reply(inter, "Роль не выдана. Монеты возвращены.", rows=[[back]])
        state = await settle_role_purchase(g, uid, ref, granted=True)
    except Exception as ex:
        print("Не завершена покупка роли:", g, ref, repr(ex))
        return await reply(inter, pending_note, rows=[["inventory", back]])
    if state != "sold":
        return await reply(inter, "Покупка отменена. Монеты возвращены.", rows=[[back]])
    e = embed(f"🛍️ Куплено: {r['name']}", f"Списано **{fmt(r['price'])}**. Роль уже на тебе.\n"
              "Снять или надеть её можно в инвентаре.", discord.Colour(r["color"]))
    await send_card(inter, e, "shop", rows=[["inventory", back]])


# ═════════ Создание роли ═════════
def parse_color(raw: str) -> int | None:
    m = re.fullmatch(r"#?([0-9a-fA-F]{6})", raw.strip())
    return int(m.group(1), 16) if m else None


def role_spot(g: discord.Guild) -> int:
    """Позиция для ролей игроков: сразу над ролью бустера (и ниже всех ролей над ним)."""
    top = g.me.top_role.position - 1          # выше роли бота поставить нельзя
    booster = g.premium_subscriber_role
    if booster and booster.position < top:
        return booster.position + 1
    return max(1, top)


async def place_role(g: discord.Guild, role: discord.Role):
    try:
        await role.edit(position=role_spot(g))
    except discord.HTTPException as ex:
        print("Роль не передвинута:", role.name, repr(ex))


@bot.listen("on_ready")
async def fix_role_positions():
    """Старые роли игроков ставим на место: сразу над ролью бустера."""
    for g in bot.guilds:
        booster = g.premium_subscriber_role
        if not booster:
            continue
        try:
            cur = await bot.db.execute("SELECT role_id FROM custom_roles WHERE guild_id=?", (g.id,))
            ids = {r[0] for r in await cur.fetchall()}
            roles = sorted([g.get_role(i) for i in ids if g.get_role(i)], key=lambda r: r.position)
            for r in roles:
                if (r.position < booster.position or r.position > booster.position + len(roles)) \
                        and r < g.me.top_role:
                    await place_role(g, r)
                    booster = g.premium_subscriber_role
        except Exception as ex:
            print("Роли игроков не передвинуты:", repr(ex))


async def discard_new_role(role: discord.Role):
    try:
        await role.delete(reason="Отмена создания роли")
    except discord.NotFound:
        pass
    except discord.HTTPException as ex:
        print("Временную роль надо удалить:", role.id, repr(ex))


async def create_role(inter: discord.Interaction, name: str, color_raw: str):
    g = inter.guild
    uid = inter.user.id
    name = " ".join(name.split())[:NAME_MAX]
    color = parse_color(color_raw)
    if not name or "@" in name:
        return await reply(inter, "Название не подходит", rows=[["rolecreate"]])
    if color is None:
        return await reply(inter, "Цвет нужен в виде **#FF0000** (шестнадцатеричный код)",
                           rows=[["rolecreate"]])
    if any(r.name.lower() == name.lower() for r in g.roles):
        return await reply(inter, "Роль с таким названием уже есть на сервере", rows=[["rolecreate"]])
    cur = await bot.db.execute("SELECT COUNT(*) FROM custom_roles WHERE guild_id=? AND owner_id=?",
                               (g.id, uid))
    if (await cur.fetchone())[0] >= ROLE_LIMIT:
        return await reply(inter, f"Можно создать не больше **{ROLE_LIMIT}** ролей", rows=[["roles"]])
    u = await bot.get_user(g.id, uid)
    if u["balance"] < ROLE_CREATE_PRICE:
        return await reply(inter, f"Создание роли стоит **{fmt(ROLE_CREATE_PRICE)}**",
                           rows=[["daily", "market"]])
    try:
        role = await g.create_role(name=name, colour=discord.Colour(color),
                                   reason=f"Роль игрока {inter.user}")
    except discord.HTTPException:
        return await reply(inter, NO_RIGHTS)
    try:
        await inter.user.add_roles(role, reason="Создатель роли")
        async with bot.transaction() as db:
            debit = await db.execute(
                "UPDATE users SET balance=balance-? WHERE guild_id=? AND user_id=? AND balance>=?",
                (ROLE_CREATE_PRICE, g.id, uid, ROLE_CREATE_PRICE))
            if debit.rowcount == 1:
                cur = await db.execute(
                    "INSERT INTO custom_roles(guild_id,owner_id,role_id,name,color,price,created) "
                    "VALUES(?,?,?,?,?,NULL,?)", (g.id, uid, role.id, name, color, int(time.time())))
                await db.execute("INSERT INTO role_owners(guild_id,role_ref,user_id,worn) VALUES(?,?,?,1)",
                                 (g.id, cur.lastrowid, uid))
                await ledger_record(db, g.id, uid, -ROLE_CREATE_PRICE, "role_create",
                                    discord.utils.escape_markdown(name))
    except Exception as ex:
        print("Создание роли отменено:", g.id, role.id, repr(ex))
        await discard_new_role(role)
        return await reply(inter, "Роль не оформлена. Монеты не списаны.", rows=[["roles", "market"]])
    if debit.rowcount != 1:
        await discard_new_role(role)
        return await reply(inter, "Для создания роли не хватает монет.", rows=[["daily", "market"]])
    await place_role(g, role)
    e = embed(f"✨ Роль создана: {name}", f"Списано **{fmt(ROLE_CREATE_PRICE)}**. Роль уже на тебе.\n"
              "Чтобы продавать её, открой «Мои роли» и выбери её.", discord.Colour(color))
    await send_card(inter, e, "shop", rows=[["roles", "market"]])


@bot.tree.command(name="создать_роль", description=f"Создать свою роль за {ROLE_CREATE_PRICE} монет")
@app_commands.describe(название="Как будет называться роль", цвет="Цвет, например #C0392B")
async def create_role_cmd(inter: discord.Interaction, название: app_commands.Range[str, 1, NAME_MAX],
                          цвет: str):
    await create_role(inter, название, цвет)


class CreateRoleModal(discord.ui.Modal, title="Новая роль"):
    name = discord.ui.TextInput(label="Название", max_length=NAME_MAX)
    color = discord.ui.TextInput(label="Цвет (код)", placeholder="#C0392B", max_length=7)

    async def on_submit(self, inter: discord.Interaction):
        from .menu import run_fn
        await run_fn(inter, lambda i: create_role(i, self.name.value, self.color.value))


# ═════════ Мои роли ═════════
@bot.tree.command(name="роли", description="Твои роли: надеть, снять, выставить на продажу")
async def my_roles(inter: discord.Interaction):
    await inventory_roles(inter)


ROLE_FILTERS = {"all": "Все роли", "worn": "Надеты", "mine": "Мои", "bought": "Куплены"}
ROLE_PAGE_SIZE = 8


def inventory_page_button(filter_key, page, label, *, disabled):
    return discord.ui.Button(label=label, custom_id=f"sd:inv:roles:{filter_key}:{page}",
                             style=_G, disabled=disabled)


@bot.tree.command(name="инвентарь", description="Твои роли и кольца")
async def inventory(inter: discord.Interaction):
    await inventory_roles(inter)


async def inventory_roles(inter: discord.Interaction, filter_key="all", page=0):
    g, uid = inter.guild_id, inter.user.id
    roles = [r for r in await owned_roles(g, uid) if not await forget_missing(inter.guild, r)]
    worn_roles = sum(bool(r["worn"]) for r in roles)
    created = sum(r["owner_id"] == uid for r in roles)
    if filter_key == "worn":
        filtered = [r for r in roles if r["worn"]]
    elif filter_key == "mine":
        filtered = [r for r in roles if r["owner_id"] == uid]
    elif filter_key == "bought":
        filtered = [r for r in roles if r["owner_id"] != uid]
    else:
        filter_key, filtered = "all", roles
    total_pages = max(1, (len(filtered) + ROLE_PAGE_SIZE - 1) // ROLE_PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    visible = filtered[page * ROLE_PAGE_SIZE:(page + 1) * ROLE_PAGE_SIZE]

    lines = []
    for r in visible:
        tags = ["твоя" if r["owner_id"] == uid else "куплена", "надета" if r["worn"] else "снята"]
        if r["owner_id"] == uid:
            tags.append(f"в продаже за {r['price']}" if r["price"] is not None else "не продаётся")
            tags.append(f"продаж: {r['sold']}, заработано: {r['earned']}")
        lines.append(f"<@&{r['role_id']}> — " + " · ".join(tags))

    role_text = "\n".join(lines) if lines else "В этой вкладке пока нет ролей."
    desc = (f"**Всего ролей:** {len(roles)} · **Надето:** {worn_roles} · **Создано:** {created}/{ROLE_LIMIT}"
            f"\n\n{role_text}\n\n-# Страница {page + 1} из {total_pages}")
    filters = discord.ui.Select(
        custom_id="sd:inv:filter", placeholder="Показать роли",
        options=[discord.SelectOption(label=label, value=key, default=key == filter_key)
                 for key, label in ROLE_FILTERS.items()])
    rows = [[btn("inventory", "Роли"), btn("inv:rings", style=_G)], [filters]]
    if visible:
        rows.append([discord.ui.Select(
            custom_id=f"sd:mk:mine:{filter_key}:{page}", placeholder="Выбери роль",
            options=[discord.SelectOption(label=r["name"][:100], value=str(r["id"]),
                                          emoji=icon_emoji("⭐") if r["owner_id"] == uid else None)
                     for r in visible])])
    actions = []
    if total_pages > 1:
        actions = [inventory_page_button(filter_key, max(page - 1, 0), "◀", disabled=page == 0),
                   inventory_page_button(filter_key, page + 1, "▶", disabled=page + 1 == total_pages)]
    rows.append(actions + ["rolecreate", "market"])
    await send_card(inter, embed("🎒 Инвентарь · Роли", desc), "inv", rows=rows,
                    allowed_mentions=discord.AllowedMentions.none())


async def inventory_rings(inter: discord.Interaction):
    from .marriage import RINGS, collection_keys, get_marriage, get_rings, other_of, ring_emo

    g, uid = inter.guild_id, inter.user.id
    stock = await get_rings(g, uid)
    mar = await get_marriage(g, uid)
    rows = [[btn("inventory", "Роли", style=_G), btn("inv:rings")]]
    total = sum(stock.get(key, 0) for key in RINGS)
    if mar:
        partner_stock = await get_rings(g, other_of(mar, uid))
        shared = collection_keys(mar, stock, partner_stock)
        lines = []
        for key, (name, _, _) in RINGS.items():
            tags = []
            if key == mar["ring"]:
                tags.append("в профиле пары")
            if key == mar["bond_ring"]:
                tags.append("обручальное")
            if stock.get(key):
                tags.append(f"у тебя: {stock[key]}")
            if partner_stock.get(key):
                tags.append(f"у партнёра: {partner_stock[key]}")
            lines.append(f"{ring_emo(key)} **{name}** · " + (" · ".join(tags) if tags else "нет в коллекции"))
        text = f"**Коллекция пары:** {len(shared)}/{len(RINGS)}\n" + "\n".join(lines)
        text += f"\n\n**Личный запас:** {total}"
        rows.append(["ringbook", "rings"])
    else:
        lines = [f"{ring_emo(key)} **{name}** · {stock.get(key, 0)}"
                 for key, (name, _, _) in RINGS.items()]
        text = f"**Личный запас:** {total}\n" + "\n".join(lines)
        text += "\n\nКоллекция пары появится после свадьбы."
        rows.append(["rings"])
    await send_card(inter, embed("🎒 Инвентарь · Кольца", text), "inventory_rings", rows=rows)


def inventory_view(parts):
    if len(parts) == 2 and parts[0] in ROLE_FILTERS and re.fullmatch(r"[0-9]{1,9}", parts[1]):
        return parts[0], int(parts[1])
    return None


def inventory_back(state):
    if state is None:
        return "roles"
    return discord.ui.Button(label="К списку", custom_id=f"sd:inv:roles:{state[0]}:{state[1]}", style=_G)


async def show_mine(inter: discord.Interaction, ref: int, state=None):
    suffix = f":{state[0]}:{state[1]}" if state is not None else ""
    back = inventory_back(state)
    roles = {r["id"]: r for r in await owned_roles(inter.guild_id, inter.user.id)}
    r = roles.get(ref)
    if not r or await forget_missing(inter.guild, r):
        return await reply(inter, "Этой роли у тебя нет", rows=[[inventory_back(state)]])
    own = r["owner_id"] == inter.user.id
    info = [f"Цвет: **{color_of(r)}**", f"Сейчас: **{'надета' if r['worn'] else 'снята'}**"]
    btn = []
    btn.append(discord.ui.Button(label="Снять" if r["worn"] else "Надеть",
                                 emoji=icon_emoji("👕"), style=discord.ButtonStyle.secondary,
                                 custom_id=f"sd:mk:{'off' if r['worn'] else 'on'}:{ref}{suffix}"))
    if own:
        info.append(f"Продаж: **{r['sold']}** · заработано: **{fmt(r['earned'])}**")
        if r["price"] is None:
            info.append("В магазине: **нет**")
            btn.append(discord.ui.Button(label="Выставить на продажу", emoji=icon_emoji("🏷️"),
                                         style=discord.ButtonStyle.success,
                                         custom_id=f"sd:mk:sell:{ref}{suffix}"))
        else:
            info.append(f"В магазине за **{fmt(r['price'])}**")
            price_icon = discord.PartialEmoji.from_str(button_icon("role_price_change") or "🏷️")
            btn.append(discord.ui.Button(label="Изменить цену", emoji=price_icon,
                                         style=discord.ButtonStyle.primary,
                                         custom_id=f"sd:mk:sell:{ref}{suffix}"))
            btn.append(discord.ui.Button(label="Снять с продажи", emoji=icon_emoji("✖️"),
                                         style=discord.ButtonStyle.danger,
                                         custom_id=f"sd:mk:unsell:{ref}{suffix}"))
    e = embed(f"🎭 {r['name']}" + (" ⭐" if own else ""), "\n".join(info), discord.Colour(r["color"]))
    await send_card(inter, e, "inv", rows=[btn + [back, "inventory"]])


async def wear(inter: discord.Interaction, ref: int, on: bool, state=None):
    roles = {r["id"]: r for r in await owned_roles(inter.guild_id, inter.user.id)}
    r = roles.get(ref)
    if not r:
        return await reply(inter, "Этой роли у тебя нет", rows=[[inventory_back(state)]])
    try:
        obj = discord.Object(id=r["role_id"])
        if on:
            await inter.user.add_roles(obj, reason="Надел свою роль")
        else:
            await inter.user.remove_roles(obj, reason="Снял свою роль")
    except discord.HTTPException:
        return await reply(inter, NO_RIGHTS, rows=[[inventory_back(state)]])
    await bot.db.execute("UPDATE role_owners SET worn=? WHERE guild_id=? AND role_ref=? AND user_id=?",
                         (int(on), inter.guild_id, ref, inter.user.id))
    await bot.db.commit()
    await show_mine(inter, ref, state)


async def set_price(inter: discord.Interaction, ref: int, price: int | None, state=None):
    r = await get_role(inter.guild_id, ref)
    if not r or r["owner_id"] != inter.user.id:
        return await reply(inter, "Продавать можно только свою роль", rows=[[inventory_back(state)]])
    if price is not None and not PRICE_MIN <= price <= PRICE_MAX:
        return await reply(inter, f"Цена — от {PRICE_MIN} до {PRICE_MAX:,}".replace(",", " "),
                           rows=[[inventory_back(state)]])
    await bot.db.execute("UPDATE custom_roles SET price=? WHERE id=?", (price, ref))
    await bot.db.commit()
    await show_mine(inter, ref, state)


class PriceModal(discord.ui.Modal, title="Цена роли"):
    price = discord.ui.TextInput(label="Сколько монет", placeholder="например 2000", max_length=7)

    def __init__(self, ref: int, state=None):
        super().__init__()
        self.ref, self.state = ref, state

    async def on_submit(self, inter: discord.Interaction):
        raw = self.price.value.strip().replace(" ", "")
        if not raw.isdigit():
            return await inter.response.send_message("Нужно целое число", ephemeral=True)
        from .menu import run_fn
        await run_fn(inter, lambda i: set_price(i, self.ref, int(raw), self.state))


# ═════════ Кнопки и списки рынка (sd:mk:...) ═════════
def modal_for(key: str):
    """Окно ввода для кнопки, если оно нужно, иначе None."""
    if key == "rolecreate":
        return CreateRoleModal()
    parts = key.split(":")
    if len(parts) == 3 and parts[:2] == ["mk", "search"]:
        return MarketSearch(MarketView.parse(parts[2]))
    if len(parts) in (3, 5) and parts[:2] == ["mk", "sell"] and parts[2].isdecimal():
        return PriceModal(int(parts[2]), inventory_view(parts[3:]))
    return None


async def handle(inter: discord.Interaction, key: str):
    values = (inter.data or {}).get("values") or []
    parts = key.split(":")
    if len(parts) < 2:
        return
    _, act, *args = parts
    if act in ("pick", "mine"):
        if not values or not values[0].isdecimal():
            return
        ref = int(values[0])
        if act == "pick":
            return await show_for_sale(inter, ref, MarketView.parse(args[0] if args else ""))
        return await show_mine(inter, ref, inventory_view(args))
    if act in ("list", "sort") and len(args) == 1:
        state = MarketView.parse(args[0])
        if act == "sort" and values and values[0] in MARKET_SORTS:
            state = replace(state, sort=values[0], page=0)
        return await show_market(inter, state)
    if not args or not args[0].isdecimal():
        return
    ref = int(args[0])
    if act == "page":  # кнопки в старых сообщениях
        await show_market(inter, MarketView(page=ref))
    elif act == "buy":
        await buy_role(inter, ref, MarketView.parse(args[1] if len(args) > 1 else ""))
    elif act in ("on", "off"):
        await wear(inter, ref, act == "on", inventory_view(args[1:]))
    elif act == "unsell":
        await set_price(inter, ref, None, inventory_view(args[1:]))


async def delete_role(guild: discord.Guild, ref: int) -> bool:
    """Для админов: удалить роль игрока полностью."""
    r = await get_role(guild.id, ref)
    if not r:
        return False
    try:
        role = guild.get_role(r["role_id"])
        if role is None:
            role = await guild.fetch_role(r["role_id"])
        await role.delete(reason="Удалена админом")
    except discord.NotFound:
        pass
    except discord.HTTPException as ex:
        print("Удаление роли не подтверждено Discord:", guild.id, ref, repr(ex))
        return False
    async with bot.transaction() as db:
        await db.execute("DELETE FROM role_owners WHERE guild_id=? AND role_ref=?", (guild.id, ref))
        await db.execute("DELETE FROM custom_roles WHERE guild_id=? AND id=?", (guild.id, ref))
    return True

