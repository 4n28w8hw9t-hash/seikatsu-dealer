"""Рынок ролей: игроки создают свои роли, выставляют их на продажу и получают процент."""
import re
import time

import discord
from discord import app_commands

from .core import ECON_LOCK, _B, _G, bot, btn, icon_emoji, embed, fmt, member_name, reply, send_card

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
    await bot.db.execute("DELETE FROM role_owners WHERE guild_id=? AND role_ref=?", (guild.id, r["id"]))
    await bot.db.execute("DELETE FROM custom_roles WHERE guild_id=? AND id=?", (guild.id, r["id"]))
    await bot.db.commit()
    return True


NO_RIGHTS = ("Не получилось: боту нужно право «Управлять ролями», "
             "и его роль должна стоять выше ролей игроков")


# ═════════ Магазин ═════════
@bot.tree.command(name="магазин", description="Роли, которые игроки выставили на продажу")
async def market(inter: discord.Interaction):
    await show_market(inter)


async def show_market(inter: discord.Interaction, page: int = 0):
    guild_id = inter.guild_id
    async with bot.db.execute(
        "SELECT COUNT(*) FROM custom_roles WHERE guild_id=? AND price IS NOT NULL", (guild_id,)
    ) as cur:
        total = (await cur.fetchone())[0]
    pages = max(1, (total + MARKET_PAGE_SIZE - 1) // MARKET_PAGE_SIZE)
    page = max(0, min(page, pages - 1))
    offset = page * MARKET_PAGE_SIZE
    cur = await bot.db.execute(
        f"SELECT {','.join(FIELDS)} FROM custom_roles WHERE guild_id=? AND price IS NOT NULL "
        "ORDER BY sold DESC, price ASC, id ASC LIMIT ? OFFSET ?", (guild_id, MARKET_PAGE_SIZE, offset))
    rows = [dict(zip(FIELDS, r)) for r in await cur.fetchall()]
    lines = []
    for i, r in enumerate(rows, start=offset + 1):
        owner = await member_name(inter.guild, r["owner_id"])
        lines.append(f"`{i}.` <@&{r['role_id']}> — **{fmt(r['price'])}** · "
                     f"продаж: {r['sold']} · от {owner}")
    text = "\n".join(lines) if lines else "Пока никто ничего не выставил."
    e = embed("🛒 Магазин ролей", text +
              f"\n\nСвою роль можно создать за **{fmt(ROLE_CREATE_PRICE)}** и продавать другим.\n"
              f"-# Владелец получает {round(SELLER_SHARE * 100)}% с продажи · Страница {page + 1} из {pages}")
    rows_ui = []
    if rows:
        rows_ui.append([discord.ui.Select(
            custom_id="sd:mk:pick", placeholder="Выбери роль, чтобы купить",
            options=[discord.SelectOption(label=r["name"][:100], value=str(r["id"]),
                                          description=f"{r['price']} монет · продаж: {r['sold']}"[:100])
                     for r in rows])])
    if pages > 1:
        rows_ui.append([
            discord.ui.Button(label="Назад", custom_id=f"sd:mk:page:{page - 1 if page else 'start'}",
                              style=_G, disabled=page == 0),
            discord.ui.Button(label="Дальше", custom_id=f"sd:mk:page:{page + 1}", style=_G,
                              disabled=page + 1 >= pages),
        ])
    rows_ui.append(["rolecreate", "roles"])
    await send_card(inter, e, "shop", rows=rows_ui, allowed_mentions=discord.AllowedMentions.none())


async def show_for_sale(inter: discord.Interaction, ref: int):
    r = await get_role(inter.guild_id, ref)
    if not r or r["price"] is None or await forget_missing(inter.guild, r):
        return await reply(inter, "Эта роль уже не продаётся", rows=[["market"]])
    owner = await member_name(inter.guild, r["owner_id"])
    e = embed(f"🎭 {r['name']}", f"Цвет: **{color_of(r)}**\nСоздатель: **{owner}**\n"
              f"Продаж: **{r['sold']}**\nЦена: **{fmt(r['price'])}**",
              discord.Colour(r["color"]))
    buy = discord.ui.Button(label=f"Купить за {r['price']}", emoji=icon_emoji("🛍️"),
                            style=discord.ButtonStyle.success, custom_id=f"sd:mk:buy:{r['id']}")
    await send_card(inter, e, "shop", rows=[[buy, "market"]])


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
            "SELECT owner_id FROM custom_roles WHERE guild_id=? AND id=? AND role_id=?",
            (guild_id, ref, role_id)
        ) as cur:
            seller = await cur.fetchone()
        sold = False
        if granted and seller:
            row = await db.execute(
                "INSERT OR IGNORE INTO role_owners(guild_id,user_id,role_ref,worn) VALUES(?,?,?,1)", key)
            sold = row.rowcount == 1
        if sold:
            owner_id = seller[0]
            share = int(price * SELLER_SHARE)
            await bot.ensure_user(db, guild_id, owner_id)
            await db.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?",
                             (share, guild_id, owner_id))
            await db.execute("UPDATE custom_roles SET sold=sold+1, earned=earned+? WHERE guild_id=? AND id=?",
                             (share, guild_id, ref))
        else:
            await bot.ensure_user(db, guild_id, user_id)
            await db.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?",
                             (price, guild_id, user_id))
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


