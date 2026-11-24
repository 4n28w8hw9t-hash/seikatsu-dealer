"""Команды админов /эко и обработка ошибок команд."""
import discord
from discord import app_commands

from .core import V2, bot, build_classic, build_page, fmt, reply
from .market import delete_role
from .marriage import dissolve, get_marriage
from .menu import menu_page


# ═════════ Админ-команды ═════════
admin = app_commands.Group(name="эко", description="Управление монетами",
                           default_permissions=discord.Permissions(administrator=True),
                           guild_only=True)


@admin.command(name="выдать", description="Выдать монеты")
async def a_give(inter: discord.Interaction, участник: discord.Member, сумма: int):
    await bot.add(inter.guild_id, участник.id, сумма)
    await reply(inter, f"✅ Выдано {участник.mention}: **{fmt(сумма)}**", key=None, nav=False)


@admin.command(name="забрать", description="Забрать монеты из кошелька")
async def a_take(inter: discord.Interaction, участник: discord.Member, сумма: int):
    await bot.add(inter.guild_id, участник.id, -сумма)
    await reply(inter, f"✅ Забрано у {участник.mention}: **{fmt(сумма)}**", key=None, nav=False)


@admin.command(name="сбросить", description="Обнулить участника")
async def a_reset(inter: discord.Interaction, участник: discord.Member):
    await bot.db.execute("DELETE FROM users WHERE guild_id=? AND user_id=?",
                         (inter.guild_id, участник.id))
    await bot.db.execute("DELETE FROM rings WHERE guild_id=? AND user_id=?",
                         (inter.guild_id, участник.id))
    await bot.db.commit()
    mar = await get_marriage(inter.guild_id, участник.id)
    if mar:
        await dissolve(inter.guild, mar)
    await reply(inter, f"♻️ {участник.mention} обнулён", key=None, nav=False)


@admin.command(name="роль_удалить", description="Удалить роль, созданную игроком")
@app_commands.describe(роль="Какую роль удалить")
async def a_del_role(inter: discord.Interaction, роль: discord.Role):
    cur = await bot.db.execute("SELECT id FROM custom_roles WHERE guild_id=? AND role_id=?",
                               (inter.guild_id, роль.id))
    row = await cur.fetchone()
    if not row:
        return await reply(inter, "Это не роль игрока", key=None, nav=False)
    await delete_role(inter.guild, row[0])
    await reply(inter, f"🗑️ Роль **{роль.name}** удалена", key=None, nav=False)


@admin.command(name="панель", description="Поставить в этот канал постоянное меню с кнопками")
async def a_panel(inter: discord.Interaction):
    try:
        sent = False
        if V2:
            try:
                view, files = build_page(**menu_page())
                await inter.channel.send(view=view, files=files)
                sent = True
            except discord.Forbidden:
                raise
            except Exception as ex:
                print("Панель в новом виде не отправлена:", repr(ex))
        if not sent:
            kw = build_classic(**menu_page())
            await inter.channel.send(embed=kw["embed"], files=kw["attachments"], view=kw["view"])
    except discord.HTTPException:
        return await reply(inter, "Не могу написать в этот канал — у бота нет прав", key=None, nav=False)
    await reply(inter, "✅ Панель поставлена. Закрепи сообщение, чтобы оно не уезжало.", key=None, nav=False)


bot.tree.add_command(admin)


@bot.tree.error
async def on_app_error(inter: discord.Interaction, error: app_commands.AppCommandError):
    msg = "Нет прав на эту команду" if isinstance(error, app_commands.MissingPermissions) \
        else f"Ошибка: {error}"
    print("Ошибка команды:", repr(error))
    try:
        await reply(inter, msg, key=None)
    except discord.HTTPException:
        pass


# ═════════ Админ-панель /админ (по ролям) ═════════
import asyncio  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import time  # noqa: E402

import art  # noqa: E402

from .core import E, ECON_LOCK  # noqa: E402
from .levels import PATHS, get_path, get_xp, level_of, rank_of, is_female, xp_for  # noqa: E402
from .marriage import RINGS, get_rings  # noqa: E402

