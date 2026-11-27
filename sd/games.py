"""Игры на монеты: монетка и дуэли."""
import os
import random

import discord
from discord import app_commands

from .core import ECON_LOCK, bot, button_emoji, card_name, embed, fmt, reply, send_card, send_public


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
        await bot.add(g, uid, ставка, reason="flip")
        await bot.add(g, uid, 1, "flip_wins")
        msg, col = f"Выпал **{result}** — ты забираешь **{fmt(ставка * 2)}**! 🎉", discord.Color.green()
        key = "coinflip"   # шут с монеткой — он же баннер победы
    else:
        await bot.add(g, uid, -ставка, reason="flip")
        msg, col = f"Выпал **{result}** — ставка **{fmt(ставка)}** сгорает 😢", discord.Color.red()
        key = "flip_lose"
    if key not in getattr(bot, "banners", {}):
        key = "lose" if "lose" in getattr(bot, "banners", {}) else "coinflip"
    await send_card(inter, embed("🪙 Монетка", msg, col), key, rows=[["coin", "balance"]])


# ═════════ Дуэли ═════════
class DuelView(discord.ui.View):
    def __init__(self, a: discord.Member, b: discord.Member | None, bet: int):
        super().__init__(timeout=60 if b else 120)
        self.a, self.b, self.bet = a, b, bet   # b = None — открытая дуэль, принять может любой
        self.open = b is None
        self.message = None
        self.accept.emoji = button_emoji("duel_accept", "⚔️")
        self.decline.emoji = button_emoji("duel_decline", "✖️")
        if self.open:
            self.decline.label = "Отменить"

    def card(self, text: str, color=discord.Color.gold()) -> discord.Embed:
        e = embed("⚔️ Дуэль", text, color)
        if "duel" in getattr(bot, "banners", {}):
            e.set_image(url=f"attachment://{card_name(bot.banners['duel'])}")
        return e

    async def _deny(self, inter: discord.Interaction, text: str):
        await inter.response.send_message(text, ephemeral=True)

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success)
    async def accept(self, inter: discord.Interaction, button: discord.ui.Button):
        if inter.user.id == self.a.id:
            return await self._deny(inter, "Нельзя принять свой же вызов")
        if not self.open and inter.user.id != self.b.id:
            return await self._deny(inter, "Это не твоя дуэль")
        if inter.user.bot:
            return
        await inter.response.defer()
        async with ECON_LOCK:
            if getattr(self, "done", False) or self.is_finished():
                return await inter.followup.send("Вызов уже закрыт", ephemeral=True)
            g = inter.guild_id
            challenger = await bot.get_user(g, self.a.id)
            opponent = await bot.get_user(g, inter.user.id)
            if self.open and challenger["balance"] >= self.bet and opponent["balance"] < self.bet:
                return await inter.followup.send(
                    f"Нужно **{fmt(self.bet)}**, у тебя **{fmt(opponent['balance'])}**", ephemeral=True)
            if getattr(self, "done", False) or self.is_finished():
                return await inter.followup.send("Вызов уже закрыт", ephemeral=True)
            win, lose = random.sample([self.a, inter.user], 2)
            self.done = True
            self.stop()
            settled = await bot.move_coins(g, lose.id, win.id, self.bet, duel=True)
        if not settled:
            return await inter.edit_original_response(view=None, embed=self.card(
                "Дуэль отменена: у кого-то не хватает монет в кошельке.",
                discord.Color.dark_grey()))
        e = self.card(f"🎉 {win.mention} побеждает и забирает **{fmt(self.bet * 2)}**!",
                      discord.Color.green())
        e2 = embed("⚔️ Дуэль", f"😢 {lose.mention} проигрывает **{fmt(self.bet)}**", discord.Color.red())
        files = []
        for key, em in (("win", e), ("lose", e2)):   # баннеры рыцаря: победа и поражение
            bn = getattr(bot, "banners", {})
            path = bn.get("duel_" + key) or bn.get(key)
            if path and os.path.exists(path):
                name = key + os.path.splitext(path)[1].lower()
                em.set_image(url=f"attachment://{name}")
                files.append(discord.File(path, filename=name))
            elif key == "win":
                em.set_image(url=None)
        await inter.edit_original_response(view=None, embeds=[e, e2], attachments=files)
        if self.bet >= 1000:   # крупные дуэли — в летопись
            from .chronicle import clog
            clog(inter.guild, "Дуэль", f"Дуэль на {self.bet * 2} монет",
                 f"⚔️ {win.mention} против {lose.mention}. Клинок сломан — победа за {win.mention}, "
                 f"выигрыш **{fmt(self.bet * 2)}**.", "duel_win")

    @discord.ui.button(label="Отказаться", style=discord.ButtonStyle.danger)
    async def decline(self, inter: discord.Interaction, button: discord.ui.Button):
        if getattr(self, "done", False):
            return
        uid = inter.user.id
        if uid == self.a.id:
            text = f"{self.a.mention} отменил вызов."
        elif not self.open and uid == self.b.id:
            text = f"{self.b.mention} отказался от дуэли с {self.a.mention}."
        else:
            return await self._deny(inter, "Отменить может только тот, кто вызвал" if self.open
                                    else "Это не твоя дуэль")
        self.done = True
        self.stop()
        await inter.response.edit_message(view=None, embed=self.card(text, discord.Color.dark_grey()))

    async def on_timeout(self):
        if self.message and not getattr(self, "done", False):
            try:
                text = (f"Никто не принял вызов {self.a.mention}." if self.open
                        else f"{self.b.mention} не ответил на вызов {self.a.mention}.")
                await self.message.edit(view=None, embed=self.card(text, discord.Color.dark_grey()))
            except discord.HTTPException:
                pass


@bot.tree.command(name="дуэль", description="Дуэль на монеты: вызвать участника или любого желающего")
@app_commands.describe(ставка="Сколько ставит каждый",
                       участник="Кого вызываешь (пусто — принять может любой)")
async def duel(inter: discord.Interaction, ставка: app_commands.Range[int, 10],
               участник: discord.Member | None = None):
    if участник and (участник.bot or участник.id == inter.user.id):
        return await reply(inter, "Так нельзя 🙃")
    me = await bot.get_user(inter.guild_id, inter.user.id)
    if me["balance"] < ставка:
        return await reply(inter, "Недостаточно монет в кошельке")
    if участник is None:   # открытый вызов
        view = DuelView(inter.user, None, ставка)
        view.message = await send_public(inter, view.card(
            f"{inter.user.mention} бросает вызов всем желающим!\n"
            f"Ставка: **{fmt(ставка)}** с каждого, победитель забирает всё.\n"
            "Жми «Принять», чтобы сразиться. Вызов действует 2 минуты."), "duel", view=view)
        return
    him = await bot.get_user(inter.guild_id, участник.id)
    if him["balance"] < ставка:
        return await reply(inter, "У соперника не хватает монет на такую ставку")
    view = DuelView(inter.user, участник, ставка)
    view.message = await send_public(inter, view.card(
        f"{inter.user.mention} вызывает {участник.mention} на дуэль!\n"
        f"Ставка: **{fmt(ставка)}** с каждого, победитель забирает всё.\n"
        "На ответ есть 60 секунд."), "duel", view=view, content=участник.mention)
