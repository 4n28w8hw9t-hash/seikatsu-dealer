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
import time  # noqa: E402

from .core import ECON_LOCK  # noqa: E402
from .levels import PATHS, get_path, get_xp, level_of, rank_of, is_female, xp_for  # noqa: E402
from .marriage import RINGS, get_rings  # noqa: E402

ADMIN_ROLES = {1365248221269463060, 1574154563051720795}   # кому доступна панель


def is_staff(member) -> bool:
    if getattr(getattr(member, "guild_permissions", None), "administrator", False):
        return True
    return any(r.id in ADMIN_ROLES for r in getattr(member, "roles", []))


async def staff_card(guild: discord.Guild, m: discord.Member, note: str = "") -> discord.Embed:
    g = guild.id
    u = await bot.get_user(g, m.id)
    xp = await get_xp(g, m.id)
    lvl = level_of(xp)
    path = await get_path(g, m.id)
    title = rank_of(lvl, path, is_female(m))
    rings = await get_rings(g, m.id)
    now = int(time.time())
    daily = "готова" if now - u["last_daily"] >= 86400 else "уже получена"
    work = "можно" if now - u["last_work"] >= 12 * 3600 else "на перерыве"
    e = discord.Embed(title=f"🛠️ Админ-панель · {m.display_name}", color=discord.Color.dark_red())
    e.set_thumbnail(url=m.display_avatar.url)
    e.add_field(name="💰 Монеты", value=f"**{fmt(u['balance'])}**")
    e.add_field(name="⭐ Уровень", value=f"**{lvl}** · {fmt(xp)} опыта")
    e.add_field(name="👑 Путь", value=(f"{PATHS[path][1]} · {title}" if path else "не выбран"))
    e.add_field(name="🎁 Награда", value=f"{daily} · серия {u['streak']}")
    e.add_field(name="⚒️ Работа", value=work)
    e.add_field(name="💍 Кольца",
                value=", ".join(f"{RINGS[k][0].split()[0]} ×{v}" for k, v in rings.items() if v) or "нет")
    if note:
        e.description = f"✅ {note}"
    e.set_footer(text="Изменения сразу сохраняются. Все действия пишутся в лог бота.")
    return e


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

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.owner_id or not is_staff(inter.user):
            await inter.response.send_message("Это не твоя панель", ephemeral=True)
            return False
        return True

    async def show(self, inter: discord.Interaction, note: str = ""):
        view = StaffView(self.owner_id, self.member)
        await inter.response.edit_message(embed=await staff_card(inter.guild, self.member, note),
                                          view=view)

    async def apply(self, inter: discord.Interaction, kind: str, n: int):
        g, m = inter.guild_id, self.member
        async with ECON_LOCK:
            if kind == "coins_add":
                await bot.add(g, m.id, n)
                note = f"{'Выдано' if n >= 0 else 'Забрано'} {fmt(abs(n))} монет"
            elif kind == "coins_set":
                await bot.get_user(g, m.id)
                await bot.set_field(g, m.id, balance=max(n, 0))
                note = f"Баланс теперь {fmt(max(n, 0))}"
            elif kind == "level_set":
                n = max(1, min(n, 200))
                await bot.get_user(g, m.id)
                await bot.set_field(g, m.id, xp=xp_for(n))
                note = f"Уровень теперь {n}"
            elif kind == "xp_add":
                xp = await get_xp(g, m.id)
                await bot.set_field(g, m.id, xp=max(xp + n, 0))
                note = f"Опыт {'+' if n >= 0 else '−'}{fmt(abs(n))}"
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
        e = await staff_card(inter.guild, участник)
    else:
        e = discord.Embed(title="🛠️ Админ-панель",
                          description="Выбери участника в списке ниже — откроется его карточка "
                                      "с кнопками: монеты, уровень, опыт, путь, кольца, сбросы.",
                          color=discord.Color.dark_red())
    await inter.followup.send(embed=e, view=view, ephemeral=True)
