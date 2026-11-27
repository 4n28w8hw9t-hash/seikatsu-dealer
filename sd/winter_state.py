"""Бал зимней луны 2026/27. Все изменения проходят в одной транзакции бота."""

from datetime import date, datetime, time, timedelta
from random import SystemRandom

from .core import bot
from .ledger import record
from .quests import COURT_TZ

START, REVEAL, END = date(2026, 12, 15), date(2027, 1, 1), date(2027, 1, 11)
BOSSES = ("Ледяной Страж", "Лунный Волк", "Крампус", "Королева Метели")
DATES = ("15–21 декабря", "22–28 декабря", "29 декабря – 4 января", "5–10 января")
GOALS = (60, 80, 100, 120)
TACTICS = (
    (("Расколоть щит", "Отразить выпад"), ("Страж укрылся за ледяным щитом.", "Страж занёс алебарду.")),
    (("Зажечь фонарь", "Сомкнуть строй"), ("Волк исчез в лунном тумане.", "Стая заходит с флангов.")),
    (
        ("Сбить бубенцы", "Разорвать путы"),
        ("Бубенцы Крампуса зовут подкрепление.", "Ледяные цепи опутали дозор."),
    ),
    (
        ("Рассеять метель", "Разбить зеркало"),
        ("Королева подняла снежный вихрь.", "Ледяное зеркало питает корону."),
    ),
)


def stance(day, idx):
    return ((day - START).days + idx) % 2


SIGILS = ("Печать Стража", "Лунный след", "Бубенец Крампуса", "Корона Метели")
SCHEMA = """
CREATE TABLE IF NOT EXISTS winter26_goals (g INTEGER,boss INTEGER,goal INTEGER, PRIMARY KEY(g,boss));
CREATE TABLE IF NOT EXISTS winter26_players (
 g INTEGER, u INTEGER, flakes INTEGER NOT NULL DEFAULT 0, night INTEGER DEFAULT 0,
 skin TEXT DEFAULT '', frame TEXT DEFAULT '', chest INTEGER DEFAULT 0, PRIMARY KEY(g,u));
CREATE TABLE IF NOT EXISTS winter26_raids (
 g INTEGER,u INTEGER,day TEXT,boss INTEGER,damage INTEGER, PRIMARY KEY(g,u,day));
CREATE INDEX IF NOT EXISTS winter26_boss ON winter26_raids(g,boss,u);
CREATE TABLE IF NOT EXISTS winter26_games (g INTEGER,u INTEGER,day TEXT, PRIMARY KEY(g,u,day));
CREATE TABLE IF NOT EXISTS winter26_pairs (
 g INTEGER,a INTEGER,b INTEGER,since INTEGER,day TEXT,u INTEGER, PRIMARY KEY(g,a,b,since,day,u));
CREATE TABLE IF NOT EXISTS winter26_rings (g INTEGER,u INTEGER, PRIMARY KEY(g,u));
CREATE TABLE IF NOT EXISTS winter26_gifts (g INTEGER,u INTEGER,recipient INTEGER, PRIMARY KEY(g,u));
"""


SCHEMA += """
CREATE TABLE IF NOT EXISTS snow_baskets(g INTEGER,u INTEGER,day TEXT,used INTEGER DEFAULT 0,last_target INTEGER DEFAULT -1,PRIMARY KEY(g,u,day));
CREATE TABLE IF NOT EXISTS snow_forts(g INTEGER,boss INTEGER,hits INTEGER DEFAULT 0,shooter INTEGER DEFAULT 0,mirrors INTEGER DEFAULT 0,volley INTEGER DEFAULT 0,PRIMARY KEY(g,boss));
CREATE TABLE IF NOT EXISTS snow_items(g INTEGER,u INTEGER,item TEXT,PRIMARY KEY(g,u,item));
CREATE TABLE IF NOT EXISTS snow_pairs(g INTEGER,a INTEGER,b INTEGER,since INTEGER,step INTEGER DEFAULT 0,PRIMARY KEY(g,a,b,since));
CREATE TABLE IF NOT EXISTS snow_duels(id INTEGER PRIMARY KEY,g INTEGER,a INTEGER,b INTEGER,phase TEXT,round INTEGER DEFAULT 1,ma INTEGER DEFAULT -1,mb INTEGER DEFAULT -1,sa INTEGER DEFAULT 0,sb INTEGER DEFAULT 0,report TEXT DEFAULT '',expires INTEGER);
CREATE INDEX IF NOT EXISTS snow_duel_guild ON snow_duels(g,phase,expires);
"""

