"""Privileged Discord moderation actions for the staff panel."""
from datetime import timedelta

import discord

from .admin import StaffSection, is_staff, log

ACTIONS = {
    "mute": ("Мут", "moderate_members", "🔇"),
    "unmute": ("Снять мут", "moderate_members", "🔊"),
    "kick": ("Кик", "kick_members", "🚪"),
    "ban": ("Бан", "ban_members", "⛔"),
    "unban": ("Разбан", "ban_members", "🔓"),
}
MAX_TIMEOUT_MINUTES = 28 * 24 * 60
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
        await inter.response.defer(ephemeral=True, thinking=True)
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
        if action == "unban" and not 0 < number < 2 ** 64:
            return await inter.followup.send("Проверь ID пользователя.", ephemeral=True)

        guild = inter.guild
        reason = " ".join(self.reason.value.split())
        if not reason:
            return await inter.followup.send("Укажи причину.", ephemeral=True)
        audit_reason = f"{inter.user.id} · {reason}"
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
                    await target.timeout(timedelta(minutes=number), reason=audit_reason)
                elif action == "unmute":
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
        audit_target = guild.get_member(target.id) or target
        log(inter, audit_target, f"{label}{duration}. Причина — {reason}")
        await inter.followup.send(f"**{label}**{duration} · <@{target.id}>\nПричина — {discord.utils.escape_markdown(reason)}",
                                  ephemeral=True, allowed_mentions=NO_MENTIONS)


class ModerationView(discord.ui.View):
    def __init__(self, owner_id, member=None):
        super().__init__(timeout=900)
        self.owner_id, self.member = owner_id, member
        self.add_item(StaffSection(owner_id, member, "moderation"))
        if member is None:
            self.remove_item(self.actions)

    async def interaction_check(self, inter: discord.Interaction):
        if inter.user.id == self.owner_id and is_staff(inter.user):
            return True
        await inter.response.send_message("Панель недоступна.", ephemeral=True)
        return False

    async def show(self, inter: discord.Interaction):
        if not inter.response.is_done():
            await inter.response.defer()
        description = "Выбери участника для мута, кика или бана. Для разбана понадобится ID."
        if self.member is not None:
            name = discord.utils.escape_markdown(self.member.display_name)
            until = self.member.timed_out_until
            state = f"Мут до {discord.utils.format_dt(until, 'F')}" if self.member.is_timed_out() else "Мут отсутствует"
            description = f"**{name}** · {state}"
        embed = discord.Embed(title="Модерация", description=description, color=discord.Color.dark_red())
        await inter.edit_original_response(embed=embed, attachments=[], view=self)

    @discord.ui.select(cls=discord.ui.UserSelect, placeholder="Выбери участника", row=0)
    async def pick(self, inter: discord.Interaction, select: discord.ui.UserSelect):
        member = select.values[0]
        if not isinstance(member, discord.Member):
            return await inter.response.send_message("Этот пользователь не на сервере.", ephemeral=True)
        await ModerationView(self.owner_id, member).show(inter)

    @discord.ui.select(placeholder="Действие модерации", row=1, options=[
        discord.SelectOption(label=label, value=action, emoji=emoji)
        for action, (label, _, emoji) in ACTIONS.items() if action != "unban"
    ])
    async def actions(self, inter: discord.Interaction, select: discord.ui.Select):
        action = select.values[0]
        problem = moderation_problem(inter.guild, inter.user, self.member, action)
        if problem:
            return await inter.response.send_message(problem, ephemeral=True)
        await inter.response.send_modal(ModerationModal(self.owner_id, self.member, action))

    @discord.ui.button(label="Разбан по ID", emoji="🔓", row=2)
    async def unban(self, inter: discord.Interaction, _):
        problem = moderation_problem(inter.guild, inter.user, None, "unban")
        if problem:
            return await inter.response.send_message(problem, ephemeral=True)
        await inter.response.send_modal(ModerationModal(self.owner_id, None, "unban"))
