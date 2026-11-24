"""Small Caps для всего текста бота: подменяет буквы на «маленькие заглавные» прямо перед отправкой.
Не трогает упоминания, свои эмодзи, ссылки, `код` и названия файлов. Выключить: ENABLED = False."""
import json
import re

import discord
from discord import http as _http
from discord.webhook import async_ as _wh

ENABLED = False

MAP = {
    'а': 'ᴀ', 'в': 'ʙ', 'г': 'ᴦ', 'е': 'ᴇ', 'ё': 'ᴇ', 'и': 'ᴎ', 'к': 'ᴋ', 'л': 'ᴫ', 'м': 'ᴍ', 'н': 'ʜ',
    'о': 'ᴏ', 'п': 'ᴨ', 'р': 'ᴘ', 'с': 'ᴄ', 'т': 'ᴛ', 'у': 'ʏ', 'х': 'x', 'я': 'ᴙ',
    'a': 'ᴀ', 'b': 'ʙ', 'c': 'ᴄ', 'd': 'ᴅ', 'e': 'ᴇ', 'f': 'ꜰ', 'g': 'ɢ', 'h': 'ʜ', 'i': 'ɪ', 'j': 'ᴊ',
    'k': 'ᴋ', 'l': 'ʟ', 'm': 'ᴍ', 'n': 'ɴ', 'o': 'ᴏ', 'p': 'ᴘ', 'q': 'ǫ', 'r': 'ʀ', 's': 'ꜱ', 't': 'ᴛ',
    'u': 'ᴜ', 'v': 'ᴠ', 'w': 'ᴡ', 'x': 'x', 'y': 'ʏ', 'z': 'ᴢ',
}
_KEEP = re.compile(r"(<[^>\s]+>|https?://\S+|attachment://\S+|`[^`]*`|:[A-Za-z0-9_~]+:|@everyone|@here)")
_TEXT_KEYS = {"content", "title", "description", "text", "label", "placeholder"}


def sc(text: str) -> str:
    if not ENABLED or not isinstance(text, str) or not text:
        return text
    parts = _KEEP.split(text)
    for i in range(0, len(parts), 2):       # чётные куски — обычный текст
        parts[i] = "".join(MAP.get(ch.lower(), ch.lower() if ch.isalpha() else ch) for ch in parts[i])
    return "".join(parts)


def _walk(obj, parent=None):
    if isinstance(obj, dict):
        is_emoji = "id" in obj and "name" in obj and "custom_id" not in obj and "type" not in obj
        for k, v in list(obj.items()):
            if isinstance(v, str):
                if k in _TEXT_KEYS:
                    obj[k] = sc(v)
                elif k == "value" and parent == "fields":          # значения полей эмбеда (не value у меню!)
                    obj[k] = sc(v)
                elif k == "name" and parent in ("fields", "author") and not is_emoji:
                    obj[k] = sc(v)
            else:
                _walk(v, k)
    elif isinstance(obj, list):
        for x in obj:
            _walk(x, parent)


def _is_message_route(route) -> bool:
    p = getattr(route, "path", "") or ""
    return p.endswith("/messages") or p.endswith("/threads") or "/messages/{message_id}" in p or "/callback" in p \
        or p.startswith("/webhooks/{webhook_id}/{webhook_token}")


def _fix_form(form):
    for part in form or []:
        if part.get("name") == "payload_json" and isinstance(part.get("value"), str):
            try:
                data = json.loads(part["value"])
                _walk(data)
                part["value"] = json.dumps(data, ensure_ascii=False)
            except Exception:
                pass


_orig_http = _http.HTTPClient.request


async def _http_request(self, route, *, files=None, form=None, **kwargs):
    if ENABLED and _is_message_route(route):
        if isinstance(kwargs.get("json"), (dict, list)):
            _walk(kwargs["json"])
        _fix_form(form)
    return await _orig_http(self, route, files=files, form=form, **kwargs)


_orig_wh = _wh.AsyncWebhookAdapter.request


async def _wh_request(self, route, session, *, payload=None, multipart=None, **kwargs):
    if ENABLED and _is_message_route(route):
        if isinstance(payload, (dict, list)):
            _walk(payload)
        _fix_form(multipart)
    return await _orig_wh(self, route, session, payload=payload, multipart=multipart, **kwargs)


_http.HTTPClient.request = _http_request
_wh.AsyncWebhookAdapter.request = _wh_request