def today():
    return datetime.now(COURT_TZ).date()


def stage(day):
    return (day - START).days // 7 if START <= day < END else None


async def rows(db, query, args):
    async with db.execute(query, args) as cur:
        return await cur.fetchall()


async def first(db, query, args, default=0):
    result = await rows(db, query, args)
    return result[0][0] if result else default


async def targets(db, g):
    goals = list(GOALS)
    for boss, goal in await rows(db, "SELECT boss,goal FROM winter26_goals WHERE g=?", (g,)):
        goals[boss] = goal
    return goals


async def open_chapter(db, g, idx):
    if await first(db, "SELECT 1 FROM winter26_goals WHERE g=? AND boss=?", (g, idx)):
        return
    start_day = START + timedelta(days=7 * idx)
    since = int(datetime.combine(start_day - timedelta(days=14), time.min, COURT_TZ).timestamp())
    until = int(datetime.combine(start_day, time.min, COURT_TZ).timestamp())
    active = await first(
        db,
        "SELECT COUNT(*) FROM users WHERE guild_id=? AND "
        "((last_daily>=? AND last_daily<?) OR (last_work>=? AND last_work<?))",
        (g, since, until, since, until),
    )
    goal = max(GOALS[idx], active * 3 * (10 + 5 * idx))
    await db.execute("INSERT OR IGNORE INTO winter26_goals VALUES(?,?,?)", (g, idx, goal))


async def progress(db, g, u):
    result = await rows(
        db,
        "SELECT boss,SUM(damage),SUM(CASE WHEN u=? THEN 1 ELSE 0 END) "
        "FROM winter26_raids WHERE g=? GROUP BY boss",
        (u, g),
    )
    totals, mine = [0] * 4, [0] * 4
    for idx, damage, count in result:
        totals[idx], mine[idx] = damage, count
    return totals, mine


async def cosmetics(db, g, u):
    result = await rows(db, "SELECT skin,frame FROM winter26_players WHERE g=? AND u=?", (g, u))
    return result[0] if result else ("", "")


async def pair_days(db, g, a, b, since):
    return await first(
        db,
        "SELECT COUNT(*) FROM (SELECT day FROM winter26_pairs WHERE "
        "g=? AND a=? AND b=? AND since=? GROUP BY day HAVING COUNT(*)=2)",
        (g, a, b, since),
    )


async def coin(db, g, u, amount, detail):
    await bot.ensure_user(db, g, u)
    await db.execute("UPDATE users SET balance=balance+? WHERE guild_id=? AND user_id=?", (amount, g, u))
    await record(db, g, u, amount, "winter", detail)


async def settle(db, g, day):
    if day < REVEAL:
        return
    entrants = [
        r[0] for r in await rows(db, "SELECT u FROM winter26_gifts WHERE g=? AND recipient IS NULL", (g,))
    ]
    SystemRandom().shuffle(entrants)
    for i, sender in enumerate(entrants):
        receiver = entrants[(i + 1) % len(entrants)]
        await db.execute("UPDATE winter26_gifts SET recipient=? WHERE g=? AND u=?", (receiver, g, sender))
        await coin(db, g, receiver, 500, "Тайный Санта" if sender != receiver else "Возврат подарка")
        await db.execute("UPDATE winter26_players SET flakes=flakes+50 WHERE g=? AND u=?", (g, receiver))


async def deliver_gifts():
    day = today()
    if day < REVEAL:
        return
    guilds = await rows(bot.db, "SELECT DISTINCT g FROM winter26_gifts WHERE recipient IS NULL", ())
    for (g,) in guilds:
        async with bot.transaction() as db:
            await settle(db, g, day)


