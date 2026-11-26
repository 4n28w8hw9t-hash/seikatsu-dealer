"""New-member checklist started by accepting the court rules."""
import time

from .core import AFTER_ACTION, bot, embed, send_card

BADGE = "court:first_day"


async def start(guild_id, user_id):
    async with bot.transaction() as db:
        await db.execute("INSERT OR IGNORE INTO onboarding(guild_id,user_id,joined) VALUES(?,?,?)",
                         (guild_id, user_id, int(time.time())))


async def status(guild_id, user_id):
    async with bot.db.execute(
        "SELECT o.opened,o.awarded,u.path,COALESCE(u.last_daily,0)>=o.joined "
        "FROM onboarding o LEFT JOIN users u USING(guild_id,user_id) "
        "WHERE o.guild_id=? AND o.user_id=?", (guild_id, user_id)
    ) as cur:
        return await cur.fetchone()


async def open_profile(guild_id, user_id):
    row = await status(guild_id, user_id)
    if row and not row[0]:
        async with bot.transaction() as db:
            await db.execute("UPDATE onboarding SET opened=1 WHERE guild_id=? AND user_id=?",
                             (guild_id, user_id))


async def unlock(inter):
    if not inter.guild_id:
        return
    key = inter.guild_id, inter.user.id
    row = await status(*key)
    if row and row[0] and not row[1] and row[2] and row[3]:
        async with bot.transaction() as db:
            await db.execute("UPDATE onboarding SET awarded=1 WHERE guild_id=? AND user_id=?", key)


AFTER_ACTION.append(unlock)


async def show(inter):
    await unlock(inter)
    row = await status(inter.guild_id, inter.user.id)
    rows = []
    if row:
        opened, awarded, path, daily = row
        steps = (("Выбрать путь", path, "path"), ("Получить награду", daily, "daily"),
                 ("Открыть профиль", opened, "profile"))
        text = "\n".join(f"{'✅' if done else '◇'} {label}" for label, done, _ in steps)
        buttons = [key for _, done, key in steps if not done]
        if buttons:
            rows.append(buttons)
        text += ("\n\nЗначок «Первый день при дворе» доступен в Витрине." if awarded
                 else "\n\nЗа три шага — значок «Первый день при дворе».")
        if awarded:
            rows.append(["showcase"])
    else:
        text = "Первый день начинается после принятия устава."
    await send_card(inter, embed("Первый день при дворе", text), "welcome", rows=rows)
