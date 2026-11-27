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
                # A deposit recorded by the release preceding free keepsake exchange.
                await self.db.execute("UPDATE users SET balance=balance-500 WHERE guild_id=? AND user_id=?",(g,u))
                await self.db.execute("UPDATE winter26_players SET flakes=0 WHERE g=? AND u=?",(g,u))
                await self.db.execute("INSERT INTO winter26_gifts(g,u) VALUES(?,?)",(g,u))
                await self.db.commit()
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

    async def test_guest_story_catchup_and_heirlooms(self):
        from sd import winter_guests as guests
        from sd.snowballs import inventory
        g, u = 1, 7
        await self.act(u, "ball", w.START)
        async with core.bot.transaction() as db:
            async def solve(i, day):
                return await guests.journal(db,g,u,day,f"{u}.{i}.{guests.CHAPTERS[i][3]}")
            await solve(0,w.START)
            await solve(1,w.START)
            await solve(0,w.START)
            finale = w.END - timedelta(days=1)
            await guests.journal(db,g,u,finale,"8.1.2")
            self.assertEqual(await inventory(db,g,u), {"shard0"})
            for i in range(1,4):
                await solve(i,finale)
            await solve(3,finale)
            self.assertEqual(await w.first(db,"SELECT flakes FROM winter26_players WHERE g=? AND u=?",(g,u)),40)
            for _ in range(2):
                await guests.workshop(db,g,u,"brooch",None,False,False)
            self.assertIn("moon_brooch", await inventory(db,g,u))
            marriage=(7,8,12345)
            await guests.workshop(db,g,u,"engrave",marriage,True,False)
            self.assertFalse(await w.first(db,"SELECT 1 FROM winter26_engraving",()))
            for _ in range(2):
                await guests.workshop(db,g,u,"engrave",marriage,True,True)
            self.assertEqual(await w.first(db,"SELECT COUNT(*) FROM winter26_engraving",()),1)

    async def test_pages_and_profile_render(self):
        inter = SimpleNamespace(guild_id=1, user=SimpleNamespace(id=3))

        async def render(inter, **kw):
            kw.pop("key", None)
            kw.pop("allowed_mentions", None)
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
                "siege",
                "pack",
                "store",
                "itemlace",
                "journal",
                "workshop",
                "itemyard",
                "itemrings",
                "itemaurora",
                "duels",
                "relay",
                "princess",
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

    async def test_snow_baskets_and_shared_targets(self):
        from sd import snowballs as snow

        async def launch(u, day, used, choice):
            async with core.bot.transaction() as db:
                await w.act(db, 1, u, "ball", day)
                await snow.pack(db, 1, u, day)
                return await snow.throw(db, 1, u, day, choice, f"{day}.{u}.{used}")

        for idx in range(4):
            day = w.START + timedelta(days=7 * idx)
            for used in range(5):
                choice = used % 3 if idx == 3 else snow.target(1, 1, day, used)
                await asyncio.gather(launch(1, day, used, choice), launch(1, day, used, choice))
                if idx == 0 and used == 2:
                    msg = await launch(2, day, 0, (snow.target(1, 2, day, 0) + 1) % 3)
                    self.assertIn("брешь", msg)
            self.assertEqual((await snow.basket(self.db, 1, 1, day))[0], 5)
        self.assertEqual(
            await w.first(self.db, "SELECT flakes FROM winter26_players WHERE g=1 AND u=1", ()), 163
        )
        self.assertIn("snowball", await snow.inventory(self.db, 1, 1))
        self.assertGreater((await snow.fort(self.db, 1, 3))[3], 0)
        self.assertIn("Обнови", await launch(1, w.END, 0, 0))

    async def test_store_relay_and_princess(self):
        from sd import snowballs as snow

        async with core.bot.transaction() as db:
            await w.act(db, 1, 1, "ball", w.START)
            await db.execute("INSERT INTO marriages VALUES(1,1,2,14)")
            await db.execute("UPDATE winter26_players SET flakes=460")
            for step, u in enumerate((1, 2, 2, 1)):
                await snow.relay(db, 1, u, w.START, f"14.{step}")
            for key in ("lace", "yard", "aurora", "rings", "rings"):
                await snow.purchase(db, 1, 1, key, w.START)
            self.assertEqual(await w.first(db, "SELECT flakes FROM winter26_players WHERE u=1", ()), 0)
            self.assertEqual(await w.first(db, "SELECT COUNT(*) FROM winter26_rings", ()), 2)
            await snow.equip(db, 1, 1, "lace")
            await snow.equip(db, 1, 1, "yard")
            self.assertEqual(await w.cosmetics(db, 1, 1), ("yard", "lace"))
            await snow.princess(db, 1, 1, w.START)
            self.assertNotIn("princess", await snow.inventory(db, 1, 1))
            await snow.princess(db, 1, 1, w.REVEAL)
            await snow.princess(db, 1, 1, w.REVEAL)
            self.assertEqual(await w.first(db, "SELECT SUM(amount) FROM coin_history", ()), 250)

    async def test_three_private_duel_rounds(self):
        from sd import snowballs as snow

        async with core.bot.transaction() as db:
            await snow.invite(db, 1, 11, 22, w.START)
            ident = (await snow.duel(db, 1, 22))[0]
            await snow.duel_move(db, 1, 11, "accept", f"{ident}.1", -1, w.START)
            self.assertEqual((await snow.duel(db, 1, 11))[3], "invite")
            await snow.duel_move(db, 1, 22, "accept", f"{ident}.1", -1, w.START)
            for turn in range(1, 4):
                token = f"{ident}.{turn}"
                await snow.duel_move(db, 1, 11, "move", token, 0, w.START)
                await snow.duel_move(db, 1, 11, "move", token, 8, w.START)
                await snow.duel_move(db, 1, 22, "move", token, 3, w.START)
            result = await snow.duel(db, 1, 22, latest=True)
            self.assertEqual((result[3], result[7], result[8]), ("done", 3, 0))
            self.assertIsNone(await snow.duel(db, 1, 11))

    async def test_free_secret_santa_and_sealed_invitation(self):
        from unittest.mock import AsyncMock
        inter=SimpleNamespace(guild_id=1,user=SimpleNamespace(id=12))
        with patch.object(w,"today",return_value=w.START-timedelta(days=1)), patch.object(winter,"reply",new_callable=AsyncMock) as send:
            for key in ("ball","store","pack","wrap_book","aim0@old","unwrap"):
                await winter.show(inter,key)
                self.assertEqual(send.await_args.kwargs["rows"],[["menu"]])
            self.assertEqual(await w.first(self.db,"SELECT count(*) FROM winter26_players",()),0)
        await self.act(1,"wrap_book",w.START)
        await self.act(1,"wrap_rose",w.START)
        await self.act(2,"wrap_chime",w.START)
        await self.act(3,"wrap_book",w.START,2)
        with patch.object(w,"today",return_value=w.REVEAL):
            await asyncio.gather(w.deliver_gifts(),w.deliver_gifts())
        self.assertEqual(await w.rows(self.db,"SELECT u,item FROM snow_items WHERE g=1 ORDER BY u",()),[(1,"santa_chime"),(2,"santa_rose")])
        solo=await w.first(self.db,"SELECT item FROM snow_items WHERE g=2",())
        self.assertIn(solo,("santa_chime","santa_rose"))
        self.assertEqual(await w.first(self.db,"SELECT count(*) FROM coin_history",()),0)
        self.assertEqual(await w.first(self.db,"SELECT SUM(flakes) FROM winter26_players",()),0)
        await self.act(2,"wrap_rose",w.REVEAL)
        self.assertEqual(await w.first(self.db,"SELECT keepsake FROM winter26_parcels WHERE g=1 AND u=2",()),"chime")