async def act(db, g, u, key, day):
    await db.execute("INSERT OR IGNORE INTO winter26_players(g,u) VALUES(?,?)", (g, u))
    await settle(db, g, day)
    idx = stage(day)
    if idx is not None:
        await open_chapter(db, g, idx)
    goals = await targets(db, g)
    totals, mine = await progress(db, g, u)
    wins = sum(bool(n) and t >= goal for n, t, goal in zip(mine, totals, goals))
    active_only = key in ("strike", "counter", "offer", "pairday", "buy") or key.startswith("answer")
    if active_only and idx is None:
        return "Бал проходит с 15 декабря по 10 января по Москве."
    if key in ("strike", "counter"):
        technique = int(key == "counter")
        damage = (10, 15, 20, 25)[idx] + (5 if technique == stance(day, idx) else 0)
        cur = await db.execute(
            "INSERT OR IGNORE INTO winter26_raids VALUES(?,?,?,?,?)", (g, u, str(day), idx, damage)
        )
        if not cur.rowcount:
            return "Сегодня ты уже участвовал. Следующий выход в полночь по Москве."
        await db.execute("UPDATE winter26_players SET flakes=flakes+20 WHERE g=? AND u=?", (g, u))
        if totals[idx] < goals[idx] <= totals[idx] + damage:
            return f"Победа двора! Участники получили значок «{SIGILS[idx]}». Тебе +20 снежинок."
        return "+20 снежинок · " + (
            f"удар на {damage} урона." if totals[idx] < goals[idx] else "дозор завершён."
        )
    if key.startswith("answer"):
        cur = await db.execute("INSERT OR IGNORE INTO winter26_games VALUES(?,?,?)", (g, u, str(day)))
        if not cur.rowcount:
            return "Ты уже решил сегодняшнюю загадку."
        correct = key == "answer" + str(PUZZLES[(day - START).days % len(PUZZLES)][2])
        reward = 20 if correct else 5
        await db.execute("UPDATE winter26_players SET flakes=flakes+? WHERE g=? AND u=?", (reward, g, u))
        return ("Верно!" if correct else "Дух Метели дарит утешительный приз.") + f" +{reward} снежинок."
    if key == "offer":
        if day >= REVEAL:
            return "Подарки уже открыты."
        if await first(db, "SELECT 1 FROM winter26_gifts WHERE g=? AND u=?", (g, u)):
            return "Твой подарок уже под ёлкой."
        await bot.ensure_user(db, g, u)
        enough = await first(
            db,
            "SELECT 1 FROM users JOIN winter26_players ON guild_id=g AND user_id=u "
            "WHERE g=? AND u=? AND balance>=500 AND flakes>=50",
            (g, u),
        )
        if not enough:
            return "Для подарка нужно 500 монет и 50 снежинок."
        await coin(db, g, u, -500, "Подарок под ёлку")
        await db.execute("UPDATE winter26_players SET flakes=flakes-50 WHERE g=? AND u=?", (g, u))
        await db.execute("INSERT INTO winter26_gifts(g,u) VALUES(?,?)", (g, u))
        return "Камеристка спрятала твой подарок под ёлкой."
    if key == "pairday":
        mar = await rows(db, "SELECT a,b,since FROM marriages WHERE guild_id=? AND (a=? OR b=?)", (g, u, u))
        if not mar:
            return "Для парного поручения нужен брак при дворе."
        a, b, since = mar[0]
        await db.execute(
            "INSERT OR IGNORE INTO winter26_pairs VALUES(?,?,?,?,?,?)", (g, a, b, since, str(day), u)
        )
        days = await pair_days(db, g, a, b, since)
        if days >= 3:
            await db.executemany("INSERT OR IGNORE INTO winter26_rings VALUES(?,?)", [(g, a), (g, b)])
            return "Кольца Зимней луны украшают ваш парный профиль."
        return f"Твоя часть поручения выполнена. Совместных дней {days}/3."
    if key == "buy":
        cur = await db.execute(
            "UPDATE winter26_players SET night=1,flakes=flakes-80 WHERE g=? AND u=? AND night=0 AND flakes>=80",
            (g, u),
        )
        return (
            "Карточка «Северная ночь» теперь твоя."
            if cur.rowcount
            else "Карточка уже куплена или не хватает 80 снежинок."
        )
    if key in ("hall", "night", "classic", "frost", "crown", "bare"):
        night = await first(db, "SELECT night FROM winter26_players WHERE g=? AND u=?", (g, u))
        allowed = {
            "hall": sum(bool(n) for n in mine) >= 3,
            "night": bool(night),
            "classic": True,
            "frost": any(mine),
            "crown": wins == 4,
            "bare": True,
        }
        if not allowed[key]:
            return "Это оформление ещё предстоит заработать."
        column = "skin" if key in ("hall", "night", "classic") else "frame"
        await db.execute(
            f"UPDATE winter26_players SET {column}=? WHERE g=? AND u=?",
            ("" if key in ("classic", "bare") else key, g, u),
        )
        return "Оформление профиля сохранено."
    if key == "claim":
        if day < END and totals[3] < goals[3]:
            return "Сундук откроется после победы над Королевой или по окончании бала."
        if not any(mine):
            return "Сундук предназначен участникам хотя бы одной битвы."
        cur = await db.execute("UPDATE winter26_players SET chest=1 WHERE g=? AND u=? AND chest=0", (g, u))
        if not cur.rowcount:
            return "Ты уже получил финальный сундук."
        await coin(db, g, u, 1000, "Сундук Зимней луны")
        return "В сундуке 1 000 монет. Казначей зачислил их на баланс."
    return ""


