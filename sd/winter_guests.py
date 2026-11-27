"""Личная история Бала зимней луны и мастерская ювелира."""

from . import snowballs as s
from . import winter_state as w

CHAPTERS = (
    ("Погасший фонарь", "У ворот погас старый путевой фонарь. В щите Стража блестит щепка серебра. "
     "Следопыт подносит огонь: тонкая трещина расползается от щепки к самому краю. Где её поддеть?",
     ("Под ободом", "В середине щита", "У рукояти"), 0,
     "Из-под обода выпадает серебряный рожок. На нём клеймо дворцовой мастерской."),
    ("След в сугробе", "За воротами волчьи следы расходятся. У сосны снег гладок, у моста припорошен, "
     "а над сугробом у колодца ещё клубится пар. Где искать второй осколок?",
     ("Под сосной", "У моста", "У колодца"), 2,
     "В тёплой лунке лежит дужка. Волк грел её лапой, пока серебро примерзало ко льду."),
    ("Тихий бубенец", "На санях Крампуса медь гудит, золото звенит, и лишь серебряный бубенец молчит. "
     "Следопыт просит найти, в каком застряла деталь фонаря.",
     ("В золотом", "В серебряном", "В медном"), 1,
     "Вместо язычка внутри качается звезда с острым краем. Ювелир узнаёт оправу лунного стекла."),
    ("Последнее отражение", "В зале Королевы три зеркала отражают один фонарь. В первом горит свеча, "
     "во втором мерцает звезда, а третье показывает пустую оправу. Куда вставить серебряную звезду?",
     ("В первое", "Во второе", "В третье"), 2,
     "За стеклом вспыхивает огонёк. У ворот снова светло. Теперь даже запоздалый гость найдёт дорогу на бал."),
)


async def journal(db, g, u, day, stamp):
    owned = await s.inventory(db, g, u)
    chapter = next((i for i in range(4) if f"shard{i}" not in owned), 4)
    stage = w.stage(day)
    active = stage is not None and chapter <= stage
    notice = ""
    if active and stamp:
        _, _, _, correct, ending = CHAPTERS[chapter]
        if stamp == f"{u}.{chapter}.{correct}":
            if await s.award(db, g, u, f"shard{chapter}"):
                await db.execute("UPDATE winter26_players SET flakes=flakes+10 WHERE g=? AND u=?", (g,u))
            notice = ending + " **+10 снежинок.**"
            chapter += 1
        elif stamp.startswith(f"{u}.{chapter}."):
            notice = "След ещё не найден. Перечитай наблюдение Следопыта и попробуй снова."
    lines = [f"**Журнал Агаты · Четыре осколка зимней луны · {chapter}/4**"]
    if notice:
        lines.append(notice)
    choices = []
    if chapter == 4:
        lines.append("Отнеси осколки ювелиру. В память о зажжённом фонаре она изготовит брошь для твоей витрины.")
    elif stage is not None and chapter <= stage:
        title, scene, choices, _, _ = CHAPTERS[chapter]
        lines.extend([f"**Глава {chapter+1} · {title}**", scene])
    elif day >= w.END:
        lines.append("Бал завершён. Найденные осколки остались в твоём журнале.")
    else:
        lines.append(f"Следующая глава · {w.DATES[chapter]}.")
    if chapter and not notice:
        lines.append("**Последняя запись** · " + CHAPTERS[chapter-1][4])
    return lines, chapter, choices


async def workshop(db, g, u, key, mar, has_rings, victory):
    items = await s.inventory(db,g,u)
    complete = all(f"shard{i}" in items for i in range(4))
    if key == "brooch" and complete:
        await s.award(db,g,u,"moon_brooch")
    engraved = False
    if mar and has_rings and complete and victory and key == "engrave":
        await db.execute("INSERT OR IGNORE INTO winter26_engraving VALUES(?,?,?,?)",(g,*mar))
    if mar:
        engraved = await w.first(db,"SELECT 1 FROM winter26_engraving WHERE g=? AND a=? AND b=? AND since=?",(g,*mar))
    lines = ["«Подойди к свету. Видишь зарубку на серебре? Так моя мать помечала всё, что выходило из нашей мастерской».",
             "Примерь рамку на своём аватаре или посмотри, как кольца смотрятся на карточке пары."]
    rows = [["wb:trylace","wb:itemrings"]]
    if complete:
        if key == "brooch" or "moon_brooch" in items:
            lines.append("**Брошь «Первая зимняя луна»** в коллекции. Её можно поставить на витрину профиля.")
            rows.append(["showcase"])
        else:
            lines.append("Все четыре осколка собраны. Ювелир готова вручить личную серебряную брошь.")
            rows.append(["wb:brooch"])
    else:
        lines.append("За четыре главы Следопыта ювелир изготовит **брошь для витрины**.")
    if engraved:
        lines.append("На кольцах вашей пары выгравировано «Первая зимняя луна».")
    elif mar and has_rings and complete and victory:
        rows.append(["wb:engrave"])
    else:
        lines.append("**Гравировка колец** открывается владельцам колец Зимней луны после четырёх глав и победы двора над Королевой Метели.")
    rows.append(["wb:journal","wb:store"])
    return lines, rows
