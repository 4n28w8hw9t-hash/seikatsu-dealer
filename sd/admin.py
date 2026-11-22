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