PUZZLES = (
    ("На гербе ночи два рога, а в небе он один. Что это?", ("Месяц", "Олень", "Фонарь"), 0),
    ("Звенит на санях Крампуса, хотя у него нет голоса.", ("Снежинка", "Бубенец", "Ключ"), 1),
    ("Кто рисует на стекле серебром до рассвета?", ("Герольд", "Лунный Волк", "Мороз"), 2),
    ("Шесть лучей, ни одного огня. Что лежит на рукаве?", ("Снежинка", "Корона", "Звезда"), 0),
    ("У кого в лавке фонарь, сундук и сдача снежинками?", ("Хранитель", "Герольд", "Рыцарь"), 0),
    ("Кто держит список гостей и читает указы?", ("Камеристка", "Герольд", "Караульный"), 1),
    ("Пришёл без ног, завыл без горла, замёл следы во дворе.", ("Гонец", "Ворон", "Ветер"), 2),
    ("Сплю под снегом, весной звеню, летом бегу. Кто я?", ("Ручей", "Ветка", "Бубенец"), 0),
    ("Сколько острых концов у полумесяца на знамени?", ("Один", "Два", "Четыре"), 1),
    ("Что оставит Волк на снегу, перепрыгнув через ров?", ("Иней", "Печать", "След лапы"), 2),
    ("Какой узор у Духа Метели на шутовском камзоле?", ("Ромбы", "Полосы", "Розы"), 0),
    ("Кто хранит подарок и прикладывает палец к губам?", ("Принцесса", "Камеристка", "Герольд"), 1),
    ("Висит под крышей прозрачный клинок. Из чего он?", ("Хрусталь", "Стекло", "Лёд"), 2),
    ("Кто оставляет следы лап у ворот во второй главе бала?", ("Волк", "Олень", "Лис"), 0),
    ("Что отгоняет туман и не оставляет следа на снегу?", ("Цепь", "Свет фонаря", "Копыто"), 1),
    ("Какой металл дал имя венцу за четыре победы?", ("Медь", "Золото", "Серебро"), 2),
    ("Кого слышно по звону бубенцов ещё до его появления?", ("Крампуса", "Стража", "Королеву"), 0),
    ("К какому часу двор ждёт новую загадку по Москве?", ("К рассвету", "К полуночи", "К полудню"), 1),
    ("В какой день Камеристка раскрывает подарки?", ("31 декабря", "7 января", "1 января"), 2),
    (
        "Что остаётся у двух супругов после трёх совместных дней?",
        ("Парные кольца", "Один ключ", "Один венец"),
        0,
    ),
    ("Как называется карточка за три главы битв?", ("Иней", "Лунный зал", "Зимний караул"), 1),
    ("Какой предмет носит ледяной Страж для защиты?", ("Веер", "Бубенец", "Щит"), 2),
    ("Что разливается над тундрой зелёной лентой света?", ("Сияние", "Метель", "Туман"), 0),
    ("Какая рамка ждёт за первый выход в дозор?", ("Венец", "Иней", "Месяц"), 1),
    ("Кто поведёт последнюю метель к воротам дворца?", ("Лунный Волк", "Герольд", "Королева Метели"), 2),
    ("Что питает корону Королевы во второй боевой стойке?", ("Зеркало", "Бубенец", "Фонарь"), 0),
    ("Какой подарок под ёлкой скрывает имя дарителя?", ("Сундук двора", "Тайный Санта", "Парное кольцо"), 1),
)
