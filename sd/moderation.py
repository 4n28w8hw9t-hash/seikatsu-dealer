"""Privileged Discord moderation actions for the staff panel."""
from datetime import timedelta
import os
import time

import aiosqlite

import discord

from .admin import StaffSection, edit_staff_page, em, is_staff, log
from .core import bot

ACTIONS = {
    "warn": ("Предупреждение", "moderate_members", "⚠️"),
    "mute": ("Мут", "moderate_members", "🔇"),
    "unmute": ("Снять мут", "moderate_members", "🔊"),
    "kick": ("Кик", "kick_members", "🚪"),
    "ban": ("Бан", "ban_members", "⛔"),
    "unban": ("Разбан", "ban_members", "🔓"),
}
MAX_TIMEOUT_MINUTES = 28 * 24 * 60
MAX_MEMBER_ID = (1 << 63) - 1
NO_MENTIONS = discord.AllowedMentions.none()


def moderation_problem(guild, actor, target, action):
    permission = ACTIONS[action][1]
    if not is_staff(actor) or not getattr(actor.guild_permissions, permission):
        return "У тебя нет права выполнить это действие."
    me = guild.me
    if me is None or not getattr(me.guild_permissions, permission):
        return "У бота нет нужного права Discord."
    if target is None:
        return None
    if target.id in (guild.owner_id, actor.id, me.id):
        return "Это действие для выбранного участника недоступно."
    if (actor.id != guild.owner_id and actor.top_role <= target.top_role) or me.top_role <= target.top_role:
        return "Роль участника должна быть ниже твоей роли и роли бота."
    if action in ("mute", "unmute") and target.guild_permissions.administrator:
        return "Discord не позволяет выдать мут администратору."
    return None


