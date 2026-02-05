#!/usr/bin/env python3
import argparse
import asyncio
import datetime
import json
import logging
import os
import pprint
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from itertools import starmap
from pathlib import Path
from typing import Any, Callable, NamedTuple, Optional, TypeVar, Union

import gi  # type: ignore[import-untyped]

gi.require_version("Notify", "0.7")
from gi.repository import Notify  # type: ignore[import-untyped]

app_name = "nixos-update-reminder"

logger = logging.getLogger(__name__)


@dataclass
class HostConfig:
    argv: list[str]


T_Config = TypeVar("T_Config", bound="Config")


@dataclass
class Config:
    max_time_since_update: datetime.timedelta = datetime.timedelta(weeks=1)
    notification_interval: datetime.timedelta = datetime.timedelta(hours=1)
    nixos_version_timeout: datetime.timedelta = datetime.timedelta(seconds=30)
    http_timeout: datetime.timedelta = datetime.timedelta(seconds=30)
    hosts: dict[str, HostConfig] = field(default_factory=dict)

    @classmethod
    def load(cls: type[T_Config], path: Path) -> T_Config:
        with open(path, "rb") as fp:
            raw = tomllib.load(fp)

        units = [
            "w[week[s]]",
            "d[ay[s]]",
            "m[in[ute[s]]]",
            "s[ec[ond[s]]]",
        ]
        pattern = re.compile(
            r"(?P<int>\d+)(?P<unit>"
            + "|".join(f"(?:{u.replace('[', '(?:').replace(']', ')?')})" for u in units)
            + r")|(?P<white>\s+)|(?P<error>.)"
        )

        timeouts: dict[str, datetime.timedelta] = {}
        for opt in [
            "max_time_since_update",
            "notification_interval",
            "nixos_version_timeout",
            "http_timeout",
        ]:
            try:
                raw_value = raw[opt]
            except KeyError:
                continue
            if isinstance(raw_value, (int, float)):
                if raw_value < 0:
                    raise ValueError(
                        f"cannot parse {opt}: {raw_value!r} is less than zero"
                    )
                value = datetime.timedelta(seconds=raw_value)
            elif isinstance(raw_value, datetime.time):
                value = datetime.timedelta(
                    hours=raw_value.hour,
                    minutes=raw_value.minute,
                    seconds=raw_value.second,
                )
            elif isinstance(raw_value, str):
                kwargs = {"w": 0, "d": 0, "m": 0, "s": 0}
                for m in re.finditer(pattern, raw_value):
                    if m["error"] is not None:
                        example = " ".join(f"${{NUMBER}}{u}" for u in units)
                        raise ValueError(
                            f"cannot parse {opt}: expected {example!r}, not {raw_value!r}"
                        )
                    if m["white"] is not None:
                        continue
                    kwargs[m["unit"][:1]] += int(m["int"], 10)
                value = datetime.timedelta(
                    weeks=kwargs["w"],
                    days=kwargs["d"],
                    minutes=kwargs["m"],
                    seconds=kwargs["s"],
                )
            else:
                raise TypeError(r"cannot parse {opt}: unexpected type")
            timeouts[opt] = value

        hosts: dict[str, HostConfig] = {}
        raw_hosts = raw.get("hosts", {})
        if not isinstance(raw_hosts, dict):
            raise TypeError("cannot parse hosts: expected a table, not {raw_hosts!r}")
        for host, raw_host in raw_hosts.items():
            try:
                argv = raw_host["argv"]
            except KeyError:
                raise ValueError(f"cannot parse hosts.{host!r}: missing option argv")
            if not isinstance(argv, list) or not all(isinstance(a, str) for a in argv):
                raise TypeError(
                    f"cannot parse hosts.{host!r}.argv: expected list of strings, not {argv!r}"
                )
            hosts[host] = HostConfig(argv=argv)

        if not hosts:
            raise ValueError("No hosts to query configured")

        return cls(hosts=hosts, **timeouts)


def get_cache_directory() -> Path:
    try:
        cache_home = Path(os.environ["XDG_CACHE_HOME"])
    except KeyError:
        cache_home = Path(os.environ["HOME"]) / ".cache"
    return cache_home / app_name


def safe_join(a: Path, b: Union[str, os.PathLike[str]]) -> Path:
    c = (a / b).resolve()
    assert c.is_relative_to(a), (
        f"refusing to join paths {a!r} and {b!r}, because {c!r} is no longer below {a!r}"
    )
    return c


