"""Poll the switch while a browser is on the demo page."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.aoscx import AoscxError, AoscxSession, RawClient, RawPort, SwitchTarget, normalize_switch_host
from app.clearpass import ClearPassError, ClearPassSession, ClearPassTarget, EndpointInfo
from app.db import get_settings
from app.junos import JunosError, JunosSession, JunosTarget
from app.mist import MistError, MistSession, MistTarget
from app.translate import mark_mist, ports_from_junos

logger = logging.getLogger("colorless.poll")


@dataclass
class PollStatus:
    switch_ok: bool = False
    switch_error: str = ""
    polled_at: str | None = None
    hostname: str = ""
    software_version: str = ""
    raw_ports: list[RawPort] | None = None
    clearpass_ok: bool = False
    clearpass_error: str = ""
    ex_ok: bool = False
    ex_error: str = ""
    ex_polled_at: str | None = None
    ex_hostname: str = ""
    ex_version: str = ""
    ex_ports: list[RawPort] | None = None
    cache: dict[str, tuple[float, EndpointInfo]] = field(default_factory=dict)


def viewer_is_active(last_view: float, interval: float) -> bool:
    idle_for = max(8.0, float(interval) * 4)
    return (time.monotonic() - last_view) <= idle_for


def mac_key(mac: str) -> str:
    return "".join(ch for ch in mac.lower() if ch in "0123456789abcdef")


class Poller:
    def __init__(self, app) -> None:
        self.app = app
        self.switch: AoscxSession | None = None
        self.switch_fp: tuple | None = None
        self.clearpass: ClearPassSession | None = None
        self.clearpass_fp: tuple | None = None
        self.mist: MistSession | None = None
        self.mist_fp: tuple | None = None
        self.junos: JunosSession | None = None
        self.junos_fp: tuple | None = None
        self._ex_source = ""
        self._logged = ""
        self._ex_logged = ""

    async def close(self) -> None:
        if self.switch is not None:
            await self.switch.close()
            self.switch = None
        if self.clearpass is not None:
            await self.clearpass.close()
            self.clearpass = None
        if self.mist is not None:
            await self.mist.close()
            self.mist = None
        if self.junos is not None:
            await self.junos.close()
            self.junos = None

    async def run(self) -> None:
        stop: asyncio.Event = self.app.state.stop
        while not stop.is_set():
            settings = get_settings(self.app.state.db_path)
            interval = float(settings["poll_interval_sec"])
            watching = viewer_is_active(self.app.state.last_view, interval)
            cx_on = bool(settings["switch_host"])
            source = ex_source(settings)
            if not cx_on:
                await self._clear_cx()
            if not source:
                await self._clear_ex()
                self._ex_source = ""
            if not watching or not (cx_on or source):
                await sleep_or_wake(self.app.state.wake, 1)
                continue
            if cx_on:
                try:
                    await self.poll_once(settings)
                except asyncio.CancelledError:
                    raise
                except AoscxError as exc:
                    self._fail(str(exc))
                except Exception:
                    logger.warning("switch poll failed")
                    self._fail("Poll failed")
            if source:
                try:
                    await self.poll_active_ex(settings)
                except asyncio.CancelledError:
                    raise
                except (MistError, JunosError) as exc:
                    self._fail_ex(str(exc))
                except Exception:
                    logger.warning("ex poll failed")
                    self._fail_ex("EX poll failed")
            await sleep_or_wake(self.app.state.wake, interval)

    async def poll_active_ex(self, settings: dict) -> None:
        source = ex_source(settings)
        if source != self._ex_source:
            self._reset_ex_view()
            self._ex_source = source
        if source == "junos":
            await self._close_mist()
            await self.poll_junos(settings)
            return
        if source == "mist":
            await self._close_junos()
            await self.poll_ex(settings)

    async def poll_junos(self, settings: dict) -> None:
        fingerprint = (
            settings.get("junos_host") or "",
            int(settings.get("junos_port") or 3443),
            settings.get("junos_username") or "",
            settings.get("junos_password") or "",
            bool(settings.get("junos_verify_tls")),
        )
        if self.junos is None or fingerprint != self.junos_fp:
            if self.junos is not None:
                await self.junos.close()
            self.junos = JunosSession(
                JunosTarget(
                    host=str(settings.get("junos_host") or ""),
                    port=int(settings.get("junos_port") or 3443),
                    username=str(settings.get("junos_username") or ""),
                    password=str(settings.get("junos_password") or ""),
                    verify_tls=bool(settings.get("junos_verify_tls")),
                )
            )
            self.junos_fp = fingerprint
        hostname, version, links, sessions = await self.junos.read_access()
        self._store_ex(hostname, version, ports_from_junos(links, sessions))

    async def poll_ex(self, settings: dict) -> None:
        fingerprint = (
            settings["mist_host"],
            settings["mist_api_token"],
            bool(settings["mist_verify_tls"]),
        )
        if self.mist is None or fingerprint != self.mist_fp:
            if self.mist is not None:
                await self.mist.close()
            self.mist = MistSession(
                MistTarget(
                    host=settings["mist_host"] or "api.mist.com",
                    api_token=settings["mist_api_token"],
                    verify_tls=bool(settings["mist_verify_tls"]),
                )
            )
            self.mist_fp = fingerprint
        hostname, version, ports = await self.mist.poll_access_ports(
            settings["ex_site_id"],
            settings["ex_switch_mac"],
        )
        self._store_ex(hostname, version, mark_mist(ports))

    def _store_ex(self, hostname: str, version: str, ports: list[RawPort]) -> None:
        status: PollStatus = self.app.state.poll
        status.ex_ports = ports
        status.ex_ok = True
        status.ex_error = ""
        status.ex_hostname = hostname
        status.ex_version = version
        status.ex_polled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if self._ex_logged:
            logger.info("ex poll recovered")
            self._ex_logged = ""

    def _reset_ex_view(self) -> None:
        status: PollStatus = self.app.state.poll
        status.ex_ok = False
        status.ex_error = ""
        status.ex_ports = None
        status.ex_hostname = ""
        status.ex_version = ""
        status.ex_polled_at = None

    async def poll_once(self, settings: dict) -> None:
        fingerprint = (
            settings["switch_host"],
            settings["switch_port"],
            settings["switch_username"],
            settings["switch_password"],
            settings["api_version"],
            bool(settings["switch_verify_tls"]),
            int(settings["vsf_member"]),
        )
        if self.switch is None or fingerprint != self.switch_fp:
            if self.switch is not None:
                await self.switch.close()
            host, port = normalize_switch_host(settings["switch_host"], int(settings["switch_port"]))
            self.switch = AoscxSession(
                SwitchTarget(
                    host=host,
                    port=port,
                    username=settings["switch_username"],
                    password=settings["switch_password"],
                    api_version=settings["api_version"],
                    verify_tls=bool(settings["switch_verify_tls"]),
                    vsf_member=int(settings["vsf_member"]),
                )
            )
            self.switch_fp = fingerprint
        hostname, version, ports = await self.switch.poll_access_ports()
        await self._enrich(settings, ports)
        status: PollStatus = self.app.state.poll
        status.raw_ports = ports
        status.switch_ok = True
        status.switch_error = ""
        status.hostname = hostname
        status.software_version = version
        status.polled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if self._logged:
            logger.info("switch poll recovered")
            self._logged = ""

    async def _enrich(self, settings: dict, ports: list[RawPort]) -> None:
        status: PollStatus = self.app.state.poll
        if not settings["clearpass_host"]:
            status.clearpass_ok = False
            status.clearpass_error = ""
            return
        if not settings["clearpass_client_id"] or not settings["clearpass_client_secret"]:
            status.clearpass_ok = False
            status.clearpass_error = "ClearPass client ID and secret are required"
            return
        fingerprint = (
            settings["clearpass_host"],
            settings["clearpass_client_id"],
            settings["clearpass_client_secret"],
            bool(settings["clearpass_verify_tls"]),
        )
        if self.clearpass is None or fingerprint != self.clearpass_fp:
            if self.clearpass is not None:
                await self.clearpass.close()
            self.clearpass = ClearPassSession(
                ClearPassTarget(
                    host=settings["clearpass_host"],
                    client_id=settings["clearpass_client_id"],
                    client_secret=settings["clearpass_client_secret"],
                    verify_tls=bool(settings["clearpass_verify_tls"]),
                )
            )
            self.clearpass_fp = fingerprint
        pending: list[RawClient] = []
        now = time.monotonic()
        for port in ports:
            for client in port.clients:
                key = mac_key(client.mac)
                cached = status.cache.get(key)
                if cached and _cache_fresh(cached, now):
                    _apply_endpoint(client, cached[1])
                    continue
                if key:
                    pending.append(client)
        if not pending:
            status.clearpass_ok = True
            status.clearpass_error = ""
            return
        errors: list[str] = []
        semaphore = asyncio.Semaphore(4)

        async def lookup(client: RawClient) -> None:
            try:
                async with semaphore:
                    info = await self.clearpass.endpoint(client.mac)  # type: ignore[union-attr]
            except ClearPassError as exc:
                errors.append(str(exc))
                return
            status.cache[mac_key(client.mac)] = (time.monotonic(), info)
            _apply_endpoint(client, info)

        await asyncio.gather(*(lookup(client) for client in pending[:16]))
        if errors:
            status.clearpass_ok = False
            status.clearpass_error = errors[0]
        else:
            status.clearpass_ok = True
            status.clearpass_error = ""

    def _fail(self, message: str) -> None:
        status: PollStatus = self.app.state.poll
        status.switch_ok = False
        status.switch_error = message
        if message != self._logged:
            logger.warning("switch poll: %s", message)
            self._logged = message

    def _fail_ex(self, message: str) -> None:
        status: PollStatus = self.app.state.poll
        status.ex_ok = False
        status.ex_error = message
        if message != self._ex_logged:
            logger.warning("ex poll: %s", message)
            self._ex_logged = message

    async def _clear_cx(self) -> None:
        status: PollStatus = self.app.state.poll
        status.switch_ok = False
        status.switch_error = ""
        status.raw_ports = None
        status.hostname = ""
        status.software_version = ""
        status.polled_at = None
        status.clearpass_ok = False
        status.clearpass_error = ""
        if self.switch is not None:
            await self.switch.close()
            self.switch = None
            self.switch_fp = None
        if self.clearpass is not None:
            await self.clearpass.close()
            self.clearpass = None
            self.clearpass_fp = None

    async def _clear_ex(self) -> None:
        status: PollStatus = self.app.state.poll
        status.ex_ok = False
        status.ex_error = ""
        status.ex_ports = None
        status.ex_hostname = ""
        status.ex_version = ""
        status.ex_polled_at = None
        if self.mist is not None:
            await self.mist.close()
            self.mist = None
            self.mist_fp = None
        await self._close_junos()

    async def _close_mist(self) -> None:
        if self.mist is None:
            return
        await self.mist.close()
        self.mist = None
        self.mist_fp = None

    async def _close_junos(self) -> None:
        if self.junos is None:
            return
        await self.junos.close()
        self.junos = None
        self.junos_fp = None


def junos_ready(settings: dict) -> bool:
    return bool(
        str(settings.get("junos_host") or "").strip()
        and str(settings.get("junos_username") or "").strip()
        and settings.get("junos_password")
    )


def mist_ready(settings: dict) -> bool:
    return bool(
        settings.get("ex_site_id")
        and settings.get("ex_switch_mac")
        and settings.get("mist_api_token")
    )


def saved_ex_choice(settings: dict) -> str:
    choice = str(settings.get("ex_source_choice") or "").strip().casefold()
    if choice in {"mist", "junos"}:
        return choice
    return ""


def display_ex_choice(settings: dict) -> str:
    """The radio to show. A saved choice wins. Otherwise show whichever source is ready."""
    saved = saved_ex_choice(settings)
    if saved:
        return saved
    if junos_ready(settings):
        return "junos"
    return "mist"


def ex_source(settings: dict) -> str:
    """The one EX poller. A saved choice stays on that source even when the other is filled in."""
    choice = saved_ex_choice(settings)
    if choice == "junos":
        return "junos" if junos_ready(settings) else ""
    if choice == "mist":
        return "mist" if mist_ready(settings) else ""
    if junos_ready(settings):
        return "junos"
    if mist_ready(settings):
        return "mist"
    return ""


def _cache_fresh(entry: tuple[float, EndpointInfo], now: float) -> bool:
    info = entry[1]
    ttl = 300.0 if (info.device_type or info.device_name or info.ip_address or info.device_category) else 60.0
    return now - entry[0] < ttl


def _apply_endpoint(client: RawClient, info: EndpointInfo) -> None:
    if info.device_type:
        client.device_type = info.device_type
    if info.device_name:
        client.device_name = info.device_name
    if info.ip_address:
        client.ip_address = info.ip_address
    if info.device_category:
        client.device_category = info.device_category
    if info.device_family:
        client.device_family = info.device_family


async def sleep_or_wake(event: asyncio.Event, timeout: float) -> None:
    try:
        await asyncio.wait_for(event.wait(), timeout)
    except TimeoutError:
        pass
    event.clear()
