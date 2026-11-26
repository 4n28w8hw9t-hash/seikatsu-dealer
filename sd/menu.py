"""Меню, помощь и обработка всех кнопок."""
import os
import time

import discord
from discord import app_commands

from .core import wrong_channel, E, card_name, BUTTONS, DAILY_REWARD, after_action, ECON_LOCK, RED, bot, fmt, reply, send_card, too_fast
from .core import btn, button_icon, fmt_time, member_name, send_panel, _OK, _G
from .achievements import ACHIEVEMENTS, achievements, get_stats
from .economy import DAY, balance, daily, profile
from .games import coinflip, duel
from .levels import PATHS, RANK_STEP, WORK_COOLDOWN, get_path, is_female, next_rank, rank_of, work_pay, xp_for
from . import events, ledger, market, marriage, onboarding, pair_quests, quests, reminders, showcase, top
from .paths import choose_path, pick_path, work
from .marriage import buy_ring, couple, divorce, divorce_confirm, love_room, rings_shop


# ═════════ Помощь ═════════
@bot.tree.command(name="помощь", description="Что умеет Seikatsu Court")
async def help_cmd(inter: discord.Interaction):
    e = discord.Embed(
        title="Seikatsu Court",
        description=("Принцесса двора **Seikatsu** и хранительница казны.\n"
                     "Всё делается кнопками."),
        color=RED,
    )
    e.add_field(name=f"{E('sd_gift', '🎁')} Монеты", inline=False,
                value=f"`/награда` — {DAILY_REWARD} монет раз в 24 часа\n"
                      "`/баланс` — сколько у тебя монет\n"
                      "`/перевод @участник сумма` — отправить монеты другому")
    e.add_field(name=f"{E('sd_flip', '🎲')} Игры", inline=False,
                value="`/монетка` — угадал сторону: x2, нет — ставка сгорает\n"
                      "`/дуэль ставка [@участник]` — ставка с каждого, победитель забирает всё; без участника принять может любой")
    e.add_field(name=f"{E('sd_profile', '👤')} Профиль", inline=False,
                value="`/путь` — знать или вера: от пути и уровня зависит титул\n"
                      "`/работа` — жалованье по титулу раз в 12 часов\n"
                      "`/профиль` — титул, уровень, опыт, баланс, пара, достижения\n"
                      "`/достижения` — все достижения с редкостью и наградами\n"
                      "`/топ` — лучшие при дворе по уровню и по монетам\n"
                      "Опыт идёт за сообщения и время в голосовых.")
    e.add_field(name=f"{E('sd_ring', '💍')} Брак", inline=False,
                value="`/кольца` — купить кольцо · `/брак @участник` — предложение\n"
                      "`/пара` — парный профиль и лав-рума · `/развод`\n"
                      f"`/название_румы` — своё название лав-румы за {fmt(marriage.ROOM_RENAME_PRICE)}")
    e.add_field(name=f"{E('sd_inv', '🎭')} Роли", inline=False,
                value=f"`/создать_роль` — своя роль за {market.ROLE_CREATE_PRICE:,} монет ".replace(",", " ")
                      + f"(до {market.ROLE_LIMIT} штук)\n"
                      "`/инвентарь` — сколько у тебя ролей и колец\n"
                      "`/роли` — надеть, снять, выставить на продажу\n"
                      f"`/магазин` — купить роль; создатель получает {round(market.SELLER_SHARE * 100)}% с продажи")
    e.set_footer(text="Админам: /эко — управление монетами")
    await send_card(inter, e, "help")


# ═════════ Меню ═════════
MENU_ROWS = [
    "---", "### {sd_profile} Профиль", ["profile", "path", "work", "ach", "top"],
    "---", "### {sd_coin} Монеты", ["balance", "daily", "coin"],
    "---", "### {sd_couple} Пара", ["couple", "rings", "loveroom"],
    "---", "### {sd_inv} Роли", ["inventory", "market", "roles", "rolecreate"],
    "---", ["help"],
]
# окно с вводом: (заголовок, подпись поля, подсказка)
MENU_MODALS = {"coin": ("Монетка", "Ставка", "например 100"),
               "duel": ("Открытая дуэль", "Ставка с каждого", "например 100")}