async def update_commit_info(commit: str, timeout: Union[int, float]) -> Any:
    def fetch_json(url: str) -> Any:
        logger.debug("querying %s", url)
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"Accept": "application/json"})
        ) as r:
            return json.loads(r.read().decode("utf-8"))

    url = "https://api.github.com/repos/NixOS/nixpkgs/commits/" + urllib.parse.quote(
        commit
    )
    loop = asyncio.get_running_loop()
    try:
        commit_info = await asyncio.wait_for(
            loop.run_in_executor(None, fetch_json, url),
            timeout,
        )
    except TimeoutError:
        logger.error("%s timed out after %r seconds", url, timeout)
        return None
    except urllib.error.HTTPError as e:
        response: Any = e.fp.read(1024)
        try:
            response = response.decode("utf-8")
            response = json.loads(response)
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
        logger.exception(
            "cannot fetch %s, %d %s: %r",
            e.url,
            e.code,
            e.reason,
            response,
        )
        return None

    commit_info_dir = get_cache_directory() / "commit-info"
    commit_info_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=commit_info_dir) as temp:
        temp_file = safe_join(Path(temp), commit)
        with open(temp_file, "x", encoding="utf-8") as fp:
            json.dump(
                commit_info,
                fp,
                indent=2,
                separators=(",", ": "),
            )
            fp.write("\n")
        os.replace(temp_file, safe_join(commit_info_dir, commit))

    return commit_info


async def get_commit_info(commit: str, timeout: Union[int, float]) -> Any:
    commit_info_dir = get_cache_directory() / "commit-info"
    path = safe_join(commit_info_dir, commit)
    try:
        with open(path, "r", encoding="utf-8") as fp:
            commit_info = json.load(fp)
        assert commit_info.get("sha") == commit
    except (AssertionError, FileNotFoundError, json.decoder.JSONDecodeError):
        commit_info = await update_commit_info(commit, timeout=timeout)
    return commit_info


async def get_author_date(
    commit: str,
    timeout: Union[int, float],
    *,
    _get_commit_info: Callable[[str, Union[int, float]], Any] = get_commit_info,
) -> Optional[datetime.datetime]:
    commit_info = await _get_commit_info(commit, timeout)
    if commit_info is None:
        # get_commit_info will only return None when it called update_commit_info
        return None
    try:
        return datetime.datetime.fromisoformat(commit_info["commit"]["author"]["date"])
    except (KeyError, TypeError, ValueError):
        if _get_commit_info is update_commit_info:
            return None
        return await get_author_date(
            commit, timeout=timeout, _get_commit_info=update_commit_info
        )


def get_last_notification_date() -> Optional[datetime.datetime]:
    cache_dir = get_cache_directory()
    try:
        with open(cache_dir / "last-notification", "r", encoding="ascii") as fp:
            chunk = fp.read(len("YYYY-MM-DDTHH:MM:SS.ffffff+HH:MM:SS.ffffff\n"))
            return datetime.datetime.fromisoformat(chunk.split("\n", maxsplit=1)[0])
    except (FileNotFoundError, ValueError, UnicodeDecodeError):
        return None


async def increasingly_kill_process(p: asyncio.subprocess.Process) -> None:
    logger.info("sending SIGHUP to process %d", p.pid)
    p.send_signal(signal.SIGHUP)
    for timeout, signum in [
        # If the process is still running after 1 second send a SIGTERM.
        (1, signal.SIGTERM),
        # If it is still running after another 1 second send a SIGKILL.
        (1, signal.SIGKILL),
    ]:
        try:
            await asyncio.wait_for(
                p.wait(),
                timeout=timeout,
            )
        except TimeoutError:
            # Process is still running.
            logger.info("sending %s to process %d", signal.Signals(signum).name, p.pid)
            p.send_signal(signum)
        else:
            # Process ended.
            break


async def get_nixos_revision(cmd: list[str]) -> str:
    logger.debug("starting process: %s", shlex.join(cmd))
    try:
        p = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
        )
    except BaseException:  # asyncio.CancelledError is a subclass of BaseException
        logger.exception("cannot start process: %s", shlex.join(cmd))
        raise
    try:
        logger.debug("started process %d: %s", p.pid, shlex.join(cmd))
        # TODO read only 21 bytes
        stdout, _ = await p.communicate()
    except BaseException:
        logger.exception("error reading from process %d: %s", p.pid, shlex.join(cmd))
        await increasingly_kill_process(p)
        raise
    finally:
        rc = await p.wait()
        if rc != 0:
            raise subprocess.CalledProcessError(rc, cmd)
    return stdout.strip().decode("ascii")


