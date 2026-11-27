"""Состояние Снежной осады. Вызывается внутри транзакции экономики."""

import hashlib
import time

from . import winter_state as w

SHOP = {
    "lace": ("Морозное кружево", 60, "frame"),
    "yard": ("Заснеженный двор", 100, "skin"),
    "rings": ("Кольца Зимней луны", 160, "pair"),
    "aurora": ("Северное сияние", 180, "frame"),
}
TARGETS = (
    ("Левый край", "Гребень", "Правый край"),
    ("Левый сугроб", "Средний сугроб", "Правый сугроб"),
    ("Медный бубенец", "Серебряный", "Золотой"),
    ("Левое зеркало", "Среднее зеркало", "Правое зеркало"),
)
DIRECTIONS = ("слева", "в центре", "справа")


async def inventory(db, g, u):
    return {r[0] for r in await w.rows(db, "SELECT item FROM snow_items WHERE g=? AND u=?", (g, u))}


async def award(db, g, u, item):
    return (await db.execute("INSERT OR IGNORE INTO snow_items VALUES(?,?,?)", (g, u, item))).rowcount


async def couple(db, g, u):
    result = await w.rows(db, "SELECT a,b,since FROM marriages WHERE guild_id=? AND (a=? OR b=?)", (g, u, u))
    return result[0] if result else None


async def pair_step(db, g, mar):
    if not mar:
        return 0
    return await w.first(db, "SELECT step FROM snow_pairs WHERE g=? AND a=? AND b=? AND since=?", (g, *mar))


async def relay(db, g, u, day, stamp):
    mar = await couple(db, g, u)
    if not mar or w.stage(day) is None:
        return "Парный выход доступен супругам во время бала."
    step = await pair_step(db, g, mar)
    if stamp != f"{mar[2]}.{step}" or step >= 4:
        return "Поручение уже обновилось."
    if u != mar[(0, 1, 1, 0)[step]]:
        return "Сейчас ход твоей пары."
    await db.execute(
        "INSERT INTO snow_pairs VALUES(?,?,?,?,1) ON CONFLICT(g,a,b,since) DO UPDATE SET step=step+1",
        (g, *mar),
    )
    return "Оба сыграли обе роли! Комплект теперь стоит 120 снежинок." if step == 3 else "Манёвр выполнен."


async def purchase(db, g, u, key, day):
    if key not in SHOP or w.stage(day) is None:
        return "Лавка принимает снежинки в дни бала."
    name, price, kind = SHOP[key]
    mar = await couple(db, g, u)
    if kind == "pair":
        if not mar:
            return "Комплект выдаётся двум супругам."
        if (
            await w.first(db, "SELECT COUNT(*) FROM winter26_rings WHERE g=? AND u IN (?,?)", (g, *mar[:2]))
            == 2
        ):
            return "У вас уже есть оба кольца."
        if await pair_step(db, g, mar) >= 4:
            price = 120
    elif key in await inventory(db, g, u):
        return "Предмет уже в твоей коллекции."
    cur = await db.execute(
        "UPDATE winter26_players SET flakes=flakes-? WHERE g=? AND u=? AND flakes>=?", (price, g, u, price)
    )
    if not cur.rowcount:
        return f"Для покупки нужно {price} снежинок."
    if kind == "pair":
        await db.executemany("INSERT OR IGNORE INTO winter26_rings VALUES(?,?)", [(g, v) for v in mar[:2]])
    else:
        await award(db, g, u, key)
    return f"Покупка получена · {name}."


async def equip(db, g, u, key):
    if key not in await inventory(db, g, u) or key not in SHOP or SHOP[key][2] not in ("frame", "skin"):
        return "Сначала приобрети оформление в лавке."
    column = SHOP[key][2]
    await db.execute(f"UPDATE winter26_players SET {column}=? WHERE g=? AND u=?", (key, g, u))
    return "Оформление надето."


async def basket(db, g, u, day):
    result = await w.rows(
        db, "SELECT used,last_target FROM snow_baskets WHERE g=? AND u=? AND day=?", (g, u, str(day))
    )
    return result[0] if result else (-1, -1)


async def fort(db, g, idx):
    result = await w.rows(
        db, "SELECT hits,shooter,mirrors,volley FROM snow_forts WHERE g=? AND boss=?", (g, idx)
    )
    return result[0] if result else (0, 0, 0, 0)


def target(g, u, day, used):
    digest = hashlib.blake2s(f"{g}/{u}/{day}/{used}".encode()).digest()
    return digest[0] % 3


async def pack(db, g, u, day):
    if w.stage(day) is None:
        return "Караул выдаёт снег с 15 декабря по 10 января."
    cur = await db.execute("INSERT OR IGNORE INTO snow_baskets(g,u,day) VALUES(?,?,?)", (g, u, str(day)))
    return "В корзинке пять свежих снежков." if cur.rowcount else "Ты уже слепил сегодняшнюю корзинку."


