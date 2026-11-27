import asyncio
from contextlib import ExitStack
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import aiosqlite
from PIL import Image

import art
from sd import core, menu, showcase, winter
from sd import winter_state as w


class WinterBallTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = str(Path(tmp.name) / "court.db")
        self.db = await aiosqlite.connect(path)
        self.addAsyncCleanup(self.db.close)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(core, "DB_PATH", path))
        stack.enter_context(patch.object(core.bot, "db", self.db))
        await self.db.executescript(
            w.SCHEMA
            + """
          CREATE TABLE users(guild_id,user_id,balance DEFAULT 0,last_daily DEFAULT 0,last_work DEFAULT 0,
                             PRIMARY KEY(guild_id,user_id));
          CREATE TABLE marriages(guild_id,a,b,since);
          CREATE TABLE coin_history(guild_id,user_id,amount,kind,detail,status,role_ref,created);
        """
        )

    async def act(self, u, action, day, g=1):
        async with core.bot.transaction() as db:
            return await w.act(db, g, u, action, day)

    async def test_schedule_rewards_and_duplicate_clicks(self):
        self.assertIsNone(w.stage(w.START - timedelta(days=1)))
        self.assertEqual(
            [w.stage(w.START + timedelta(days=i)) for i in (0, 6, 7, 13, 14, 20, 21, 26)],
            [0, 0, 1, 1, 2, 2, 3, 3],
        )
        self.assertIsNone(w.stage(w.END))
        await self.act(1, "strike", w.START - timedelta(days=1))
        for idx in range(4):
            day = w.START + timedelta(days=idx * 7)
            await asyncio.gather(self.act(1, "strike", day), self.act(1, "counter", day))
            for u in range(2, 8):
                await self.act(u, "strike", day)
        totals, mine = await w.progress(self.db, 1, 1)
        self.assertEqual(mine, [1, 1, 1, 1])
        self.assertTrue(all(t >= v for t, v in zip(totals, w.GOALS)))
        await self.act(1, "hall", w.END)
        await self.act(1, "crown", w.END)
        self.assertEqual(await w.cosmetics(self.db, 1, 1), ("hall", "crown"))
        await asyncio.gather(self.act(1, "claim", w.END), self.act(1, "claim", w.END))
        self.assertEqual(await w.first(self.db, "SELECT sum(amount) FROM coin_history", ()), 1000)
        self.assertEqual(
            await w.first(self.db, "SELECT flakes FROM winter26_players WHERE g=1 AND u=1", ()), 80
        )
        self.assertEqual(await w.progress(self.db, 2, 1), ([0] * 4, [0] * 4))

    async def test_santa_settlement_and_refund(self):
        for g, users in ((1, [1, 2, 3]), (2, [1])):
            for u in users:
                await self.act(u, "ball", w.START, g)
                await self.db.execute("INSERT INTO users(guild_id,user_id,balance) VALUES(?,?,800)", (g, u))
                await self.db.execute("UPDATE winter26_players SET flakes=50 WHERE g=? AND u=?", (g, u))
                await self.db.commit()
                await asyncio.gather(self.act(u, "offer", w.START, g), self.act(u, "offer", w.START, g))
        with patch.object(w, "today", return_value=w.REVEAL):
            await asyncio.gather(w.deliver_gifts(), w.deliver_gifts())
        matches = await w.rows(self.db, "SELECT g,u,recipient FROM winter26_gifts", ())
        self.assertTrue(all((u != recipient) == (g == 1) for g, u, recipient in matches))
        self.assertEqual(len({r for g, u, r in matches if g == 1}), 3)
        self.assertEqual(await w.rows(self.db, "SELECT DISTINCT balance FROM users", ()), [(800,)])
        self.assertEqual(await w.rows(self.db, "SELECT DISTINCT flakes FROM winter26_players", ()), [(50,)])

    async def test_pair_collection_puzzle_and_shop(self):
        await self.db.execute("INSERT INTO marriages VALUES(1,1,2,100)")
        await self.db.commit()
        for i in range(3):
            day = w.START + timedelta(days=i)
            for u in (1, 1, 2):
                await self.act(u, "pairday", day)
            await self.act(1, "answer" + str(w.PUZZLES[i][2]), day)
            await self.act(1, "answer0", day)
        self.assertEqual(await w.pair_days(self.db, 1, 1, 2, 100), 3)
        self.assertEqual(await w.rows(self.db, "SELECT u FROM winter26_rings ORDER BY u", ()), [(1,), (2,)])
        await self.act(1, "strike", day)
        await asyncio.gather(self.act(1, "buy", day), self.act(1, "buy", day))
        await self.act(1, "night", day)
        await self.act(1, "frost", day)
        self.assertEqual(await w.cosmetics(self.db, 1, 1), ("night", "frost"))
        self.assertEqual(await w.first(self.db, "SELECT flakes FROM winter26_players WHERE u=1", ()), 0)

    async def test_pages_and_profile_render(self):
        inter = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=3))

        async def render(inter, **kw):
            kw.pop("key", None)
            view, files = core.build_page(**kw)
            for file in files:
                with Image.open(file.fp) as im:
                    self.assertEqual(im.format, "GIF")
                    self.assertGreater(im.n_frames, 1)
                    im.seek(1)
                    im.load()
                    self.assertGreaterEqual(im.width, 900)
                file.close()
            self.assertTrue(view.children)

        with (
            patch.object(winter, "reply", side_effect=render),
            patch.object(w, "today", return_value=w.START),
        ):
            for page in (
                "ball",
                "archive",
                "raid",
                "santa",
                "pair",
                "shop",
                "game",
                "gifts",
                "dress",
                "strike@2020-01-01",
            ):
                await menu.menu_action("wb:" + page, inter)
        self.assertEqual((await w.progress(self.db, 1, 3))[1], [0] * 4)
        data = {
            "name": "ZANACHKA",
            "title": "Рыцарь",
            "level": 23,
            "have": 420,
            "need": 900,
            "cells": [("Монеты", "3078")],
            "showcase": [("winter:0", *showcase.badge("winter:0"))],
        }
        path = Path(art.__file__).parent / "banners/noble_2.jpg"
        variants = []
        for skin, frame in (("", ""), ("hall", "frost"), ("night", "crown")):
            pic = Image.open(BytesIO(art.profile_card(str(path), dict(data, skin=skin, frame=frame))))
            variants.append(pic.getpixel((25, 30)))
        self.assertEqual(len(set(variants)), 3)
