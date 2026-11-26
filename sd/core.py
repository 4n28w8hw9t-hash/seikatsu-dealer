"""Ядро: настройки, база, сам бот, страницы с кнопками и баннерами."""
import aiosqlite
import art
import asyncio
import discord
from . import smallcaps  # noqa: F401,E402  — Small Caps для текста бота
import io
import os
import time
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN") or os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
GUILD_ID = os.getenv("GUILD_ID")  # необязательно: команды появятся на сервере мгновенно

# ───────── Настройки экономики ─────────
CURRENCY = "🪙"
START_BALANCE = 100
DAILY_REWARD = 100          # /награда — раз в 24 часа
MSG_COOLDOWN = 60           # опыт за сообщения — не чаще раза в минуту
DATA_DIR = os.getenv("DATA_DIR", ".")  # на хостинге — постоянная папка
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.getenv("DB_PATH") or os.path.join(DATA_DIR, "economy.db")

def fmt(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " " + E("sd_coin", CURRENCY)


def fmt_time(sec: int) -> str:
    h, rem = divmod(int(sec), 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h: parts.append(f"{h} ч")
    if m: parts.append(f"{m} мин")
    if s and not h: parts.append(f"{s} сек")
    return " ".join(parts) or "0 сек"


ECON_LOCK = asyncio.Lock()   # операции с монетами идут строго по одной — защита от дюпа
LAST_CMD: dict[int, float] = {}
CMD_GAP = 1.5                # минимальная пауза между действиями одного игрока, сек


def too_fast(user_id: int) -> bool:
    now = time.time()
    if now - LAST_CMD.get(user_id, 0) < CMD_GAP:
        return True
    LAST_CMD[user_id] = now
    return False


BOT_CHANNEL_ID = 1574168108434718780   # все сообщения бота идут в этот канал


def bot_channel(guild: discord.Guild | None):
    return guild.get_channel(BOT_CHANNEL_ID) if guild else None


async def wrong_channel(inter: discord.Interaction) -> bool:
    """Команда не в канале бота — скрытая подсказка перейти туда. True, если канал чужой."""
    if inter.guild is None or inter.channel_id == BOT_CHANNEL_ID or bot_channel(inter.guild) is None:
        return False
    try:
        await inter.response.send_message(
            f"🥀 Команды бота работают только в <#{BOT_CHANNEL_ID}> — переходи туда", ephemeral=True)
    except discord.HTTPException:
        pass
    return True


AFTER_ACTION = []   # что сделать после каждой команды и кнопки (например, проверить достижения)


async def after_action(inter: discord.Interaction):
    for hook in AFTER_ACTION:
        try:
            await hook(inter)
        except Exception as ex:
            print("Ошибка после действия:", repr(ex))


STAFF_COMMANDS = {"админ"}


class DeferTree(app_commands.CommandTree):
    """Антиспам, мгновенное личное подтверждение и очередь для операций с монетами."""
    async def _call(self, interaction: discord.Interaction):
        if interaction.type == discord.InteractionType.application_command:
            staff = (interaction.data or {}).get("name") in STAFF_COMMANDS   # админ-панель — скрыто и в любом канале
            if not staff and await wrong_channel(interaction):
                return
            try:
                if too_fast(interaction.user.id):
                    return await interaction.response.send_message(
                        "⏳ Не так быстро, подожди пару секунд", ephemeral=True)
                await interaction.response.defer(thinking=True, ephemeral=staff)
            except discord.HTTPException:
                pass
        async with ECON_LOCK:
            await super()._call(interaction)
            if interaction.type == discord.InteractionType.application_command:
                await after_action(interaction)


RED = discord.Color.from_rgb(209, 53, 57)
V2 = hasattr(discord.ui, "LayoutView")   # новые «широкие» сообщения Discord
# кнопка: (подпись, запасной эмодзи, своя иконка sd_<имя>, цвет)
_G, _B, _OK, _R = (discord.ButtonStyle.secondary, discord.ButtonStyle.primary,
                   discord.ButtonStyle.success, discord.ButtonStyle.danger)
BUTTONS = {
    "menu": ("Меню", "◀️", "menu", _G),
    "profile": ("Профиль", "👤", "profile", _B),
    "ach": ("Достижения", "🏅", "top", _B),
    "path": ("Путь", "👑", "path", _B),
    "work": ("Работа", "⚒️", "work", _OK),
    "path:noble": ("Знать", "👑", "noble", _B),
    "path:faith": ("Вера", "✝️", "faith", _B),
    "balance": ("Баланс", "💰", "coin", _G),
    "daily": ("Награда", "🎁", "gift", _OK),
    "coin": ("Монетка", "🪙", "flip", _R),
    "couple": ("Пара", "💞", "couple", _B),
    "rings": ("Кольца", "💍", "ring", _G),
    "ringbook": ("Коллекция колец", "💍", "ring", _B),
    "ringbook:action": ("Действие с кольцом", "💍", "ring", _B),
    "ringbook:giftselect": ("Выбор кольца для подарка", "🎁", "gift", _B),
    "ringgift": ("Подарить кольцо", "🎁", "gift", _B),
    "loveroom": ("Лав-рума", "🕯️", "loveroom", _B),
    "divorce": ("Развод", "💔", "divorce", _G),
    "divorce:yes": ("Да, развестись", "💔", "divorce", _R),
    "ring:silver": ("Серебряное · 300", "💍", "ring_silver", _OK),
    "ring:gold": ("Золотое · 1500", "💛", "ring_gold", _OK),
    "ring:ruby": ("С рубином · 5000", "❤️", "ring_ruby", _OK),
    "market": ("Магазин ролей", "🛒", "shop", _G),
    "roles": ("Мои роли", "🎭", "inv", _B),
    "rolecreate": ("Создать роль", "✨", "skill", _OK),
    "help": ("Помощь", "❓", "help", _G),
    "roomname": ("Название румы", "🏷️", "tag", _G),
    "duel": ("Дуэль", "⚔️", "duel", _G),
    "top": ("Топ", "🏆", "trophy", _B),
    "top:lvl": ("По уровню", "⭐", "top_lvl", _B),
    "top:coin": ("По монетам", "💰", "top_coin", _G),
}
NAV = ["menu", "profile", "couple"]


async def member_name(guild: discord.Guild | None, uid: int) -> str:
    """Имя участника на сервере (даже если его нет в кэше)."""
    m = guild.get_member(uid) if guild else None
    if m is None and guild is not None:
        try:
            m = await guild.fetch_member(uid)
        except discord.HTTPException:
            m = None
    return m.display_name if m else "кто-то"


# обычные эмодзи → свои иконки бота (icons/<имя>.png). Если иконки нет — остаётся эмодзи.
ICON_MAP = {
    "⚪": "gem_common", "🔵": "gem_rare", "🟣": "gem_epic", "🟠": "gem_legendary",
    "🔒": "lock", "🏅": "top", "⏳": "hourglass", "🥀": "rose", "📜": "help", "👑": "path",
    "⚒️": "work", "🎁": "gift", "👤": "profile", "🪙": "flip", "⚔️": "duel", "💍": "ring",
    "🎉": "win", "😢": "lose", "🛒": "shop", "🎭": "inv", "🛍️": "bag", "✨": "skill", "⭐": "skill",
    "👕": "hanger", "🏷️": "tag", "✖️": "cancel", "✝️": "faith", "💞": "couple", "💔": "divorce",
    "🕯️": "loveroom", "🏆": "trophy", "💰": "coin", "🎲": "flip", "💛": "ring_gold",
    "❤️": "ring_ruby", "◀️": "menu", "❓": "help",
}
_ICON_ORDER = sorted(ICON_MAP, key=len, reverse=True)


def iconize(text):
    """Заменяет в тексте обычные эмодзи на свои иконки бота."""
    if not text or not isinstance(text, str):
        return text
    emo = getattr(bot, "emo", {})
    for u in _ICON_ORDER:
        if u in text and emo.get(f"sd_{ICON_MAP[u]}"):
            text = text.replace(u, emo[f"sd_{ICON_MAP[u]}"])
    return text


def icon_emoji(u: str):
    """Эмодзи для кнопки: своя иконка, если есть, иначе обычный эмодзи."""
    custom = getattr(bot, "emo", {}).get(f"sd_{ICON_MAP.get(u, '')}")
    if custom:
        try:
            return discord.PartialEmoji.from_str(custom)
        except Exception:
            pass
    return u


def make_button(key: str) -> discord.ui.Button:
    label, emo, icon, style = BUTTONS[key]
    custom = getattr(bot, "emo", {}).get(f"sd_{icon}")
    if custom:
        try:
            emo = discord.PartialEmoji.from_str(custom)
        except Exception:
            pass
    return discord.ui.Button(label=label, emoji=emo, style=style, custom_id=f"sd:{key}")


def _file(image) -> discord.File:
    name, src = image
    return discord.File(src if isinstance(src, str) else io.BytesIO(src), filename=name)


def _embed_text(e: discord.Embed | None, content: str | None) -> str:
    return iconize(_embed_text_raw(e, content))


def _embed_text_raw(e: discord.Embed | None, content: str | None) -> str:
    parts = []
    if e is not None:
        if e.title:
            parts.append(f"## {e.title}")
        if e.description:
            parts.append(e.description)
        short = []
        for f in e.fields:
            if f.name == "​":
                continue
            if f.inline and "\n" not in f.value:
                short.append(f"**{f.name}:** {f.value}")
            else:
                parts.append(f"### {f.name}\n{f.value}")
        if short:
            parts.append("\n".join(short))
        if e.footer and e.footer.text:
            parts.append(f"-# {e.footer.text}")
    if content:
        parts.append(str(content))
    return "\n".join(parts)[:3900]


def build_page(content=None, embed=None, image=None, rows=None, nav=True, thumb=None):
    """Широкая карточка: баннер (или портрет справа), текст и кнопки внутри одной рамки."""
    ui = discord.ui
    items, files = [], []
    if image:
        files.append(_file(image))
        items.append(ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{image[0]}")))
    text = _embed_text(embed, content)
    if thumb:          # маленький портрет персонажа справа от текста
        files.append(_file(thumb))
        thumb = f"attachment://{thumb[0]}"
    else:
        thumb = embed.thumbnail.url if embed is not None and embed.thumbnail else None
    if text and thumb:
        items.append(ui.Section(ui.TextDisplay(text), accessory=ui.Thumbnail(thumb)))
    elif text:
        items.append(ui.TextDisplay(text))
    used = set()   # одна и та же кнопка дважды в сообщении запрещена
    for row in rows or []:
        if row == "---":
            items.append(ui.Separator(spacing=discord.SeparatorSpacing.large))
            continue
        if isinstance(row, str):
            items.append(ui.TextDisplay(row))
            continue
        keys = [k for k in row if not isinstance(k, str) or k not in used]
        used.update(k for k in keys if isinstance(k, str))
        if keys:  # строка — ключ кнопки из BUTTONS, иначе готовый элемент (кнопка/список)
            items.append(ui.ActionRow(*[make_button(k) if isinstance(k, str) else k for k in keys]))
    keys = [k for k in NAV if k not in used] if nav else []
    if keys:
        items.append(ui.Separator())
        items.append(ui.ActionRow(*[make_button(k) for k in keys]))
    color = embed.color if embed is not None and embed.color else RED
    view = ui.LayoutView(timeout=None)
    view.add_item(ui.Container(*items, accent_colour=color))
    view.stop()  # нажатия ловит on_interaction, хранить сообщение в памяти не нужно
    return view, files


def build_classic(content=None, embed=None, image=None, rows=None, nav=True, thumb=None) -> dict:
    """Запасной вид (обычный эмбед), если широкие карточки недоступны."""
    if embed is None and thumb and content:
        embed, content = discord.Embed(description=iconize(str(content)), color=RED), None
    kw = {"content": content, "embed": embed, "attachments": []}
    if image:
        kw["attachments"] = [_file(image)]
        if embed is not None:
            embed.set_image(url=f"attachment://{image[0]}")
    if thumb and embed is not None:
        kw["attachments"].append(_file(thumb))
        embed.set_thumbnail(url=f"attachment://{thumb[0]}")
    view = discord.ui.View(timeout=None)
    lines = [r for r in (rows or []) if not isinstance(r, str)][:4]
    if nav:
        lines.append(NAV)
    used = set()
    for i, row in enumerate(lines[:5]):
        for k in row[:5]:
            if isinstance(k, str):
                if k in used:
                    continue
                used.add(k)
            b = make_button(k) if isinstance(k, str) else k
            b.row = i
            view.add_item(b)
    view.stop()
    kw["view"] = view
    return kw


async def _deliver(inter: discord.Interaction, kw: dict, ephemeral: bool):
    if inter.extras.get("sd_edit"):  # меняем то же сообщение, где нажали кнопку
        msg = inter.message
        if "embed" not in kw and not (msg and msg.flags.components_v2):
            kw["content"], kw["embeds"] = None, []   # старое сообщение было обычным эмбедом
        return await inter.edit_original_response(**kw)
    files = kw.pop("attachments", [])
    kw = {k: v for k, v in kw.items() if v is not None}
    if files:
        kw["files"] = files
    if inter.response.is_done():
        return await inter.followup.send(ephemeral=ephemeral, **kw)
    return await inter.response.send_message(ephemeral=ephemeral, **kw)


def char_thumb(key: str | None):
    """Портрет персонажа (chars/<key>.png) для короткого ответа: (имя файла, байты) или None."""
    path = getattr(bot, "banners", {}).get(key or "")
    if not path:
        return None
    char = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(path))), "chars",
                        os.path.splitext(os.path.basename(path))[0] + ".png")
    try:
        data = art.thumb(char)
    except Exception as ex:
        print("Портрет не нарисован:", key, repr(ex))
        return None
    return ("portrait.png", data) if data else None