ADMIN_ROLES = {1365248221269463060, 1574154563051720795}   # кому доступна панель


def is_staff(member) -> bool:
    if getattr(getattr(member, "guild_permissions", None), "administrator", False):
        return True
    return any(r.id in ADMIN_ROLES for r in getattr(member, "roles", []))


def num(n: int) -> str:
    """Число с пробелами, без значка монеты (для картинки)."""
    return f"{int(n):,}".replace(",", " ")


def em(name: str, fallback: str):
    """Своя иконка бота sd_<name> для кнопки, иначе обычный эмодзи."""
    custom = E(f"sd_{name}")
    if custom:
        try:
            return discord.PartialEmoji.from_str(custom)
        except Exception:
            pass
    return fallback


async def staff_card(guild: discord.Guild, m: discord.Member, note: str = ""):
    """Карточка участника для админ-панели: (эмбед, файл-картинка)."""
    g = guild.id
    u = await bot.get_user(g, m.id)
    xp = await get_xp(g, m.id)
    lvl = level_of(xp)
    path = await get_path(g, m.id)
    title = rank_of(lvl, path, is_female(m))
    rings = await get_rings(g, m.id)
    now = int(time.time())
    daily_ok = now - u["last_daily"] >= 86400
    work_ok = now - u["last_work"] >= 12 * 3600
    lo, hi = xp_for(lvl), xp_for(lvl + 1)
    ring_n = sum(rings.values())
    ring_note = " · ".join(f"{RINGS[k][0].split()[0][:3].lower()} {v}" for k, v in rings.items() if v)
    tiles = [("coin", "Монеты", num(u["balance"]), "кошелёк", True),
             ("top", "Уровень", str(lvl), f"{num(xp)} опыта", True),
             (path or "path", "Путь", PATHS[path][1] if path else "—", title or "не выбран", bool(path)),
             ("ring", "Кольца", str(ring_n), ring_note or "нет колец", ring_n > 0)]
    lines = [("gift", f"Награда: {'готова' if daily_ok else 'уже получена'} · серия {u['streak']}"),
             ("work", f"Работа: {'можно идти' if work_ok else 'на перерыве'}")]
    if note:
        lines.append(("win", note))
    try:
        avatar = await m.display_avatar.replace(size=128, format="png").read()
    except Exception:
        avatar = None
    bn = getattr(bot, "banners", {})
    banner = bn.get("admin") or bn.get("top")
    try:
        img = await asyncio.to_thread(
            art.panel_card, banner, m.display_name, f"@{m.name} · канцелярия двора", "",
            ((xp - lo) / max(hi - lo, 1), f"{lvl} уровень", f"до {lvl + 1}: {num(hi - xp)} опыта"),
            tiles, lines, 1200, avatar)
        e = discord.Embed(color=discord.Color.from_rgb(150, 30, 40))
        e.set_image(url="attachment://staff.jpg")
        e.set_footer(text="Изменения сохраняются сразу · все действия пишутся в журнал")
        return e, discord.File(io.BytesIO(img), filename="staff.jpg")
    except Exception as ex:   # картинка не нарисовалась — простой текст
        print("Админ-карточка не нарисована:", repr(ex))
        e = discord.Embed(title=f"🛠️ {m.display_name}", color=discord.Color.dark_red(),
                          description=(f"✅ {note}\n" if note else "") +
                          f"💰 **{num(u['balance'])}** · ⭐ **{lvl}** ур. ({num(xp)} опыта)\n"
                          f"👑 {PATHS[path][1] + ' · ' + title if path else 'путь не выбран'} · 💍 {ring_n}")
        e.set_thumbnail(url=m.display_avatar.url)
        return e, None


def log(inter: discord.Interaction, m: discord.Member, what: str):
    print(f"[АДМИН] {inter.user} ({inter.user.id}) → {m} ({m.id}): {what}")