class ModerationModal(discord.ui.Modal):
    def __init__(self, owner_id, member, action):
        label = ACTIONS[action][0]
        title = f"{label} · {member.display_name}" if member is not None else label
        super().__init__(title=title[:45], timeout=120)
        self.owner_id = owner_id
        self.member_id = member.id if member is not None else None
        self.action = action
        self.input_number = None
        if action == "mute":
            self.input_number = discord.ui.TextInput(label="Длительность в минутах", default="60",
                                                      min_length=1, max_length=5)
        elif action == "unban":
            self.input_number = discord.ui.TextInput(label="ID пользователя", min_length=15, max_length=20)
        if self.input_number is not None:
            self.add_item(self.input_number)
        self.reason = discord.ui.TextInput(label="Причина", max_length=300)
        self.add_item(self.reason)

    async def on_submit(self, inter: discord.Interaction):
        await inter.response.defer(ephemeral=True, thinking=inter.message is None)
        if inter.user.id != self.owner_id or inter.guild is None:
            return await inter.followup.send("Панель недоступна.", ephemeral=True)

        value = self.input_number.value.strip() if self.input_number is not None else ""
        if self.input_number is not None and (not value.isascii() or not value.isdecimal()):
            return await inter.followup.send("Введи положительное целое число.", ephemeral=True)

        number = int(value) if value else 0
        action = self.action
        if action == "mute" and not 1 <= number <= MAX_TIMEOUT_MINUTES:
            return await inter.followup.send(f"Допустимая длительность от 1 до {MAX_TIMEOUT_MINUTES} мин.",
                                             ephemeral=True)
        if action == "unban" and not 0 < number <= MAX_MEMBER_ID:
            return await inter.followup.send("Проверь ID пользователя.", ephemeral=True)

        guild = inter.guild
        reason = " ".join(self.reason.value.split())
        if not reason:
            return await inter.followup.send("Укажи причину.", ephemeral=True)
        audit_reason = f"{inter.user.id} · {reason}"
        deadline = None
        try:
            actor = await guild.fetch_member(inter.user.id)
            problem = moderation_problem(guild, actor, None, action)
            if problem:
                return await inter.followup.send(problem, ephemeral=True)
            if action == "unban":
                target = discord.Object(id=number)
                await guild.unban(target, reason=audit_reason)
            else:
                target = await guild.fetch_member(self.member_id)
                problem = moderation_problem(guild, actor, target, action)
                if problem:
                    return await inter.followup.send(problem, ephemeral=True)
                if action == "mute":
                    deadline = discord.utils.utcnow() + timedelta(minutes=number)
                    await target.timeout(deadline, reason=audit_reason)
                elif action == "unmute":
                    if not target.is_timed_out():
                        return await inter.followup.send("У участника уже нет активного мута.", ephemeral=True)
                    await target.timeout(None, reason=audit_reason)
                elif action == "kick":
                    await target.kick(reason=audit_reason)
                elif action == "ban":
                    await target.ban(delete_message_seconds=0, reason=audit_reason)
        except discord.NotFound:
            return await inter.followup.send("Discord не нашёл участника или действующий бан.", ephemeral=True)
        except discord.Forbidden:
            return await inter.followup.send("Discord отклонил действие. Проверь права и порядок ролей.",
                                             ephemeral=True)
        except discord.HTTPException as ex:
            print("Не подтверждена модерация:", inter.guild_id, action, repr(ex))
            return await inter.followup.send("Discord не подтвердил действие. Проверь журнал сервера.",
                                             ephemeral=True)

        self.stop()
        label = ACTIONS[action][0]
        duration = f" на {number} мин" if action == "mute" else ""
        journal_reason = discord.utils.escape_markdown(discord.utils.escape_mentions(reason))
        log(inter, target, f"{label}{duration}. Причина — {journal_reason}")
        notice = f"**{label}**{duration} · <@{target.id}>"
        try:
            async with bot.transaction() as db:
                await db.execute(
                    "INSERT OR IGNORE INTO moderation_events "
                    "(interaction_id,guild_id,user_id,moderator_id,action,reason,duration_minutes,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (inter.id, inter.guild_id, target.id, inter.user.id, action, reason,
                     number if action == "mute" else None, int(time.time())),
                )
        except aiosqlite.Error as ex:
            print("Действие модерации не записано в историю:", inter.id, repr(ex))
            return await inter.followup.send(notice + "\nДействие выполнено. Сохранить статистику не удалось.",
                                             ephemeral=True, allowed_mentions=NO_MENTIONS)
        if action == "warn":
            try:
                await target.send(f"Предупреждение на сервере **{discord.utils.escape_markdown(guild.name)}**. "
                                  f"Причина — {journal_reason}", allowed_mentions=NO_MENTIONS)
            except discord.HTTPException:
                notice += " · личное сообщение недоступно"
        if inter.message is not None:
            member = target if action in ("warn", "mute", "unmute") else guild.get_member(target.id)
            if action in ("kick", "ban"):
                member = None
            try:
                await ModerationView(self.owner_id, member, subject_id=target.id).show(
                    inter, notice=notice, state="Мут до " + discord.utils.format_dt(deadline, "F") if deadline
                    else "Активного мута нет" if action == "unmute" else None)
                return
            except (discord.HTTPException, aiosqlite.Error) as ex:
                print("Панель модерации не обновлена:", inter.id, repr(ex))
        await inter.followup.send(notice, ephemeral=True, allowed_mentions=NO_MENTIONS)


async def moderation_history(guild_id, user_id):
    async with bot.db.execute(
        "SELECT action,COUNT(*) FROM moderation_events WHERE guild_id=? AND user_id=? GROUP BY action",
        (guild_id, user_id),
    ) as cur:
        counts = dict(await cur.fetchall())
    async with bot.db.execute(
        "SELECT action,reason,moderator_id,duration_minutes,created_at FROM moderation_events "
        "WHERE guild_id=? AND user_id=? ORDER BY interaction_id DESC LIMIT 3", (guild_id, user_id),
    ) as cur:
        return counts, await cur.fetchall()


class HistoryModal(discord.ui.Modal, title="История модерации по ID"):
    subject = discord.ui.TextInput(label="ID пользователя", min_length=15, max_length=20)

    def __init__(self, owner_id):
        super().__init__(timeout=120)
        self.owner_id = owner_id

    async def on_submit(self, inter: discord.Interaction):
        if inter.user.id != self.owner_id or not is_staff(inter.user) or inter.guild is None:
            return await inter.response.send_message("Панель недоступна.", ephemeral=True)
        value = self.subject.value.strip()
        if not value.isascii() or not value.isdecimal() or not 0 < int(value) <= MAX_MEMBER_ID:
            return await inter.response.send_message("Проверь ID пользователя.", ephemeral=True)
        subject_id = int(value)
        await ModerationView(self.owner_id, inter.guild.get_member(subject_id), subject_id=subject_id).show(inter)