# выпадающий список «Все разделы»: (ключ, подпись, пояснение)
SECTIONS = [
    ("profile", "Профиль", "Твой уровень, титул и место в топе"),
    ("inventory", "Инвентарь", "Твои роли и кольца"),
    ("quests", "Поручения двора", "Еженедельные задания и награда"),
    ("event", "Событие двора", "Общая цель и памятный знак"),
    ("onboarding", "Первый день при дворе", "Список для новых участников"),
    ("season:archive", "Архив сезонов", "Итоги прошлых месяцев"),
    ("history", "История монет", "Личная выписка из Казны"),
    ("path", "Путь и титул", "Знать или Вера, следующее звание"),
    ("top", "Топ двора", "Лучшие по уровню и по монетам"),
    ("ach", "Достижения", "Награды за успехи"),
    ("coin", "Монетка", "Орёл или решка, выигрыш x2"),
    ("duel", "Дуэль", "Открытый вызов — принять может любой"),
    ("couple", "Пара", "Карточка пары, лав-рума, название"),
    ("rings", "Магазин колец", "Посмотреть и купить кольца"),
    ("loveroom", "Лав-рума", "Открыть комнату для двоих"),
    ("market", "Рынок ролей", "Роли, созданные игроками"),
    ("roles", "Мои роли", "Надеть, снять, продать"),
    ("rolecreate", "Создать роль", "Своя роль за 10 000"),
    ("help", "Помощь", "Все команды"),
]