class NumModal(discord.ui.Modal):
    def __init__(self, panel: "StaffView", kind: str, title: str, label: str, hint: str):
        super().__init__(title=title)
        self.panel, self.kind = panel, kind
        self.value = discord.ui.TextInput(label=label, placeholder=hint, max_length=12)
        self.add_item(self.value)

    async def on_submit(self, inter: discord.Interaction):
        raw = str(self.value.value).replace(" ", "").replace("+", "")
        try:
            n = int(raw)
        except ValueError:
            return await inter.response.send_message("Нужно целое число", ephemeral=True)
        await self.panel.apply(inter, self.kind, n)


class StaffView(discord.ui.View):
    def __init__(self, owner_id: int, member: discord.Member | None = None):
        super().__init__(timeout=900)
        self.owner_id, self.member = owner_id, member
        if member is None:   # пока участник не выбран — только выбор
            for item in list(self.children):
                if not isinstance(item, discord.ui.UserSelect):
                    self.remove_item(item)
        icons = {"Монеты ±": ("adm_plus", "💰"), "Задать баланс": ("adm_scales", "🏦"),
                 "Уровень": ("adm_level", "⭐"), "Опыт ±": ("adm_xp", "✨"),
                 "Обновить": ("adm_log", "🔄"), "Обнулить участника": ("adm_burn", "♻️")}
        opt_icons = {"path:noble": "noble", "path:faith": "faith", "path:none": "cancel",
                     "ring:silver": "ring_silver", "ring:gold": "ring_gold", "ring:ruby": "ring_ruby",
                     "cd": "adm_cd", "streak": "gift"}
        for item in self.children:
            if isinstance(item, discord.ui.Button) and item.label in icons:
                item.emoji = em(*icons[item.label])
            elif isinstance(item, discord.ui.Select) and not isinstance(item, discord.ui.UserSelect):
                for o in item.options:
                    if o.value in opt_icons:
                        o.emoji = em(opt_icons[o.value], o.emoji)

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.owner_id or not is_staff(inter.user):
            await inter.response.send_message("Это не твоя панель", ephemeral=True)
            return False
        return True

    async def show(self, inter: discord.Interaction, note: str = ""):
        if not inter.response.is_done():
            await inter.response.defer()
        e, f = await staff_card(inter.guild, self.member, note)
        await inter.edit_original_response(embed=e, attachments=[f] if f else [],
                                           view=StaffView(self.owner_id, self.member))

    async def apply(self, inter: discord.Interaction, kind: str, n: int):
        g, m = inter.guild_id, self.member
        async with ECON_LOCK:
            if kind == "coins_add":
                await bot.add(g, m.id, n)
                note = f"{'Выдано' if n >= 0 else 'Забрано'} {num(abs(n))} монет"
            elif kind == "coins_set":
                await bot.get_user(g, m.id)
                await bot.set_field(g, m.id, balance=max(n, 0))
                note = f"Баланс теперь {num(max(n, 0))}"
            elif kind == "level_set":
                n = max(1, min(n, 200))
                await bot.get_user(g, m.id)
                await bot.set_field(g, m.id, xp=xp_for(n))
                note = f"Уровень теперь {n}"
            elif kind == "xp_add":
                xp = await get_xp(g, m.id)
                await bot.set_field(g, m.id, xp=max(xp + n, 0))
                note = f"Опыт {'+' if n >= 0 else '−'}{num(abs(n))}"
            else:
                return
        log(inter, m, note)
        await self.show(inter, note)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Выбери участника", row=0)
    async def pick(self, inter: discord.Interaction, select: discord.ui.UserSelect):
        m = select.values[0]
        if not isinstance(m, discord.Member):
            m = inter.guild.get_member(m.id) or await inter.guild.fetch_member(m.id)
        if m.bot:
            return await inter.response.send_message("Это бот", ephemeral=True)
        self.member = m
        await self.show(inter)

    @discord.ui.button(label="Монеты ±", emoji="💰", style=discord.ButtonStyle.success, row=1)
    async def b_coins(self, inter, _):
        await inter.response.send_modal(NumModal(self, "coins_add", "Выдать или забрать монеты",
                                                 "Сколько монет", "500 — выдать, -500 — забрать"))

    @discord.ui.button(label="Задать баланс", emoji="🏦", style=discord.ButtonStyle.secondary, row=1)
    async def b_set(self, inter, _):
        await inter.response.send_modal(NumModal(self, "coins_set", "Задать баланс",
                                                 "Новый баланс", "например 1000"))

    @discord.ui.button(label="Уровень", emoji="⭐", style=discord.ButtonStyle.primary, row=1)
    async def b_level(self, inter, _):
        await inter.response.send_modal(NumModal(self, "level_set", "Задать уровень",
                                                 "Какой уровень поставить", "от 1 до 200"))

    @discord.ui.button(label="Опыт ±", emoji="✨", style=discord.ButtonStyle.primary, row=1)
    async def b_xp(self, inter, _):
        await inter.response.send_modal(NumModal(self, "xp_add", "Добавить или убрать опыт",
                                                 "Сколько опыта", "300 — добавить, -300 — убрать"))

    @discord.ui.select(placeholder="Путь / кольца / сбросы", row=2, options=[
        discord.SelectOption(label="Путь: Знать", value="path:noble", emoji="👑"),
        discord.SelectOption(label="Путь: Вера", value="path:faith", emoji="✝️"),
        discord.SelectOption(label="Убрать путь", value="path:none", emoji="➖"),
        discord.SelectOption(label="Выдать серебряное кольцо", value="ring:silver", emoji="💍"),
        discord.SelectOption(label="Выдать золотое кольцо", value="ring:gold", emoji="💛"),
        discord.SelectOption(label="Выдать кольцо с рубином", value="ring:ruby", emoji="❤️"),
        discord.SelectOption(label="Сбросить откат награды и работы", value="cd", emoji="⏱️"),
        discord.SelectOption(label="Обнулить серию наград", value="streak", emoji="🔁"),
    ])
    async def more(self, inter: discord.Interaction, select: discord.ui.Select):
        g, m, v = inter.guild_id, self.member, select.values[0]
        async with ECON_LOCK:
            await bot.get_user(g, m.id)
            if v.startswith("path:"):
                p = v[5:]
                await bot.set_field(g, m.id, path=None if p == "none" else p, path_changed=0)
                note = "Путь убран" if p == "none" else f"Путь: {PATHS[p][1]}"
            elif v.startswith("ring:"):
                k = v[5:]
                await bot.db.execute(
                    "INSERT INTO rings(guild_id,user_id,ring,qty) VALUES(?,?,?,1) "
                    "ON CONFLICT(guild_id,user_id,ring) DO UPDATE SET qty=qty+1", (g, m.id, k))
                await bot.db.commit()
                note = f"Выдано: {RINGS[k][0]}"
            elif v == "cd":
                await bot.set_field(g, m.id, last_daily=0, last_work=0)
                note = "Награда и работа снова доступны"
            else:
                await bot.set_field(g, m.id, streak=0)
                note = "Серия наград обнулена"
        log(inter, m, note)
        await self.show(inter, note)

    @discord.ui.button(label="Обновить", emoji="🔄", style=discord.ButtonStyle.secondary, row=3)
    async def b_refresh(self, inter, _):
        await self.show(inter)

    @discord.ui.button(label="Обнулить участника", emoji="♻️", style=discord.ButtonStyle.danger, row=3)
    async def b_reset(self, inter, _):
        await inter.response.edit_message(view=ConfirmReset(self))