async def throw(db, g, u, day, choice, stamp):
    idx = w.stage(day)
    used, _ = await basket(db, g, u, day)
    if idx is None or used not in range(5) or stamp != f"{day}.{u}.{used}":
        return "Обнови осаду и проверь запас снежков."
    hits, previous, mirrors, volley = await fort(db, g, idx)
    correct = choice == target(g, u, day, used)
    now = int(time.time())
    bonus = ""
    if idx == 0 and hits and hits % 3 == 0 and previous != u:
        correct = True
        bonus = " Удар через брешь!"
    if idx == 3:
        correct = volley > now or not (mirrors & (1 << choice))
        if correct and volley <= now:
            mirrors |= 1 << choice
            if mirrors == 7:
                volley = now + 3600
                mirrors = 0
                bonus = " На час открыт общий залп по Королеве!"
    damage = (3 + idx) * int(correct)
    reward = 5 + 3 * int(correct)
    hits += int(correct)
    await db.execute(
        "UPDATE snow_baskets SET used=used+1,last_target=? WHERE g=? AND u=? AND day=?",
        (choice, g, u, str(day)),
    )
    await db.execute(
        "INSERT INTO snow_forts VALUES(?,?,?,?,?,?) ON CONFLICT(g,boss) DO UPDATE SET hits=excluded.hits,shooter=excluded.shooter,mirrors=excluded.mirrors,volley=excluded.volley",
        (g, idx, hits, u if correct else previous, mirrors, volley),
    )
    await db.execute(
        "INSERT INTO winter26_raids VALUES(?,?,?,?,?) ON CONFLICT(g,u,day) DO UPDATE SET damage=damage+excluded.damage",
        (g, u, str(day), idx, damage),
    )
    await db.execute("UPDATE winter26_players SET flakes=flakes+? WHERE g=? AND u=?", (reward, g, u))
    await award(db, g, u, "snowball")
    if idx == 2 and correct and hits % 3 == 0:
        await db.execute(
            "UPDATE winter26_players SET flakes=flakes+3 WHERE g=? AND u IN (SELECT u FROM winter26_raids WHERE g=? AND boss=2)",
            (g, g),
        )
        bonus = " Подарок спасён! Всем участникам этой главы ещё по 3 снежинки."
    return (
        ("Попадание!" if correct else "Снежок прошёл мимо.") + f" +{reward} снежинок. Урон {damage}." + bonus
    )


async def princess(db, g, u, day):
    if not w.REVEAL <= day < w.END:
        return "Принцесса вручает подарок с 1 по 10 января."
    if not await award(db, g, u, "princess"):
        return "Ты уже распаковал подарок."
    await w.coin(db, g, u, 250, "Новогодний дар Принцессы")
    await db.execute("UPDATE winter26_players SET flakes=flakes+25 WHERE g=? AND u=?", (g, u))
    return "Под лентой — 250 монет, 25 снежинок и праздничный знак!"


async def duel(db, g, u, latest=False):
    phase = "" if latest else "AND phase IN ('invite','play') AND expires>?"
    return next(
        iter(
            await w.rows(
                db,
                f"SELECT id,a,b,phase,round,ma,mb,sa,sb,report FROM snow_duels WHERE g=? AND (a=? OR b=?) {phase} ORDER BY id DESC LIMIT 1",
                (g, u, u) if latest else (g, u, u, int(time.time())),
            )
        ),
        None,
    )


async def invite(db, g, u, v, day):
    if w.stage(day) is None or u == v:
        return "Выбери другого игрока во время бала."
    if await duel(db, g, u) or await duel(db, g, v):
        return "Один из вас уже участвует в поединке."
    await db.execute(
        "INSERT INTO snow_duels(g,a,b,phase,expires) VALUES(?,?,?,'invite',?)",
        (g, u, v, int(time.time()) + 900),
    )
    return f"<@{v}>, тебя вызывают в снежки! Прими вызов в течение 15 минут."


async def duel_move(db, g, u, key, stamp, move, day):
    match = await duel(db, g, u)
    if not match or w.stage(day) is None:
        return "Этот поединок завершён."
    ident, a, b, phase, turn, ma, mb, sa, sb, _ = match
    if stamp != f"{ident}.{turn}":
        return "Этот раунд уже закрыт."
    if key == "cancel":
        await db.execute("UPDATE snow_duels SET phase='closed' WHERE id=?", (ident,))
        return "Поединок закрыт."
    if key == "accept" and u == b and phase == "invite":
        await db.execute(
            "UPDATE snow_duels SET phase='play',expires=? WHERE id=?", (int(time.time()) + 900, ident)
        )
        return "Дуэль началась!"
    if key != "move" or phase != "play" or move not in range(9):
        return "Сейчас это действие недоступно."
    if (ma if u == a else mb) >= 0:
        return "Твой ход уже принят."
    if u == a:
        ma = move
    else:
        mb = move
    report = ""
    if ma >= 0 and mb >= 0:
        ha = ma // 3 == mb % 3
        hb = mb // 3 == ma % 3
        sa += int(ha)
        sb += int(hb)
        report = f"Раунд {turn} · <@{a}> {'попал' if ha else 'промахнулся'} · <@{b}> {'попал' if hb else 'промахнулся'}."
        turn += 1
        phase = "done" if turn == 4 else "play"
        ma = mb = -1
    await db.execute(
        "UPDATE snow_duels SET phase=?,round=?,ma=?,mb=?,sa=?,sb=?,report=CASE WHEN ?='' THEN report ELSE ? END,expires=? WHERE id=?",
        (phase, turn, ma, mb, sa, sb, report, report, int(time.time()) + 900, ident),
    )
    return report or "Ход запечатан. Соперник увидит результат, когда оба сделают выбор."