def short_time(sec: int) -> str:
    h, m = divmod(max(0, int(sec)) // 60, 60)
    return f"{h}ч" if h else f"{max(1, m)}м"


def sections_select() -> discord.ui.Select:
    opts = []
    for key, label, desc in SECTIONS:
        icon = BUTTONS[key][2] if key in BUTTONS else ""
        emo = button_icon(icon)
        try:
            emo = discord.PartialEmoji.from_str(emo) if emo else None
        except Exception:
            emo = None
        opts.append(discord.SelectOption(label=label, value=key, description=desc, emoji=emo))
    return discord.ui.Select(custom_id="sd:sections", placeholder="Все разделы двора…", options=opts)


async def dashboard(inter: discord.Interaction):
    """Личное меню: сводка картинкой, быстрые кнопки с таймерами и список разделов."""
    g, m = inter.guild_id, inter.user
    s = await get_stats(g, m.id)
    u = await bot.get_user(g, m.id)
    now = int(time.time())
    lvl, fem = s["level"], is_female(m)
    path = await get_path(g, m.id)
    if path:
        sub = f"{rank_of(lvl, path, fem)} · {PATHS[path][1]} · {lvl} уровень"
        nxt = next_rank(lvl, path, fem)
        if nxt:
            bar = ((lvl - (nxt[0] - RANK_STEP)) / RANK_STEP, f"До звания «{nxt[1]}»", f"{lvl} / {nxt[0]} ур.")
        else:
            bar = (1.0, "Высшее звание двора", f"{lvl} ур.")
    else:
        sub = f"Путь не выбран · {lvl} уровень"
        have, need = s["xp"] - xp_for(lvl), xp_for(lvl + 1) - xp_for(lvl)
        bar = (have / max(1, need), f"Опыт до {lvl + 1} уровня", f"{have} / {need}")
    d_left = u["last_daily"] + DAY - now
    w_left = u["last_work"] + WORK_COOLDOWN - now
    tiles = [("coin", "Кошелёк", f"{s['coins']:,}".replace(",", " "), "монет", False)]
    tiles.append(("gift", "Награда", "Готово", "забери сейчас", True) if d_left <= 0
                 else ("gift", "Награда", fmt_time(d_left).replace(" мин", " м"), "до награды", False))
    if not path:
        tiles.append(("work", "Служба", "—", "сначала выбери путь", False))
    elif w_left <= 0:
        tiles.append(("work", "Служба", "Готово", f"жалованье {work_pay(lvl)}", True))
    else:
        tiles.append(("work", "Служба", fmt_time(w_left).replace(" мин", " м"),
                      f"жалованье {work_pay(lvl)}", False))
    mar = s["marriage"]
    if mar:
        other = mar["b"] if mar["a"] == m.id else mar["a"]
        days = max(0, (now - (mar["since"] or now)) // 86400)
        lines = [("couple", f"Пара: {await member_name(inter.guild, other)} · вместе {days} дн.")]
    else:
        lines = [("ring", "Пары пока нет — кольцо можно купить в разделе «Кольца»")]
    todo = [(s.get(stat, 0) / need, name, s.get(stat, 0), need)
            for k, name, _, _, stat, need in ACHIEVEMENTS if k not in s["ach"]]
    ach = f"Достижения {len(s['ach'])} из {len(ACHIEVEMENTS)}"
    if todo:
        _, name, cur, need = max(todo)
        ach += f" · ближайшее «{name}» {min(cur, need):,} / {need:,}".replace(",", " ")
    lines.append(("trophy", ach))
    quick = [btn("daily", "Награда" if d_left <= 0 else f"Награда · {short_time(d_left)}",
                 _OK if d_left <= 0 else _G),
             btn("work", "Работа" if (path and w_left <= 0) else
                 ("Работа" if not path else f"Работа · {short_time(w_left)}"),
                 _OK if (path and w_left <= 0) else _G),
             btn("profile"), btn("inventory"), btn("balance")]
    week, _ = quests.week_window(now)
    counts = await quests.progress(bot.db, g, m.id, week)
    done = quests.completed_count(counts, quests.goals_for_week(week))
    if done == 3 and not counts[3]:
        quest_button = btn("quests:claim", "Забрать награду за поручения")
    else:
        quest_button = btn("quests", "Поручения · " + ("получено" if counts[3] else f"{done}/3"))
    shortcuts = [*quick[3:], quest_button, "event"]
    first_day = await onboarding.status(g, m.id)
    if first_day and not first_day[1]:
        shortcuts.append("onboarding")
    await send_panel(inter, "menu", f"Покои · {m.display_name}", subtitle=sub, icon="profile",
                     bar=bar, tiles=tiles, lines=lines, rows=[quick[:3], shortcuts, [sections_select()]], nav=False)


async def menu_action(key: str, inter: discord.Interaction, n: int = 0, side: str = ""):
    if key == "menu":
        await dashboard(inter)
    elif key == "profile":
        await profile.callback(inter, None)
    elif key == "work":
        await work.callback(inter)
    elif key == "path":
        await choose_path.callback(inter)
    elif key.startswith("path:"):
        await pick_path(inter, key[5:])
    elif key == "ach":
        await achievements.callback(inter, None)
    elif key in ("top", "top:lvl"):
        await top.show_top(inter, "lvl")
    elif key in ("top:coin", "top:season"):
        await top.show_top(inter, key.split(":")[1])
    elif key == "balance":
        await balance.callback(inter, None)
    elif key == "daily":
        await daily.callback(inter)
    elif key == "showcase":
        await showcase.show(inter)
    elif key == "showcase:save":
        await showcase.save(inter, (inter.data or {}).get("values") or [])
    elif key in ("showcase:toggle", "showcase:more"):
        await showcase.save(inter, toggle=side)
    elif key == "showcase:clear":
        await showcase.save(inter, [])
    elif key == "help":
        await help_cmd.callback(inter)
    elif key == "couple":
        await couple.callback(inter, None)
    elif key == "anniversary":
        await marriage.anniversary(inter)
    elif key == "anniversary:celebrate":
        await marriage.anniversary(inter, celebrate=True)
    elif key == "anniversary:pick":
        milestone = next((target for target in marriage.ANNIVERSARIES if side == str(target)), None)
        await marriage.anniversary(inter, celebrate=milestone is not None, milestone=milestone)
    elif key == "quests":
        await quests.show(inter)
    elif key == "quests:reminder":
        await reminders.toggle(inter)
    elif key == "onboarding":
        await onboarding.show(inter)
    elif key == "event":
        await events.show(inter)
    elif key == "event:claim":
        await events.claim(inter)
    elif key == "season:archive" or key.startswith("season:archive:"):
        await top.show_archive(inter, key.removeprefix("season:archive").lstrip(":") or side)
    elif key == "quests:claim":
        await quests.claim(inter)
    elif key == "pairquest":
        await pair_quests.show(inter)
    elif key == "pairquest:claim":
        await pair_quests.claim(inter)
    elif key == "rings":
        await rings_shop.callback(inter)
    elif key == "ringbook":
        await marriage.show_ring_collection(inter)
    elif key == "ringbook:action":
        await marriage.ring_action(inter, side)
    elif key == "ringbook:giftselect":
        await marriage.ring_action(inter, side)
    elif key == "ringgift":
        await marriage.choose_gift_ring(inter)
    elif key.startswith("ring:"):
        await buy_ring(inter, key[5:])
    elif key == "loveroom":
        await love_room(inter)
    elif key == "divorce":
        await divorce.callback(inter)
    elif key == "divorce:yes":
        await divorce_confirm(inter)
    elif key == "market":
        await market.market.callback(inter)
    elif key == "roles":
        await market.my_roles.callback(inter)
    elif key == "inventory":
        await market.inventory.callback(inter)
    elif key == "inv:rings":
        await market.inventory_rings(inter)
    elif key == "inv:filter":
        await market.inventory_roles(inter, side)
    elif key.startswith("inv:roles:"):
        _, _, filter_key, page = key.split(":", 3)
        if page.isdecimal() and len(page) <= 9:
            await market.inventory_roles(inter, filter_key, int(page))
    elif key.startswith("mk:"):
        await market.handle(inter, key)
    elif key == "coin":
        if n < 10:
            return await reply(inter, "Минимальная ставка — 10", rows=[["coin"]])
        s = "решка" if side.strip().lower().startswith("р") else "орёл"
        await coinflip.callback(inter, n, app_commands.Choice(name=s, value=s))
    elif key == "duel":
        if n < 10:
            return await reply(inter, "Минимальная ставка — 10", rows=[["duel"]])
        await duel.callback(inter, n, None)


async def begin(inter: discord.Interaction):
    """Нажатие в личном сообщении меняет его же; в общей панели — открывает личное."""
    msg = inter.message
    meta = getattr(msg, "interaction_metadata", None) if msg else None
    own = msg is not None and (msg.flags.ephemeral or (meta is not None and meta.user.id == inter.user.id))
    if own:  # своё сообщение — меняем его же
        await inter.response.defer()
        inter.extras["sd_edit"] = True
    else:    # чужое меню — открываем своё отдельным сообщением
        await inter.response.defer(thinking=True)


async def run_action(inter: discord.Interaction, key: str, n: int = 0, side: str = ""):
    await run_fn(inter, lambda i: menu_action(key, i, n, side), key)


async def run_fn(inter: discord.Interaction, fn, label: str = "окно"):
    """Подтверждает нажатие и выполняет действие строго по очереди с остальными."""
    try:
        await begin(inter)
        async with ECON_LOCK:
            await fn(inter)
            await after_action(inter)
    except Exception as ex:
        print("Ошибка кнопки:", label, repr(ex))
        try:
            await reply(inter, "Что-то пошло не так, попробуй ещё раз")
        except Exception:
            pass


class AmountModal(discord.ui.Modal):
    def __init__(self, key: str):
        title, label, hint = MENU_MODALS[key]
        super().__init__(title=title)
        self.key = key
        self.amount = discord.ui.TextInput(label=label, placeholder=hint, max_length=9)
        self.add_item(self.amount)
        self.side = None
        if key == "coin":
            self.side = discord.ui.TextInput(label="Орёл или решка", default="орёл", max_length=10)
            self.add_item(self.side)

    async def on_submit(self, inter: discord.Interaction):
        raw = self.amount.value.strip()
        if not raw.isdigit():
            return await inter.response.send_message("Нужно целое число", ephemeral=True)
        await run_action(inter, self.key, int(raw), self.side.value if self.side else "")


class RoomNameModal(discord.ui.Modal, title="Название лав-румы"):
    name = discord.ui.TextInput(label="Название", placeholder="например: Наш замок",
                                max_length=marriage.ROOM_NAME_MAX)

    async def on_submit(self, inter: discord.Interaction):
        await run_fn(inter, lambda i: marriage.rename_room(i, self.name.value), "roomname")


@bot.event
async def on_interaction(inter: discord.Interaction):
    """Все кнопки бота (sd:...) — работают и после перезапуска."""
    if inter.type is not discord.InteractionType.component:
        return
    cid = str((inter.data or {}).get("custom_id", ""))
    if not cid.startswith("sd:"):
        return
    key = cid[3:]
    if key == "sections":   # выбор в списке «Все разделы»
        vals = (inter.data or {}).get("values") or [""]
        key = str(vals[0])
    side = ""
    if key in ("ringbook:action", "ringbook:giftselect", "inv:filter", "anniversary:pick", "showcase:toggle", "showcase:more", "season:archive"):
        vals = (inter.data or {}).get("values") or [""]
        side = str(vals[0])
    if (key not in BUTTONS and key not in ("inv:filter", "anniversary:pick", "showcase:save", "showcase:toggle", "showcase:more", "showcase:clear")
            and not key.startswith(("mk:", "inv:roles:", "history:", "season:archive:"))):
        return
    try:
        if await wrong_channel(inter):
            return
        if too_fast(inter.user.id):
            return await inter.response.send_message(
                "⏳ Не так быстро, подожди пару секунд", ephemeral=True)
        if key == "history" or key.startswith("history:"):
            argument = key.partition(":")[2]
            category, _, cursor = argument.partition(":")
            if argument == "filter":
                category = next(iter((inter.data or {}).get("values") or []), "all")
            elif category not in ledger.FILTERS:
                cursor, category = argument, "all"
            if cursor and (not cursor.isascii() or not cursor.isdecimal() or len(cursor) > 18):
                return await inter.response.send_message("Эта страница истории недоступна.", ephemeral=True)
            if inter.message and inter.message.flags.ephemeral:
                await inter.response.defer()
                inter.extras["sd_edit"] = True
            else:
                await inter.response.defer(ephemeral=True, thinking=True)
            return await ledger.show(inter, int(cursor) if cursor else None, category)
        if key == "roomname":
            return await inter.response.send_modal(RoomNameModal())
        if key in MENU_MODALS:
            return await inter.response.send_modal(AmountModal(key))
        modal = market.modal_for(key)
        if modal:
            return await inter.response.send_modal(modal)
    except discord.HTTPException as ex:
        return print("Ошибка кнопки:", key, repr(ex))
    await run_action(inter, key, side=side)


def menu_page() -> dict:
    """Общая панель меню (для канала): баннер, быстрые кнопки и список разделов."""
    e = discord.Embed(
        title="Двор Seikatsu — меню",
        description=("Профиль и инвентарь всегда под рукой. В меню — монеты, награда, служба и прогресс.\n"
                     "-# Командами остались действия с другим игроком: "
                     "`/перевод`, `/дуэль` и `/брак`."),
        color=RED)
    rows = [["menu", "daily", "work"], ["profile", "inventory", "quests", "balance"], [sections_select()]]
    kw = {"embed": e, "rows": rows, "nav": False}
    b = getattr(bot, "banners", {})
    path = b.get("menu") or b.get("help")
    if path and os.path.exists(path):
        kw["image"] = (card_name(path), path)
    return kw


@bot.tree.command(name="меню", description="Все действия кнопками")
async def menu(inter: discord.Interaction):
    await dashboard(inter)