async def reply(inter: discord.Interaction, content=None, *, embed=None, image=None,
                rows=None, nav=True, ephemeral=False, allowed_mentions=None, key="deny",
                thumb=None):
    """Ответ бота (виден всем в канале). Кнопки ведут на другие страницы.

    key — персонаж для ответа без своей картинки (по умолчанию «стража»): маленький портрет
    справа от текста. None — без картинки. Большой баннер — через image / send_card.
    """
    if image is None and thumb is None and key:
        thumb = char_thumb(key)
        if thumb is None:   # нет вырезанного персонажа — как раньше, баннером
            path = getattr(bot, "banners", {}).get(key)
            if path and os.path.exists(path):
                image = (card_name(path), path)
    extra = {"allowed_mentions": allowed_mentions} if allowed_mentions is not None else {}
    if V2:
        try:
            view, files = build_page(content, embed, image, rows, nav, thumb)
            return await _deliver(inter, {"view": view, "attachments": files, **extra}, ephemeral)
        except Exception as ex:
            print("Карточка не отправлена, пробую обычный вид:", repr(ex))
    kw = build_classic(content, embed, image, rows, nav, thumb)
    return await _deliver(inter, {**kw, **extra}, ephemeral)


def card_name(path: str) -> str:
    """Имя вложения по расширению файла баннера (card.png или card.jpg)."""
    return "card" + (os.path.splitext(path)[1].lower() or ".png")