class ConfirmReset(discord.ui.View):
    def __init__(self, panel: StaffView):
        super().__init__(timeout=120)
        self.panel = panel

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        return inter.user.id == self.panel.owner_id

    @discord.ui.button(label="Да, обнулить всё", style=discord.ButtonStyle.danger)
    async def yes(self, inter: discord.Interaction, _):
        m = self.panel.member
        async with ECON_LOCK:
            await bot.db.execute("DELETE FROM users WHERE guild_id=? AND user_id=?", (inter.guild_id, m.id))
            await bot.db.execute("DELETE FROM rings WHERE guild_id=? AND user_id=?", (inter.guild_id, m.id))
            await bot.db.commit()
            mar = await get_marriage(inter.guild_id, m.id)
            if mar:
                await dissolve(inter.guild, mar)
        log(inter, m, "обнулён")
        await self.panel.show(inter, "Участник обнулён")

    @discord.ui.button(label="Отмена", style=discord.ButtonStyle.secondary)
    async def no(self, inter: discord.Interaction, _):
        await self.panel.show(inter)


@bot.tree.command(name="админ", description="Админ-панель: монеты, уровни, пути, кольца участников")
@app_commands.guild_only()
@app_commands.describe(участник="Кого открыть сразу (можно выбрать потом в меню)")
async def staff_panel(inter: discord.Interaction, участник: discord.Member | None = None):
    if not is_staff(inter.user):
        return await inter.followup.send("🥀 Панель только для администрации", ephemeral=True)
    if участник and участник.bot:
        участник = None
    view = StaffView(inter.user.id, участник)
    if участник:
        e, f = await staff_card(inter.guild, участник)
    else:
        bn = getattr(bot, "banners", {})
        path = bn.get("admin") or bn.get("top")
        f = discord.File(path, filename="staff.jpg") if path and os.path.exists(path) else None
        e = discord.Embed(title="Канцелярия двора",
                          description="Выбери участника в списке ниже — откроется его карточка.\n"
                                      "-# Монеты · уровень · опыт · путь · кольца · сбросы",
                          color=discord.Color.from_rgb(150, 30, 40))
        if f:
            e.set_image(url="attachment://staff.jpg")
    kw = {"file": f} if f else {}
    await inter.followup.send(embed=e, view=view, ephemeral=True, **kw)


