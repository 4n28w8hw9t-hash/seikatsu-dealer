import asyncio
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import aiosqlite
import art
import bot as entrypoint  # registers commands and hooks

from sd import core, events, ledger, levels, market, menu, moderation, onboarding, quests, reminders, season, showcase
from sd.backups import save_backup


class ProgressionTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.path = root / "economy.db"
        bot = core.bot
        with (
            patch.object(core, "DATA_DIR", str(root)),
            patch.object(core, "DB_PATH", str(self.path)),
            patch.object(core, "GUILD_ID", None),
            patch.object(levels.tick, "start"),
            patch.object(art, "build_all", return_value={}),
            patch.object(bot, "fetch_application_emojis", AsyncMock(return_value=[])),
            patch.object(bot, "create_application_emoji", AsyncMock(side_effect=SimpleNamespace)),
            patch.object(bot.tree, "sync", AsyncMock()),
        ):
            await bot.setup_hook()
        db_path = patch.object(core, "DB_PATH", str(self.path))
        db_path.start()
        self.addCleanup(db_path.stop)
        self.addAsyncCleanup(bot.db.close)
        self.inter = SimpleNamespace(guild_id=7, user=SimpleNamespace(id=1))

    async def test_rings_purchase_profiles_collection_and_dropdown(self):
        from io import BytesIO
        from PIL import Image
        from sd import economy, marriage

        user = SimpleNamespace(id=1, display_name="Seikatsu", roles=[])
        partner = SimpleNamespace(id=2, display_name="Vera", roles=[])
        inter = SimpleNamespace(guild_id=7, guild=SimpleNamespace(id=7), user=user, extras={})
        await core.bot.adjust_staff_balance(7, 1, 6000)
        before = (await core.bot.get_user(7, 1))["balance"]
        with patch.object(marriage, "reply", AsyncMock()) as sent:
            await asyncio.gather(marriage.ring_action(inter, "buy:gold"), marriage.ring_action(inter, "buy:gold"))
            self.assertEqual(await marriage.get_rings(7, 1), {"gold": 1})
            rows = sent.call_args.kwargs["rows"]
            self.assertIn("profile", rows[1])
            self.assertEqual([opt.value for opt in rows[0][0].options], ["buy:silver", "buy:ruby"])
        self.assertEqual((await core.bot.get_user(7, 1))["balance"], before - 1500)

        async def profile(target):
            with (
                patch.object(economy, "reply", AsyncMock()) as sent,
                patch.object(economy, "member_name", AsyncMock(return_value="Пара")),
                patch.object(economy, "_ranked", AsyncMock(return_value=[])),
                patch.object(art, "profile_card", wraps=art.profile_card) as renderer,
            ):
                await economy.profile.callback(inter, target)
                data = renderer.call_args.args[1]
                image = sent.call_args.kwargs["image"][1]
                return data["rings"], Image.open(BytesIO(image)).height

        self.assertEqual(await profile(user), ([("Золото", "ring_gold")], 630))
        async with core.bot.transaction() as db:
            await db.execute("INSERT INTO marriages(guild_id,a,b,since,ring,bond_ring,xp) VALUES(7,1,2,42,'ruby','ruby',0)")
        self.assertEqual(await marriage.purchase_ring(7, 2, "gold"), "owned")
        self.assertEqual(await profile(partner), ([], 600))
        custom = {"sd_ring_silver": "<:sd_ring_silver:123456789012345678>", "sd_ring_gold": "<:sd_ring_gold:234567890123456789>"}
        with patch.object(core.bot, "emo", custom):
            select = marriage.ring_action_select("ruby", {"ruby", "gold"}, paired=True)
            self.assertEqual([(opt.value, opt.emoji.id) for opt in select.options],
                             [("buy:silver", 123456789012345678), ("wear:gold", 234567890123456789)])
            self.assertEqual(marriage.gift_ring_select({"gold": 1}).options[0].emoji.id, 234567890123456789)
        with (
            patch.object(marriage, "reply", AsyncMock()),
            patch.object(marriage, "member_name", AsyncMock(return_value="Vera")),
        ):
            await marriage.ring_action(inter, "gift:gold")
            await marriage.ring_action(inter, "wear:gold")
        self.assertEqual(await profile(partner), ([("Золото", "ring_gold")], 630))
        self.assertEqual(await profile(user), ([], 600))
        self.assertEqual((await marriage.get_marriage(7, 1))["ring"], "gold")

    async def test_quest_reward_is_paid_once(self):
        async with core.bot.transaction() as db:
            await db.execute(
                "INSERT INTO weekly_quests(guild_id,user_id,week,work,voice,daily) VALUES(7,1,'2026-11-30',2,720,3)"
            )
        with patch.object(quests, "week_window", return_value=("2026-11-30", 0)), patch.object(
            quests, "show", AsyncMock()
        ):
            await asyncio.gather(quests.claim(self.inter), quests.claim(self.inter))
        self.assertEqual((await core.bot.get_user(7, 1))["balance"], core.START_BALANCE + quests.REWARD)

    async def test_staff_debit_and_role_refund_are_safe(self):
        await core.bot.adjust_staff_balance(7, 1, 200)
        before = (await core.bot.get_user(7, 1))["balance"]
        self.assertFalse(await core.bot.adjust_staff_balance(7, 1, -(before + 1)))
        role = {"id": 99, "role_id": 100, "price": 200, "name": "Цвет"}
        self.assertEqual(await market.reserve_role_purchase(7, 1, role), "reserved")
        self.assertEqual(await market.settle_role_purchase(7, 1, 99, granted=False), "refunded")
        self.assertIsNone(await market.settle_role_purchase(7, 1, 99, granted=False))
        self.assertEqual((await core.bot.get_user(7, 1))["balance"], before)

    async def test_event_cutoff_and_badge(self):
        active = datetime(2026, 12, 7, 23, 59, tzinfo=quests.COURT_TZ).timestamp()
        closed = datetime(2026, 12, 8, 0, 0, tzinfo=quests.COURT_TZ).timestamp()
        async with core.bot.transaction() as db:
            for _ in range(events.PERSONAL_GOAL):
                await events.record_contribution(db, 7, 1, active)
            await events.record_contribution(db, 7, 1, closed)
            await db.execute("INSERT INTO court_events VALUES(7,'2026-12',2,?,0)",
                             (events.GOAL-events.PERSONAL_GOAL,))
        with patch.object(events, "event_window", return_value=("2026-12", int(closed), False)), patch.object(
            events, "show", AsyncMock()
        ):
            await asyncio.gather(events.claim(self.inter), events.claim(self.inter))
        self.assertEqual(await events.event_progress(core.bot.db, 7, "2026-12", 1),
                         (events.GOAL, events.PERSONAL_GOAL, 1))
        self.assertIn("court:event", await showcase.earned(7, 1))

    async def test_first_day_badge_requires_all_steps(self):
        await onboarding.start(7, 1)
        await core.bot.get_user(7, 1)
        await onboarding.open_profile(7, 1)
        await onboarding.unlock(self.inter)
        self.assertNotIn(onboarding.BADGE, await showcase.earned(7, 1))
        await core.bot.set_field(7, 1, path="faith", last_daily=1_900_000_000)
        await onboarding.unlock(self.inter)
        self.assertIn(onboarding.BADGE, await showcase.earned(7, 1))

    async def test_archive_preserves_personal_place(self):
        async with core.bot.transaction() as db:
            for uid, xp in enumerate((300, 250, 200, 150), start=1):
                await db.execute("INSERT INTO season_xp VALUES(7,'2026-11',?,?)", (uid, xp))
        guild = SimpleNamespace(id=7, unavailable=False, chunked=True,
                                get_member=lambda _:SimpleNamespace(bot=False))
        with patch.object(season, "month_window", return_value=("2026-12", 0)), patch.object(
            core.bot, "get_guild", return_value=guild
        ):
            await season.close_seasons()
            await season.close_seasons()
        async with core.bot.db.execute("SELECT place FROM season_results WHERE user_id=4") as cur:
            self.assertEqual(await cur.fetchone(), (4,))

    async def test_dashboard_and_wallet_filters(self):
        user = SimpleNamespace(id=1, display_name="Участник", roles=[])
        self.inter.user = user
        self.inter.guild = SimpleNamespace(id=7)
        week = "2026-11-30"
        async with core.bot.transaction() as db:
            await db.execute("INSERT INTO weekly_quests VALUES(7,1,?,2,440,3,0)", (week,))
            await ledger.record(db, 7, 1, 100, "daily")
            await ledger.record(db, 7, 1, -300, "ring")
        with patch.object(quests, "week_window", return_value=(week, 0)), patch.object(
            menu, "send_panel", AsyncMock()
        ) as panel:
            await menu.dashboard(self.inter)
        actions = panel.await_args.kwargs["rows"][1]
        self.assertIn("Поручения · 2/3", [getattr(button, "label", "") for button in actions])
        with patch.object(ledger, "send_card", AsyncMock()) as send:
            await ledger.show(self.inter, category="purchases")
        description = send.await_args.args[1].description
        self.assertIn("Покупка кольца", description)
        self.assertNotIn("Ежедневная награда", description)

    async def test_reminder_is_opt_in_and_attempted_once(self):
        member = SimpleNamespace(send=AsyncMock())
        guild = SimpleNamespace(name="Двор", get_member=lambda _:member)
        sunday = datetime(2026, 12, 6, 14, tzinfo=quests.COURT_TZ)
        self.assertFalse(await reminders.enabled(7, 1))
        with patch.object(quests, "show", AsyncMock()):
            await reminders.toggle(self.inter)
        with patch.object(core.bot, "get_guild", return_value=guild), patch.object(
            reminders, "datetime", SimpleNamespace(now=lambda _:sunday)
        ), patch.object(reminders, "_last_scan", None):
            await reminders.send_due()
            reminders._last_scan = None
            await reminders.send_due()
        member.send.assert_awaited_once()

    async def test_moderation_history_filter(self):
        self.inter.response = SimpleNamespace(is_done=lambda:True)
        async with core.bot.transaction() as db:
            await db.execute("INSERT INTO moderation_events VALUES(100,7,1,2,'warn','Флуд',NULL,1800000000)")
            await db.execute("INSERT INTO moderation_events VALUES(101,7,1,2,'ban','Другая причина',NULL,1800000000)")
        with patch.object(moderation, "edit_staff_page", AsyncMock()) as edit:
            await moderation.ModerationLogView(2, subject_id=1, category="warn").show(self.inter)
        description = edit.await_args.args[1].description
        self.assertIn("Флуд", description)
        self.assertNotIn("Другая причина", description)

    async def test_backup_contains_live_wallet(self):
        await core.bot.adjust_staff_balance(7, 1, 25)
        await save_backup(self.path)
        copy, = self.path.parent.joinpath("backups").glob("*.sqlite")
        async with aiosqlite.connect(copy) as db, db.execute("SELECT balance FROM users") as cur:
            self.assertEqual(await cur.fetchone(), (core.START_BALANCE+25,))