async def buy_role(inter: discord.Interaction, ref: int):
    g, uid = inter.guild_id, inter.user.id
    r = await get_role(g, ref)
    if not r or r["price"] is None or await forget_missing(inter.guild, r):
        return await reply(inter, "Эта роль уже не продаётся", rows=[["market"]])
    state = await reserve_role_purchase(g, uid, r)
    pending_note = "Покупка ещё проверяется. Бот завершит её или вернёт монеты автоматически."
    if state == "owned":
        return await reply(inter, "Эта роль у тебя уже есть", rows=[["roles", "market"]])
    if state == "pending":
        return await reply(inter, pending_note, rows=[["inventory", "market"]])
    if state == "insufficient":
        return await reply(inter, f"Не хватает монет: нужно **{fmt(r['price'])}**",
                           rows=[["daily", "market"]])

    try:
        try:
            await inter.user.add_roles(discord.Object(id=r["role_id"]), reason="Покупка в магазине ролей")
        except (discord.Forbidden, discord.NotFound):
            await settle_role_purchase(g, uid, ref, granted=False)
            return await reply(inter, "Роль не выдана. Монеты возвращены.", rows=[["market"]])
        state = await settle_role_purchase(g, uid, ref, granted=True)
    except Exception as ex:
        print("Не завершена покупка роли:", g, ref, repr(ex))
        return await reply(inter, pending_note, rows=[["inventory", "market"]])
    if state != "sold":
        return await reply(inter, "Покупка отменена. Монеты возвращены.", rows=[["market"]])
    e = embed(f"🛍️ Куплено: {r['name']}", f"Списано **{fmt(r['price'])}**. Роль уже на тебе.\n"
              "Снять или надеть её можно в инвентаре.", discord.Colour(r["color"]))
    await send_card(inter, e, "shop", rows=[["inventory", "market"]])


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
    await place_role(g, role)
    try:
        await inter.user.add_roles(role, reason="Создатель роли")
    except discord.HTTPException:
        pass
    await bot.add(g.id, uid, -ROLE_CREATE_PRICE)
    cur = await bot.db.execute(
        "INSERT INTO custom_roles(guild_id,owner_id,role_id,name,color,price,created) "
        "VALUES(?,?,?,?,?,NULL,?)", (g.id, uid, role.id, name, color, int(time.time())))
    await bot.db.execute("INSERT INTO role_owners(guild_id,role_ref,user_id,worn) VALUES(?,?,?,1)",
                         (g.id, cur.lastrowid, uid))
    await bot.db.commit()
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
    roles = await owned_roles(inter.guild_id, inter.user.id)
    roles = [r for r in roles if not await forget_missing(inter.guild, r)]
    mine = [r for r in roles if r["owner_id"] == inter.user.id]
    lines = []
    for r in roles:
        tags = []
        if r["owner_id"] == inter.user.id:
            tags.append("⭐ твоя")
            tags.append(f"в продаже за {r['price']}" if r["price"] is not None else "не продаётся")
            tags.append(f"продаж: {r['sold']}, заработано: {r['earned']}")
        tags.append("надета" if r["worn"] else "снята")
        lines.append(f"<@&{r['role_id']}> — " + " · ".join(tags))
    text = "\n".join(lines) if lines else "У тебя пока нет ролей."
    e = embed("🎭 Мои роли", text + f"\n\nСоздано: **{len(mine)}/{ROLE_LIMIT}**")
    rows = []
    if roles:
        rows.append([discord.ui.Select(
            custom_id="sd:mk:mine", placeholder="Выбери роль",
            options=[discord.SelectOption(label=r["name"][:100], value=str(r["id"]),
                                          emoji=icon_emoji("⭐") if r["owner_id"] == inter.user.id else None)
                     for r in roles[:25]])])
    rows.append(["rolecreate", "market"])
    await send_card(inter, e, "inv", rows=rows, allowed_mentions=discord.AllowedMentions.none())


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
            custom_id="sd:mk:mine", placeholder="Выбери роль",
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
    await send_card(inter, embed("🎒 Инвентарь · Кольца", text), "shop", rows=rows)