# ═════════ Роли-разделители: выдаются, только если есть роль из их раздела ═════════
DIVIDERS = [1574467661067194410, 1574469695627591700]   # staff, roles
MEMBER_ROLE = 1365250956710772756   # member: у всех всегда, выдаётся при входе
WRONG_DIVIDER = 1365250956710772756   # по ошибке считалась разделителем 23.11 — откатываем


def _sections(guild: discord.Guild) -> dict[int, set[int]]:
    """Разделитель → айди ролей под ним (до следующего разделителя ниже)."""
    divs = sorted([r for r in (guild.get_role(i) for i in DIVIDERS) if r],
                  key=lambda r: r.position, reverse=True)
    out = {}
    for i, d in enumerate(divs):
        low = divs[i + 1].position if i + 1 < len(divs) else 0
        out[d.id] = {r.id for r in guild.roles
                     if low < r.position < d.position and not r.is_default()
                     and r.id != MEMBER_ROLE and not r.is_bot_managed() and not r.is_integration()}
    return out


async def sync_dividers(member: discord.Member, sections=None):
    if member.bot:
        return
    sections = sections or _sections(member.guild)
    have = {r.id for r in member.roles}
    add, remove = [], []
    if member.guild.get_role(MEMBER_ROLE) and MEMBER_ROLE not in have:
        add.append(discord.Object(id=MEMBER_ROLE))
    for did, ids in sections.items():
        need = bool(have & ids)
        if need and did not in have:
            add.append(discord.Object(id=did))
        elif not need and did in have:
            remove.append(discord.Object(id=did))
    try:
        if add:
            await member.add_roles(*add, reason="Разделитель: есть роль из раздела")
        if remove:
            await member.remove_roles(*remove, reason="Разделитель: в разделе нет ролей")
    except discord.HTTPException as ex:
        print("Разделитель не выдан:", member, repr(ex))


@bot.listen("on_member_join")
async def _member_join(member: discord.Member):
    await sync_dividers(member)


@bot.listen("on_member_update")
async def _divider_update(before: discord.Member, after: discord.Member):
    if before.roles != after.roles:
        await sync_dividers(after)