def E(name: str, fallback: str = "") -> str:
    return getattr(bot, "emo", {}).get(name, fallback)


async def send_card(inter: discord.Interaction, e: discord.Embed, key: str, **kw):
    path = getattr(bot, "banners", {}).get(key)
    if path and os.path.exists(path):
        kw["image"] = (card_name(path), path)
    return await reply(inter, embed=e, **kw)


async def send_panel(inter: discord.Interaction, key: str, title: str, *, subtitle="", icon="",
                     bar=None, tiles=(), lines=(), rows=None, nav=True, fallback=None):
    """Карточка-картинка: баннер, плитки с цифрами, строки (см. art.panel_card)."""
    path = getattr(bot, "banners", {}).get(key)
    try:
        img = await asyncio.to_thread(art.panel_card, path, title, subtitle, icon, bar,
                                      list(tiles), list(lines))
        return await reply(inter, image=("panel.jpg", img), rows=rows, nav=nav)
    except Exception as ex:
        print("Панель не нарисована:", key, repr(ex))
    if fallback is None:
        fallback = embed(title, "\n".join([subtitle] + [f"**{t[1]}:** {t[2]}" for t in tiles]
                                          + [l[1] for l in lines]))
    return await send_card(inter, fallback, key, rows=rows, nav=nav)


