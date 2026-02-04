import asyncio
import logging
import random
import string
import unittest
import unittest.mock
from typing import Any

from nixos_update_reminder import HostConfig, RevisionResult, get_all_nixos_revisions


class TestNixosUpdateReminder(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        logging.basicConfig(handlers=[logging.NullHandler()])

    async def test_get_all_nixos_revisions(self) -> None:
        """get_all_nixos_revisions: success"""
        message = "".join(random.choices(string.ascii_letters, k=20))
        self.assertEqual(
            await get_all_nixos_revisions(
                {"localhost": HostConfig(argv=["echo", message])},
                timeout=30,
            ),
            {"localhost": RevisionResult(message, error=False)},
        )

    async def test_get_all_nixos_revisions_timeout(self) -> None:
        """get_all_nixos_revisions: command timeout"""
        self.assertEqual(
            await get_all_nixos_revisions(
                {"localhost": HostConfig(argv=["sleep", "10"])},
                timeout=1,
            ),
            {"localhost": RevisionResult("query timed out", error=True)},
        )

    async def test_get_all_nixos_revisions_timeout_create_subprocess_exec(self) -> None:
        """get_all_nixos_revisions: timeout during asyncio.create_subprocess_exec"""

        async def create_subprocess_exec(*args: Any, **kwargs: Any) -> None:
            while True:
                await asyncio.sleep(3600)

        with unittest.mock.patch(
            "asyncio.create_subprocess_exec", create_subprocess_exec
        ):
            self.assertEqual(
                await get_all_nixos_revisions(
                    {"localhost": HostConfig(argv=["true"])},
                    timeout=1,
                ),
                {"localhost": RevisionResult("query timed out", error=True)},
            )

    async def test_get_all_nixos_revisions_fail(self) -> None:
        """get_all_nixos_revisions: error"""
        self.assertEqual(
            await get_all_nixos_revisions(
                {"localhost": HostConfig(argv=["false"])},
                timeout=30,
            ),
            {"localhost": RevisionResult("cannot query", error=True)},
        )

    async def test_get_all_nixos_revisions_sighup(self) -> None:
        """get_all_nixos_revisions: killed by signal"""
        self.assertEqual(
            await get_all_nixos_revisions(
                {"localhost": HostConfig(argv=["sh", "-c", "exec kill -HUP $$"])},
                timeout=30,
            ),
            {"localhost": RevisionResult("cannot query", error=True)},
        )