async def undo_wrong_divider(g: discord.Guild):
    """Один раз: вернуть роль WRONG_DIVIDER тем, у кого бот её снял, и снять у тех, кому выдал."""
    import datetime
    key = f"undo_div_{g.id}"
    cur = await bot.db.execute("SELECT value FROM meta WHERE key=?", (key,))
    if await cur.fetchone():
        return
    since = datetime.datetime(2026, 11, 23, 17, 40, tzinfo=datetime.timezone.utc)
    back = gone = 0
    async for e in g.audit_logs(limit=None, after=since, action=discord.AuditLogAction.member_role_update):
        if not e.user or e.user.id != bot.user.id or not (e.reason or "").startswith("Разделитель"):
            continue
        m = g.get_member(getattr(e.target, "id", 0))
        if not m:
            continue
        removed = {r.id for r in getattr(e.before, "roles", []) or []}
        added = {r.id for r in getattr(e.after, "roles", []) or []}
        try:
            if WRONG_DIVIDER in removed and not m.get_role(WRONG_DIVIDER):
                await m.add_roles(discord.Object(id=WRONG_DIVIDER), reason="Откат ошибки разделителей")
                back += 1
            elif WRONG_DIVIDER in added and m.get_role(WRONG_DIVIDER):
                await m.remove_roles(discord.Object(id=WRONG_DIVIDER), reason="Откат ошибки разделителей")
                gone += 1
        except discord.HTTPException as ex:
            print("Откат не удался:", m, repr(ex))
    await bot.db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, "1"))
    await bot.db.commit()
    print(f"[РАЗДЕЛИТЕЛИ] откат: роль возвращена {back}, снята {gone}")


@bot.listen("on_ready")
async def _divider_startup():
    for g in bot.guilds:
        try:
            if not g.chunked:
                await g.chunk()
        except Exception as ex:
            print("Участники не загружены:", repr(ex))
        try:
            if not g.chunked:
                await g.chunk()
            sections = _sections(g)
            if not sections:
                continue
            for m in list(g.members):
                await sync_dividers(m, sections)
        except Exception as ex:
            print("Разделители не проверены:", repr(ex))


# ═════════ Устав двора: публикует Канцлер (вебхук) в канале устава ═════════
RULES_CHANNEL = 1370852188611416064
CRIMSON = discord.Color.from_rgb(150, 30, 40)
RULES = [
    ("Ⅰ · Верность двору", "Не вреди двору: никаких призывов покинуть сервер, мошенничества "
     "и критики ради разрушения."),
    ("Ⅱ · Честь и достоинство", "Держи себя достойно: без оскорблений, провокаций, агрессии, "
     "троллинга и криков в залах."),
    ("Ⅲ · Тишина залов", "Не засоряй залы: без спама, флуда и лишних упоминаний участников и ролей."),
    ("Ⅳ · Тайны покоев", "Чужие тайны неприкосновенны: никаких личных данных без согласия владельца, "
     "угроз, докса, свата и деанона."),
    ("Ⅴ · Запретные свитки", "Шокирующему, порнографическому и тошнотворному не место при дворе — "
     "ни в сообщениях, ни в трансляциях."),
    ("Ⅵ · Чужие знамёна", "Никакой рекламы сторонних ресурсов без дозволения Канцелярии."),
]


def rules_payload():
    """Эмбеды устава (как карточки) и файл баннера."""
    bn = getattr(bot, "banners", {})
    path = bn.get("ustav") or bn.get("admin")
    files, embeds = [], []
    if path and os.path.exists(path):
        files.append(discord.File(path, filename="ustav.jpg"))
        top = discord.Embed(color=CRIMSON)
        top.set_image(url="attachment://ustav.jpg")
        embeds.append(top)
    embeds.append(discord.Embed(
        color=CRIMSON,
        description="Добро пожаловать ко двору. Прочти устав — каждый, кто входит в эти залы, "
                    "принимает его.\n-# Нарушения рассматривает стража. Приговор окончателен, "
                    "обсуждение — в личных сообщениях стражи."))
    for title, rule in RULES:
        embeds.append(discord.Embed(title=title, description=rule, color=CRIMSON))
    embeds.append(discord.Embed(
        title="Кара за нарушения", color=discord.Color.from_rgb(110, 20, 28),
        description="Предупреждение → мут → изгнание из двора\n-# Тяжёлые нарушения — изгнание сразу."))
    return embeds, files