class ModerationButton(discord.ui.Button):
    def __init__(self, action, open_action, *, disabled):
        label, _, emoji = ACTIONS[action]
        style = (discord.ButtonStyle.danger if action in ("kick", "ban") else
                 discord.ButtonStyle.primary if action == "mute" else discord.ButtonStyle.secondary)
        super().__init__(label=label, emoji=emoji, style=style, row=2, disabled=disabled)
        self.action = action
        self.open_action = open_action

    async def callback(self, inter: discord.Interaction):
        await self.open_action(inter, self.action)


class ModerationView(discord.ui.View):
    def __init__(self, owner_id, member=None, *, subject_id=None):
        super().__init__(timeout=900)
        self.owner_id, self.member = owner_id, member
        self.subject_id = member.id if member is not None else subject_id
        self.all_history.disabled = self.subject_id is None
        self.add_item(StaffSection(owner_id, member, "moderation"))
        for action in ("warn", "mute", "unmute", "kick", "ban"):
            self.add_item(ModerationButton(action, self.open_action, disabled=member is None))

    async def interaction_check(self, inter: discord.Interaction):
        if inter.user.id == self.owner_id and is_staff(inter.user):
            return True
        await inter.response.send_message("Панель недоступна.", ephemeral=True)
        return False

    async def show(self, inter: discord.Interaction, notice="", state=None):
        if not inter.response.is_done():
            await inter.response.defer()
        description = "Выбери участника или открой историю по ID."
        if self.subject_id is not None:
            if self.member is None:
                name = f"Пользователь `{self.subject_id}`"
            else:
                name = discord.utils.escape_markdown(self.member.display_name)
                if state is None:
                    until = self.member.timed_out_until
                    state = (f"Мут до {discord.utils.format_dt(until, 'F')}" if self.member.is_timed_out()
                             else "Активного мута нет")
            headline = f"**{name}**" + (f" · {state}" if state else "")
            counts, recent = await moderation_history(inter.guild_id, self.subject_id)
            lines = [headline, "", (
                f"**Муты:** {counts.get('mute', 0)} · **Кики:** {counts.get('kick', 0)} · "
                f"**Баны:** {counts.get('ban', 0)}"
            ), (f"**Снятия мута:** {counts.get('unmute', 0)} · **Разбаны:** {counts.get('unban', 0)}"),
                f"**Предупреждения:** {counts.get('warn', 0)}"]
            if recent:
                lines.extend(("", "**Последние действия**"))
                for action, reason, moderator, duration, created in recent:
                    label = ACTIONS[action][0] + (f" · {duration} мин" if duration else "")
                    reason = discord.utils.escape_markdown(discord.utils.escape_mentions(reason))
                    lines.append(f"<t:{created}:d> · **{label}** · <@{moderator}> — {reason}")
            else:
                lines.extend(("", "Записей пока нет."))
            lines.append("-# Статистика действий через Канцелярию с момента обновления.")
            description = "\n".join(lines)
        if notice:
            description += f"\n\n{notice}"
        embed = discord.Embed(title="Модерация", description=description, color=discord.Color.dark_red())
        banner = getattr(bot, "banners", {}).get("admin")
        file = discord.File(banner, filename="staff.jpg") if banner and os.path.isfile(banner) else None
        await edit_staff_page(inter, embed, file, self)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Выбери участника", row=1)
    async def pick(self, inter: discord.Interaction, select: discord.ui.UserSelect):
        member = select.values[0]
        if not isinstance(member, discord.Member):
            return await inter.response.send_message("Этот пользователь не на сервере.", ephemeral=True)
        await ModerationView(self.owner_id, member).show(inter)

    async def open_action(self, inter: discord.Interaction, action):
        problem = moderation_problem(inter.guild, inter.user, self.member, action)
        if problem:
            return await inter.response.send_message(problem, ephemeral=True)
        await inter.response.send_modal(ModerationModal(self.owner_id, self.member, action))

    @discord.ui.button(label="Разбан по ID", emoji="🔓", row=3)
    async def unban(self, inter: discord.Interaction, _):
        problem = moderation_problem(inter.guild, inter.user, None, "unban")
        if problem:
            return await inter.response.send_message(problem, ephemeral=True)
        await inter.response.send_modal(ModerationModal(self.owner_id, None, "unban"))

    @discord.ui.button(label="История по ID", emoji="📒", row=3)
    async def history(self, inter: discord.Interaction, _):
        await inter.response.send_modal(HistoryModal(self.owner_id))


    @discord.ui.button(label="Вся история", row=3)
    async def all_history(self, inter: discord.Interaction, _):
        await ModerationLogView(self.owner_id, self.member, subject_id=self.subject_id).show(inter)