async def send_result(inter: discord.Interaction, key: str, title: str, text: str = "",
                      note: str = "", rows=None, nav=True, **kw):
    """Короткий ответ: заголовок, пара строк и портрет персонажа справа."""
    body = f"## {title}" + (f"\n**{text}**" if text else "") + (f"\n-# {note}" if note else "")
    return await reply(inter, body, rows=rows, nav=nav, key=key, **kw)


def btn(key: str, label: str | None = None, style=None) -> discord.ui.Button:
    """Кнопка из BUTTONS со своей подписью/цветом (например, с таймером)."""
    b = make_button(key)
    if label is not None:
        b.label = label
    if style is not None:
        b.style = style
    return b


async def send_public(inter: discord.Interaction, e: discord.Embed, key: str, **kw):
    """Сообщение, которое видят все (дуэли и ограбления)."""
    path = getattr(bot, "banners", {}).get(key)
    if path and os.path.exists(path):
        e.set_image(url=f"attachment://{card_name(path)}")
        kw["file"] = discord.File(path, filename=card_name(path))
    try:
        msg = await inter.channel.send(embed=e, **kw)
    except discord.HTTPException:
        await reply(inter, "Не могу написать в этот канал — у бота нет прав")
        return None
    if not inter.extras.get("sd_edit"):   # своё меню не удаляем, только «думает…»
        try:
            await inter.delete_original_response()
        except discord.HTTPException:
            pass
    return msg


class EconomyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = False  # для награды за сообщения текст не нужен
        intents.members = True   # нужно, чтобы видеть выдачу ролей (разделители)
        super().__init__(command_prefix="!", intents=intents, tree_cls=DeferTree)
        self.db: aiosqlite.Connection | None = None
        self.msg_cd: dict[tuple[int, int], float] = {}

    async def setup_hook(self):
        self.db = await aiosqlite.connect(DB_PATH)
        await self.db.execute("PRAGMA journal_mode=WAL")
        await self.db.execute("PRAGMA synchronous=NORMAL")
        await self.db.executescript("""
        CREATE TABLE IF NOT EXISTS users(
            guild_id INTEGER, user_id INTEGER,
            balance INTEGER DEFAULT 0, bank INTEGER DEFAULT 0,
            last_daily INTEGER DEFAULT 0, streak INTEGER DEFAULT 0,
            last_work INTEGER DEFAULT 0, last_rob INTEGER DEFAULT 0,
            PRIMARY KEY(guild_id, user_id));
        CREATE TABLE IF NOT EXISTS shop(
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER,
            name TEXT, price INTEGER, description TEXT, role_id INTEGER);
        CREATE TABLE IF NOT EXISTS inventory(
            guild_id INTEGER, user_id INTEGER, item_id INTEGER,
            qty INTEGER DEFAULT 0, PRIMARY KEY(guild_id, user_id, item_id));
        """)
        await self.db.execute(
            "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
        try:
            await self.db.execute("ALTER TABLE users ADD COLUMN xp INTEGER DEFAULT 0")
        except Exception:
            pass  # колонка уже есть
        for col in ("cls TEXT", "cls_xp INTEGER DEFAULT 0", "cls_changed INTEGER DEFAULT 0",
                    "skill_ready INTEGER DEFAULT 0", "skill_active INTEGER DEFAULT 0",
                    "msgs INTEGER DEFAULT 0", "voice_min INTEGER DEFAULT 0",
                    "path TEXT", "path_changed INTEGER DEFAULT 0",
                    "duel_wins INTEGER DEFAULT 0", "flip_wins INTEGER DEFAULT 0", "ach TEXT",
                    "works INTEGER DEFAULT 0"):
            try:
                await self.db.execute(f"ALTER TABLE users ADD COLUMN {col}")
            except Exception:
                pass
        await self.db.executescript("""
        CREATE TABLE IF NOT EXISTS marriages(
            guild_id INTEGER, a INTEGER, b INTEGER, since INTEGER, ring TEXT,
            xp INTEGER DEFAULT 0, room_id INTEGER, room_created INTEGER,
            PRIMARY KEY(guild_id, a));
        CREATE TABLE IF NOT EXISTS custom_roles(
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER, owner_id INTEGER,
            role_id INTEGER, name TEXT, color INTEGER, price INTEGER,
            sold INTEGER DEFAULT 0, earned INTEGER DEFAULT 0, created INTEGER);
        CREATE TABLE IF NOT EXISTS role_owners(
            guild_id INTEGER, role_ref INTEGER, user_id INTEGER, worn INTEGER DEFAULT 1,
            PRIMARY KEY(guild_id, role_ref, user_id));
        CREATE TABLE IF NOT EXISTS rings(
            guild_id INTEGER, user_id INTEGER, ring TEXT, qty INTEGER DEFAULT 0,
            PRIMARY KEY(guild_id, user_id, ring));
        """)
        try:   # после создания таблицы marriages (на новой базе её раньше нет)
            await self.db.execute("ALTER TABLE marriages ADD COLUMN room_name TEXT")
        except Exception:
            pass  # колонка уже есть
        # банка больше нет: всё, что лежало в нём, переходит на баланс
        await self.db.execute("UPDATE users SET balance=balance+bank, bank=0 WHERE bank>0")
        await self.db.commit()
        from . import levels
        levels.tick.start()

        try:  # баннеры команд (рисуются один раз и лежат в data/)
            self.banners = await asyncio.to_thread(
                art.build_all, BANNER_PATH, os.path.join(DATA_DIR, "art_v2"),
                os.path.join(os.path.dirname(BANNER_PATH), "chars.png"))
        except Exception as ex:
            print("Баннеры не созданы:", ex)
            self.banners = {}
        ready = os.path.join(os.path.dirname(BANNER_PATH), "banners")
        if os.path.isdir(ready):  # готовые баннеры с персонажами
            for fn in os.listdir(ready):
                name, ext = os.path.splitext(fn)
                if ext.lower() in (".png", ".jpg", ".jpeg") and \
                        (name not in self.banners or ext.lower() != ".png"):  # jpg важнее png
                    self.banners[name] = os.path.join(ready, fn)
        try:  # свои эмодзи бота
            have = {em.name: em for em in await self.fetch_application_emojis()}
            for name in art.EMOJIS:
                if name not in have:
                    buf = io.BytesIO()
                    art.emoji_png(name).save(buf, "PNG")
                    have[name] = await self.create_application_emoji(name=name, image=buf.getvalue())
            self.emo = {n: str(em) for n, em in have.items()}
            icons = os.path.join(os.path.dirname(BANNER_PATH), "icons")
            if os.path.isdir(icons):  # свои иконки: icons/<имя>.png заменяют нарисованные
                import zlib
                for fn in sorted(os.listdir(icons)):
                    if not fn.endswith(".png"):
                        continue
                    with open(os.path.join(icons, fn), "rb") as f:
                        raw = f.read()
                    base = f"sdx_{fn[:-4]}_"
                    name = f"{base}{zlib.crc32(raw) % 100000}"
                    try:
                        # старые версии этой же иконки: base + только цифры (не трогаем ring_gold у ring)
                        for n in [n for n in have if n.startswith(base) and n[len(base):].isdigit()
                                  and n != name]:
                            await have.pop(n).delete()
                        if name not in have:
                            have[name] = await self.create_application_emoji(name=name, image=raw)
                        self.emo[f"sd_{fn[:-4]}"] = str(have[name])
                    except Exception as ex:
                        print("Иконка не загружена:", fn, repr(ex))
        except Exception as ex:
            print("Эмодзи не загружены:", ex)
            self.emo = {}

        if GUILD_ID:
            g = discord.Object(id=int(GUILD_ID))
            self.tree.copy_global_to(guild=g)
            await self.tree.sync(guild=g)
        else:
            await self.tree.sync()

    async def close(self):
        if self.db:
            await self.db.close()
        await super().close()

    # ───── работа с БД ─────
    async def get_user(self, guild_id: int, user_id: int) -> dict:
        await self.db.execute(
            "INSERT OR IGNORE INTO users(guild_id,user_id,balance) VALUES(?,?,?)",
            (guild_id, user_id, START_BALANCE))
        cur = await self.db.execute(
            "SELECT balance,bank,last_daily,streak,last_work,last_rob FROM users "
            "WHERE guild_id=? AND user_id=?", (guild_id, user_id))
        r = await cur.fetchone()
        return dict(zip(["balance", "bank", "last_daily", "streak", "last_work", "last_rob"], r))

    async def add(self, guild_id: int, user_id: int, amount: int, field: str = "balance"):
        await self.get_user(guild_id, user_id)
        await self.db.execute(
            f"UPDATE users SET {field}={field}+? WHERE guild_id=? AND user_id=?",
            (amount, guild_id, user_id))
        await self.db.commit()

    async def set_field(self, guild_id: int, user_id: int, **fields):
        sets = ",".join(f"{k}=?" for k in fields)
        await self.db.execute(
            f"UPDATE users SET {sets} WHERE guild_id=? AND user_id=?",
            (*fields.values(), guild_id, user_id))
        await self.db.commit()


bot = EconomyBot()


def embed(title: str, desc: str = "", color=discord.Color.gold()) -> discord.Embed:
    return discord.Embed(title=iconize(title), description=iconize(desc), color=color)


@bot.event
async def on_ready():
    print(f"Бот запущен как {bot.user} (id {bot.user.id})")


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # папка проекта
BANNER_PATH = os.path.join(ROOT, "banner.png")


def welcome_channel(guild: discord.Guild) -> discord.TextChannel | None:
    """Системный канал сервера или первый канал, куда бот может писать."""
    me = guild.me
    if guild.system_channel and guild.system_channel.permissions_for(me).send_messages:
        return guild.system_channel
    for ch in sorted(guild.text_channels, key=lambda c: c.position):
        p = ch.permissions_for(me)
        if p.send_messages and p.embed_links:
            return ch
    return None


@bot.event
async def on_guild_join(guild: discord.Guild):
    ch = welcome_channel(guild)
    if ch is None:
        return
    e = discord.Embed(
        title="🥀 Двор открыт",
        description=(
            f"Добро пожаловать ко двору **{guild.name}**.\n"
            "Я — принцесса этих земель. Каждая монета в казне проходит через мои руки.\n\n"
            "**С чего начать**\n"
            "📜 `/меню` — всё кнопками\n"
            "👑 `/путь` — знать или вера: титул растёт с уровнем\n"
            "⚒️ `/работа` — жалованье по титулу раз в 12 часов\n"
            "🎁 `/награда` — 100 монет раз в сутки\n"
            "👤 `/профиль` — уровень, опыт, пара и достижения\n"
            "🪙 `/монетка` — орёл или решка, x2\n"
            "⚔️ `/дуэль` — сразиться с кем-то на монеты\n"
            "💍 `/брак` — сделать предложение, у пары своя лав-рума\n\n"
            "Опыт идёт за сообщения и голосовые каналы."
        ),
        color=discord.Color.from_rgb(209, 53, 57),
    )
    e.set_footer(text="Админам: /эко — управление монетами")
    bpath = getattr(bot, "banners", {}).get("welcome", BANNER_PATH)
    if os.path.exists(bpath):
        file = discord.File(bpath, filename="banner.png")
        e.set_image(url="attachment://banner.png")
        await ch.send(embed=e, file=file)
    else:
        await ch.send(embed=e)