def _roles_channel(guild: discord.Guild):
    for ch in guild.text_channels:
        if "герб" in ch.name or "рол" in ch.name:
            return ch
    return None


class RulesView(discord.ui.View):
    """Кнопки под уставом (постоянные)."""
    def __init__(self, guild: discord.Guild | None = None):
        super().__init__(timeout=None)
        self.accept.emoji = em("adm_seal", "👑")
        self.ask.emoji = em("duel", "🛡️")
        ch = _roles_channel(guild) if guild else None
        if ch:
            self.add_item(discord.ui.Button(label="Гербы и роли", emoji=em("ring", "💞"), url=ch.jump_url))

    @discord.ui.button(label="Принимаю устав", style=discord.ButtonStyle.success, custom_id="court:rules:accept")
    async def accept(self, inter: discord.Interaction, _):
        await inter.response.send_message(
            "📜 Канцлер вносит твоё имя в книгу двора. Устав принят — добро пожаловать!", ephemeral=True)

    @discord.ui.button(label="Вопрос страже", style=discord.ButtonStyle.secondary, custom_id="court:rules:ask")
    async def ask(self, inter: discord.Interaction, _):
        roles = " ".join(f"<@&{r}>" for r in ADMIN_ROLES if inter.guild and inter.guild.get_role(r))
        await inter.response.send_message(
            f"🛡️ С вопросом по уставу напиши в личные сообщения страже: {roles or 'администрации'}.\n"
            "-# Спорить с решением в общих залах нельзя.", ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none())


async def _chancellor_hook(ch: discord.TextChannel):
    """Вебхук «Канцлер двора» в канале (создаётся один раз)."""
    for h in await ch.webhooks():
        if h.user and h.user.id == bot.user.id and h.name == "Канцлер двора":
            return h
    avatar = None
    path = getattr(bot, "banners", {}).get("ustav") or getattr(bot, "banners", {}).get("admin")
    if path and os.path.exists(path):
        from PIL import Image
        im = Image.open(path).convert("RGB")
        s = int(im.height * 0.62)
        face = im.crop((int(im.width * 0.13), int(im.height * 0.06),
                        int(im.width * 0.13) + s, int(im.height * 0.06) + s)).resize((256, 256))
        buf = io.BytesIO()
        face.save(buf, "PNG")
        avatar = buf.getvalue()
    return await ch.create_webhook(name="Канцлер двора", avatar=avatar, reason="Устав двора")


@bot.listen("on_ready")
async def post_rules():
    ch = bot.get_channel(RULES_CHANNEL)
    if not isinstance(ch, discord.TextChannel):
        return
    key = f"rules_msg_{ch.id}"
    try:
        cur = await bot.db.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = await cur.fetchone()
        embeds, files = rules_payload()
        view = RulesView(ch.guild)
        bot.add_view(RulesView())
        try:
            hook = await _chancellor_hook(ch)
        except discord.HTTPException as ex:   # нет права «Управлять вебхуками» — пишет сам бот
            print("Вебхук не создан:", repr(ex))
            hook = None
        if row:
            mid = int(row[0])
            try:
                if hook:
                    await hook.edit_message(mid, embeds=embeds, attachments=files, view=view)
                else:
                    msg = await ch.fetch_message(mid)
                    await msg.edit(embeds=embeds, attachments=files, view=view)
                return
            except discord.HTTPException:
                pass   # сообщение удалено или чужое — публикуем заново
        if hook:
            msg = await hook.send(embeds=embeds, files=files, view=view, wait=True)
        else:
            msg = await ch.send(embeds=embeds, files=files, view=view)
        await bot.db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, str(msg.id)))
        await bot.db.commit()
    except Exception as ex:
        print("Устав не опубликован:", repr(ex))