class ModerationLogView(discord.ui.View):
    PAGE_SIZE = 7

    def __init__(self, owner_id, member=None, *, subject_id, category="all", page=0):
        super().__init__(timeout=900)
        self.owner_id, self.member, self.subject_id = owner_id, member, subject_id
        self.category = category if category in ACTIONS else "all"
        self.page = page
        self.filters.options = [discord.SelectOption(label="Все действия", value="all", default=category == "all")]
        self.filters.options += [
            discord.SelectOption(label=label, value=key, default=key == category)
            for key, (label, _, _) in ACTIONS.items()
        ]

    async def interaction_check(self, inter: discord.Interaction):
        return await ModerationView.interaction_check(self, inter)

    async def show(self, inter):
        if not inter.response.is_done():
            await inter.response.defer()
        params = (inter.guild_id, self.subject_id)
        where = "guild_id=? AND user_id=?"
        if self.category != "all":
            where += " AND action=?"
            params += (self.category,)
        async with bot.db.execute(
            "SELECT action,reason,moderator_id,duration_minutes,created_at FROM moderation_events "
            f"WHERE {where} ORDER BY interaction_id DESC LIMIT ? OFFSET ?",
            (*params, self.PAGE_SIZE + 1, self.page * self.PAGE_SIZE),
        ) as cur:
            events = await cur.fetchall()
        self.previous.disabled = self.page == 0
        self.next.disabled = len(events) <= self.PAGE_SIZE
        name = discord.utils.escape_markdown(self.member.display_name) if self.member else str(self.subject_id)
        lines = [f"**{name} · страница {self.page+1}**"]
        for action, reason, moderator, duration, date in events[:self.PAGE_SIZE]:
            label = ACTIONS[action][0] + (f" · {duration} мин" if duration else "")
            reason = discord.utils.escape_markdown(discord.utils.escape_mentions(reason))
            lines.append(f"<t:{date}:d> · **{label}** · <@{moderator}> — {reason}")
        if not events:
            lines.append("Записей нет.")
        await edit_staff_page(inter, discord.Embed(title="История модерации", description="\n".join(lines),
                                                   color=discord.Color.dark_red()), None, self)

    @discord.ui.select(placeholder="Фильтр действий", row=0, options=[
        discord.SelectOption(label="Все действия", value="all"),
    ])
    async def filters(self, inter: discord.Interaction, select: discord.ui.Select):
        await ModerationLogView(self.owner_id, self.member, subject_id=self.subject_id,
                                category=select.values[0]).show(inter)

    @discord.ui.button(label="Назад", row=1)
    async def previous(self, inter: discord.Interaction, _):
        await ModerationLogView(self.owner_id, self.member, subject_id=self.subject_id,
                                category=self.category, page=max(0, self.page-1)).show(inter)

    @discord.ui.button(label="Дальше", row=1)
    async def next(self, inter: discord.Interaction, _):
        await ModerationLogView(self.owner_id, self.member, subject_id=self.subject_id,
                                category=self.category, page=self.page+1).show(inter)

    @discord.ui.button(label="К участнику", row=1)
    async def back(self, inter: discord.Interaction, _):
        await ModerationView(self.owner_id, self.member, subject_id=self.subject_id).show(inter)