class RevisionResult(NamedTuple):
    revision_or_message: str
    error: bool = False


async def get_all_nixos_revisions(
    hosts: dict[str, HostConfig],
    timeout: Union[int, float],
) -> dict[str, RevisionResult]:
    results = {}

    async def run_and_store(host: str, conf: HostConfig) -> None:
        try:
            results[host] = RevisionResult(await get_nixos_revision(conf.argv))
        except BaseException as e:
            # get_nixos_revision will send SIGHUP if cancelled and wait for the
            # process to exit. This will most likely raise a CalledProcessError.
            if (
                # only the case if asyncio.create_subprocess_exec is interrupted
                isinstance(e, asyncio.CancelledError)
                # handling of asyncio.create_subprocess_exec probably caused
                # another exception (likely a subprocess.CalledProcessError)
                or isinstance(e.__context__, asyncio.CancelledError)
            ):
                logger.error("querying host %s timed out", host)
                await asyncio.sleep(5)
                results[host] = RevisionResult("query timed out", error=True)
            else:
                logger.exception("cannot query host %s", host)
                results[host] = RevisionResult("cannot query", error=True)

    try:
        await asyncio.wait_for(
            asyncio.gather(*starmap(run_and_store, hosts.items())),
            timeout,
        )
    except TimeoutError:
        pass

    return results


def notify(message: str, now: datetime.datetime) -> None:
    Notify.init(app_name)
    try:
        for line in message.splitlines():
            logger.info("%s", line)
        notif = Notify.Notification.new(
            summary="Some NixOS systems are out of date",
            body=message,
            icon="dialog-warning",
        )
        notif.show()
    finally:
        Notify.uninit()

    cache_dir = get_cache_directory()
    cache_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cache_dir) as temp:
        temp_dir = Path(temp)
        with open(temp_dir / "last-notification", "x", encoding="utf-8") as fp:
            fp.write(now.isoformat(timespec="seconds"))
            fp.write("\n")
        os.replace(temp_dir / "last-notification", cache_dir / "last-notification")


def local_now() -> datetime.datetime:
    dt = datetime.datetime.now(datetime.timezone.utc)
    tzoff = time.localtime(dt.timestamp()).tm_gmtoff
    return dt.replace(tzinfo=datetime.timezone(datetime.timedelta(seconds=tzoff)))


async def async_main() -> None:
    p = argparse.ArgumentParser(
        description="Query NixOS systems for the nixpkgs commit they were built with and display that age to the user.",
    )
    p.add_argument(
        "-c",
        "--config",
        type=Path,
        required=True,
        help="config file",
    )
    p.add_argument(
        "-f",
        "--force-notification",
        action="store_true",
        help="Display a notification even if one was displayed recently.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_const",
        default=logging.INFO,
        const=logging.DEBUG,
        help="Enable debug logging.",
    )
    args = p.parse_args()

    logging.basicConfig(level=args.verbose, stream=sys.stderr)
    config = Config.load(args.config)
    logger.debug("loaded config:\n%s", pprint.pformat(config))

    if not args.force_notification:
        last_notification = get_last_notification_date()
        now = local_now()
        if (
            last_notification is not None
            and now - last_notification < config.notification_interval
        ):
            logger.info("last notification was only %r ago", now - last_notification)
            return

    revisions = await get_all_nixos_revisions(
        config.hosts,
        timeout=config.nixos_version_timeout.total_seconds(),
    )
    author_dates: dict[str, datetime.datetime] = {}

    async def get_and_store(key: str, result: RevisionResult) -> None:
        if result.error:
            return
        author_date = await get_author_date(
            result.revision_or_message,
            timeout=config.http_timeout.total_seconds(),
        )
        if author_date is not None:
            author_dates[key] = author_date

    try:
        await asyncio.gather(*starmap(get_and_store, revisions.items()))
    except TimeoutError:
        pass

    message = []
    now = local_now()
    for host in config.hosts:
        author_date = author_dates.get(host, None)
        if author_date is None:
            res = revisions.get(host, RevisionResult("", error=False))
            message.append(
                "%(host)s: %(message)s"
                % {
                    "host": host,
                    "message": res.revision_or_message if res.error else "unknown",
                }
            )
        else:
            age = now - author_date
            if age >= config.max_time_since_update:
                message.append(
                    "%(host)s: %(days)s days"
                    % {
                        "host": host,
                        "days": age.days,
                    }
                )

    if message:
        notify("\n".join(message), now)
    else:
        logger.debug(
            "all hosts were updated in the last %r",
            config.max_time_since_update,
        )


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
