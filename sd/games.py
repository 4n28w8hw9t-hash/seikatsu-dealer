"""Игры на монеты: монетка и дуэли."""
import os
import random

import discord
from discord import app_commands

from .core import bot, card_name, embed, fmt, reply, send_card, send_public


# ═════════ Монетка ═════════
@bot.tree.command(name="монетка", description="Орёл или решка: угадал — x2, нет — ставка сгорает")
@app_commands.describe(ставка="Сколько ставишь", выбор="Орёл или решка")
@app_commands.choices(выбор=[app_commands.Choice(name="Орёл", value="орёл"),
                             app_commands.Choice(name="Решка", value="решка")])
async def coinflip(inter: discord.Interaction, ставка: app_commands.Range[int, 10],
                   выбор: app_commands.Choice[str]):
    g, uid = inter.guild_id, inter.user.id
    u = await bot.get_user(g, uid)
    if u["balance"] < ставка:
        return await reply(inter, "Недостаточно монет для ставки", rows=[["balance", "daily"]])
    result = random.choice(["орёл", "решка"])
    if result == выбор.value:
        await bot.add(g, uid, ставка)
        await bot.add(g, uid, 1, "flip_wins")
        msg, col = f"Выпал **{result}** — ты забираешь **{fmt(ставка * 2)}**! 🎉", discord.Color.green()
        key = "win"
    else:
        await bot.add(g, uid, -ставка)
        msg, col = f"Выпал **{result}** — ставка **{fmt(ставка)}** сгорает 😢", discord.Color.red()
        key = "lose"
    if key not in getattr(bot, "banners", {}):
        key = "coinflip"
    await send_card(inter, embed("🪙 Монетка", msg, col), key, rows=[["coin", "balance"]])


# ═════════ Дуэли ═════════
class DuelView(discord.ui.View):
    def __init__(self, a: discord.Member, b: discord.Member, bet: int):
        super().__init__(timeout=60)
        self.a, self.b, self.bet = a, b, bet
        self.message = None

    def card(self, text: str, color=discord.Color.gold()) -> discord.Embed:
        e = embed("⚔️ Дуэль", text, color)
        if "duel" in getattr(bot, "banners", {}):
            e.set_image(url=f"attachment://{card_name(bot.banners['duel'])}")
        return e

    async def interaction_check(self, inter: discord.Interaction) -> bool:
        if inter.user.id != self.b.id:
            await inter.response.send_message("Это не твоя дуэль", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success)
    async def accept(self, inter: discord.Interaction, button: discord.ui.Button):
        if getattr(self, "done", False):  # защита от двойного нажатия
            return
        self.done = True
        self.stop()
        g = inter.guild_id
        ua, ub = await bot.get_user(g, self.a.id), await bot.get_user(g, self.b.id)
        if ua["balance"] < self.bet or ub["balance"] < self.bet:
            return await inter.response.edit_message(view=None, embed=self.card(
                "Дуэль отменена: у кого-то не хватает монет в кошельке.",
                discord.Color.dark_grey()))
        win, lose = random.sample([self.a, self.b], 2)
        await bot.add(g, lose.id, -self.bet)
        await bot.add(g, win.id, self.bet)
        await bot.add(g, win.id, 1, "duel_wins")
        e = self.card(f"🎉 {win.mention} побеждает и забирает **{fmt(self.bet * 2)}**!",
                      discord.Color.green())
        e2 = embed("⚔️ Дуэль", f"😢 {lose.mention} проигрывает **{fmt(self.bet)}**", discord.Color.red())
        files = []
        for key, em in (("win", e), ("lose", e2)):   # баннер победы и баннер поражения
            path = getattr(bot, "banners", {}).get(key)
            if path and os.path.exists(path):
                name = key + os.path.splitext(path)[1].lower()
                em.set_image(url=f"attachment://{name}")
                files.append(discord.File(path, filename=name))
            elif key == "win":
                em.set_image(url=None)
        await inter.response.edit_message(view=None, embeds=[e, e2], attachments=files)

    @discord.ui.button(label="Отказаться", style=discord.ButtonStyle.danger)
    async def decline(self, inter: discord.Interaction, button: discord.ui.Button):
        self.stop()
        await inter.response.edit_message(view=None, embed=self.card(
            f"{self.b.mention} отказался от дуэли с {self.a.mention}.",
            discord.Color.dark_grey()))

    async def on_timeout(self):
        if self.message:
            try:
                await self.message.edit(view=None, embed=self.card(
                    f"{self.b.mention} не ответил на вызов {self.a.mention}.",
                    discord.Color.dark_grey()))
            except discord.HTTPException:
                pass


@bot.tree.command(name="дуэль", description="Вызвать участника на дуэль на монеты")
@app_commands.describe(участник="Кого вызываешь", ставка="Сколько ставит каждый")
async def duel(inter: discord.Interaction, участник: discord.Member,
               ставка: app_commands.Range[int, 10]):
    if участник.bot or участник.id == inter.user.id:
        return await reply(inter, "Так нельзя 🙃")
    me = await bot.get_user(inter.guild_id, inter.user.id)
    if me["balance"] < ставка:
        return await reply(inter, "Недостаточно монет в кошельке")
    him = await bot.get_user(inter.guild_id, участник.id)
    if him["balance"] < ставка:
        return await reply(inter, "У соперника не хватает монет на такую ставку")
    view = DuelView(inter.user, участник, ставка)
    view.message = await send_public(inter, view.card(
        f"{inter.user.mention} вызывает {участник.mention} на дуэль!\n"
        f"Ставка: **{fmt(ставка)}** с каждого, победитель забирает всё.\n"
        "На ответ есть 60 секунд."), "duel", view=view, content=участник.mention)