async def show_mine(inter: discord.Interaction, ref: int):
    roles = {r["id"]: r for r in await owned_roles(inter.guild_id, inter.user.id)}
    r = roles.get(ref)
    if not r or await forget_missing(inter.guild, r):
        return await reply(inter, "Этой роли у тебя нет", rows=[["roles"]])
    own = r["owner_id"] == inter.user.id
    info = [f"Цвет: **{color_of(r)}**", f"Сейчас: **{'надета' if r['worn'] else 'снята'}**"]
    btn = []
    btn.append(discord.ui.Button(label="Снять" if r["worn"] else "Надеть",
                                 emoji=icon_emoji("👕"), style=discord.ButtonStyle.secondary,
                                 custom_id=f"sd:mk:{'off' if r['worn'] else 'on'}:{ref}"))
    if own:
        info.append(f"Продаж: **{r['sold']}** · заработано: **{fmt(r['earned'])}**")
        if r["price"] is None:
            info.append("В магазине: **нет**")
            btn.append(discord.ui.Button(label="Выставить на продажу", emoji=icon_emoji("🏷️"),
                                         style=discord.ButtonStyle.success,
                                         custom_id=f"sd:mk:sell:{ref}"))
        else:
            info.append(f"В магазине за **{fmt(r['price'])}**")
            btn.append(discord.ui.Button(label="Изменить цену", emoji=icon_emoji("🏷️"),
                                         style=discord.ButtonStyle.primary,
                                         custom_id=f"sd:mk:sell:{ref}"))
            btn.append(discord.ui.Button(label="Снять с продажи", emoji=icon_emoji("✖️"),
                                         style=discord.ButtonStyle.danger,
                                         custom_id=f"sd:mk:unsell:{ref}"))
    e = embed(f"🎭 {r['name']}" + (" ⭐" if own else ""), "\n".join(info), discord.Colour(r["color"]))
    await send_card(inter, e, "inv", rows=[btn + ["roles", "inventory"]])


async def wear(inter: discord.Interaction, ref: int, on: bool):
    roles = {r["id"]: r for r in await owned_roles(inter.guild_id, inter.user.id)}
    r = roles.get(ref)
    if not r:
        return await reply(inter, "Этой роли у тебя нет", rows=[["roles"]])
    try:
        obj = discord.Object(id=r["role_id"])
        if on:
            await inter.user.add_roles(obj, reason="Надел свою роль")
        else:
            await inter.user.remove_roles(obj, reason="Снял свою роль")
    except discord.HTTPException:
        return await reply(inter, NO_RIGHTS)
    await bot.db.execute("UPDATE role_owners SET worn=? WHERE guild_id=? AND role_ref=? AND user_id=?",
                         (int(on), inter.guild_id, ref, inter.user.id))
    await bot.db.commit()
    await show_mine(inter, ref)


async def set_price(inter: discord.Interaction, ref: int, price: int | None):
    r = await get_role(inter.guild_id, ref)
    if not r or r["owner_id"] != inter.user.id:
        return await reply(inter, "Продавать можно только свою роль", rows=[["roles"]])
    if price is not None and not PRICE_MIN <= price <= PRICE_MAX:
        return await reply(inter, f"Цена — от {PRICE_MIN} до {PRICE_MAX:,}".replace(",", " "),
                           rows=[["roles"]])
    await bot.db.execute("UPDATE custom_roles SET price=? WHERE id=?", (price, ref))
    await bot.db.commit()
    await show_mine(inter, ref)


class PriceModal(discord.ui.Modal, title="Цена роли"):
    price = discord.ui.TextInput(label="Сколько монет", placeholder="например 2000", max_length=7)

    def __init__(self, ref: int):
        super().__init__()
        self.ref = ref

    async def on_submit(self, inter: discord.Interaction):
        raw = self.price.value.strip().replace(" ", "")
        if not raw.isdigit():
            return await inter.response.send_message("Нужно целое число", ephemeral=True)
        from .menu import run_fn
        await run_fn(inter, lambda i: set_price(i, self.ref, int(raw)))


# ═════════ Кнопки и списки рынка (sd:mk:...) ═════════
def modal_for(key: str):
    """Окно ввода для кнопки, если оно нужно, иначе None."""
    if key == "rolecreate":
        return CreateRoleModal()
    m = re.fullmatch(r"mk:sell:(\d+)", key)
    return PriceModal(int(m.group(1))) if m else None


async def handle(inter: discord.Interaction, key: str):
    values = (inter.data or {}).get("values") or []
    parts = key.split(":")
    act = parts[1] if len(parts) > 1 else ""
    if act in ("pick", "mine"):
        if not values or not values[0].isdigit():
            return
        ref = int(values[0])
        return await (show_for_sale(inter, ref) if act == "pick" else show_mine(inter, ref))
    if len(parts) != 3 or not parts[2].isdigit():
        return
    ref = int(parts[2])
    if act == "page":
        await show_market(inter, ref)
    elif act == "buy":
        await buy_role(inter, ref)
    elif act in ("on", "off"):
        await wear(inter, ref, act == "on")
    elif act == "unsell":
        await set_price(inter, ref, None)


async def delete_role(guild: discord.Guild, ref: int) -> bool:
    """Для админов: удалить роль игрока полностью."""
    r = await get_role(guild.id, ref)
    if not r:
        return False
    role = guild.get_role(r["role_id"])
    if role:
        try:
            await role.delete(reason="Удалена админом")
        except discord.HTTPException:
            pass
    await bot.db.execute("DELETE FROM role_owners WHERE guild_id=? AND role_ref=?", (guild.id, ref))
    await bot.db.execute("DELETE FROM custom_roles WHERE guild_id=? AND id=?", (guild.id, ref))
    await bot.db.commit()
    return True

