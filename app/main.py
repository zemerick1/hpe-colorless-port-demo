"""HTTP API and pages for the single colorless-port demo."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.aoscx import AoscxError, AoscxSession, SwitchTarget, normalize_switch_host
from app.clearpass import ClearPassError, ClearPassSession, ClearPassTarget
from app.db import (
    default_db_path,
    get_mist_roles,
    get_profiles,
    get_settings,
    init_db,
    merge_named_colors,
    public_config,
    resolve_secret,
    save_config,
)
from app.junos import JunosError, JunosSession, JunosTarget
from app.mist import MistError, MistSession, MistTarget, check_mist
from app.poller import PollStatus, Poller, display_ex_choice, ex_source, viewer_is_active
from app.snapshot import build_snapshot
from app.translate import mark_mist, ports_from_junos

JUNOS_FILTER_NOTE = "Ethernet-switching firewall filter on the switch."
MIST_TEMPLATE_NOTE = "Radius-group role on the Mist switch template."

logger = logging.getLogger("colorless")
STATIC = Path(__file__).resolve().parents[1] / "static"


class RoleIn(BaseModel):
    id: int | None = None
    name: str
    display_name: str = ""
    description: str = ""
    port_color: str = ""
    legend_order: int = 0
    no_popover: bool = False
    special: str = ""


class ProfileIn(BaseModel):
    id: int | None = None
    name: str = ""
    display_name: str = ""
    description: str = ""
    port_color: str = ""
    legend_order: int = 0
    no_popover: bool = False


class ConfigIn(BaseModel):
    switch_host: str = ""
    switch_port: int = 443
    switch_username: str = ""
    switch_password: str = ""
    api_version: str = "v10.16"
    switch_verify_tls: bool = False
    vsf_member: int = 1
    clearpass_host: str = ""
    clearpass_client_id: str = ""
    clearpass_client_secret: str = ""
    clearpass_verify_tls: bool = False
    mist_host: str = "api.mist.com"
    mist_api_token: str = ""
    mist_verify_tls: bool = True
    ex_site_id: str = ""
    ex_switch_mac: str = ""
    junos_host: str = ""
    junos_port: int = 3443
    junos_username: str = ""
    junos_password: str = ""
    junos_verify_tls: bool = False
    ex_source_choice: str = ""
    poll_interval_sec: float = 1
    screen_interval_sec: float = 0.5
    show_device_name_on_mac: bool = True
    visualize_unknown: bool = True
    hide_previous_popovers: bool = True
    roles: list[RoleIn] = Field(default_factory=list)
    profiles: list[ProfileIn] | None = None
    mist_roles: list[ProfileIn] | None = None


class SwitchTestIn(BaseModel):
    switch_host: str = ""
    switch_port: int = 443
    switch_username: str = ""
    switch_password: str = ""
    api_version: str = "v10.16"
    switch_verify_tls: bool = False
    vsf_member: int = 1


class ClearPassTestIn(BaseModel):
    clearpass_host: str = ""
    clearpass_client_id: str = ""
    clearpass_client_secret: str = ""
    clearpass_verify_tls: bool = False


class MistTestIn(BaseModel):
    mist_host: str = "api.mist.com"
    mist_api_token: str = ""
    mist_verify_tls: bool = True


class ExTestIn(BaseModel):
    mist_host: str = "api.mist.com"
    mist_api_token: str = ""
    mist_verify_tls: bool = True
    ex_site_id: str = ""
    ex_switch_mac: str = ""


class JunosTestIn(BaseModel):
    junos_host: str = ""
    junos_port: int = 3443
    junos_username: str = ""
    junos_password: str = ""
    junos_verify_tls: bool = False


class JunosLoadIn(JunosTestIn):
    mist_roles: list[ProfileIn] = Field(default_factory=list)


class MistTemplateLoadIn(BaseModel):
    mist_host: str = "api.mist.com"
    mist_api_token: str = ""
    mist_verify_tls: bool = True
    ex_site_id: str = ""
    mist_roles: list[ProfileIn] = Field(default_factory=list)


def create_app(db_path=None) -> FastAPI:
    path = Path(db_path) if db_path is not None else default_db_path()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_db(path)
        app.state.db_path = path
        app.state.poll = PollStatus()
        app.state.last_view = 0.0
        app.state.wake = asyncio.Event()
        app.state.stop = asyncio.Event()
        poller = Poller(app)
        app.state.poller = poller
        task = None
        import os

        if os.environ.get("COLORLESS_POLL", "1") != "0":
            task = asyncio.create_task(poller.run())
        try:
            yield
        finally:
            app.state.stop.set()
            app.state.wake.set()
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            await poller.close()

    app = FastAPI(title="Colorless Ports", lifespan=lifespan)
    app.state.db_path = path

    @app.middleware("http")
    async def no_store_api(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/")
    def demo_page() -> FileResponse:
        return FileResponse(STATIC / "demo.html")

    @app.get("/admin")
    def admin_page() -> FileResponse:
        return FileResponse(STATIC / "admin.html")

    @app.get("/api/snapshot")
    def snapshot(platform: str = "cx") -> dict:
        chosen = platform.strip().casefold()
        if chosen not in {"cx", "ex"}:
            raise HTTPException(status_code=400, detail="platform must be cx or ex")
        _note_viewer(app)
        settings = get_settings(path)
        roles = get_roles_safe(path)
        status: PollStatus = app.state.poll
        if chosen == "ex":
            raw = status.ex_ports
            poll = _ex_poll_view(app, settings)
        else:
            raw = status.raw_ports
            poll = _cx_poll_view(app, settings)
        return build_snapshot(
            raw,
            settings,
            roles,
            poll,
            platform=chosen,
            profiles=get_profiles(path),
            mist_roles=get_mist_roles(path),
        )

    @app.get("/api/admin/config")
    def admin_get() -> dict:
        settings = get_settings(path)
        config = public_config(path)
        config["ex_source_choice"] = display_ex_choice(settings)
        return {**config, "poll": _poll_view(app, settings)}

    @app.put("/api/admin/config")
    def admin_put(body: ConfigIn) -> dict:
        try:
            saved = save_config(path, body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        app.state.wake.set()
        settings = get_settings(path)
        saved["ex_source_choice"] = display_ex_choice(settings)
        return {**saved, "poll": _poll_view(app, settings)}

    @app.post("/api/admin/test/switch")
    async def test_switch(body: SwitchTestIn) -> dict:
        try:
            target = _switch_target(path, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session = AoscxSession(target)
        try:
            hostname, version, ports = await session.poll_access_ports()
        except AoscxError as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            await session.close()
        status: PollStatus = app.state.poll
        status.raw_ports = ports
        status.switch_ok = True
        status.switch_error = ""
        status.hostname = hostname
        status.software_version = version
        from datetime import datetime, timezone

        status.polled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        clients = sum(len(port.clients) for port in ports)
        up = sum(1 for port in ports if port.status == "up")
        return {
            "ok": True,
            "hostname": hostname,
            "software_version": version,
            "ports_up": up,
            "clients": clients,
        }

    @app.post("/api/admin/test/clearpass")
    async def test_clearpass(body: ClearPassTestIn) -> dict:
        try:
            target = _clearpass_target(path, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session = ClearPassSession(target)
        try:
            await session.ping()
        except ClearPassError as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            await session.close()
        return {"ok": True, "message": "ClearPass accepted the client credentials"}

    @app.post("/api/admin/test/mist")
    async def test_mist(body: MistTestIn) -> dict:
        try:
            target = _mist_target(path, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            info = await check_mist(target)
        except MistError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "name": info.get("name") or "", "message": "Mist accepted the API token"}

    @app.post("/api/admin/test/ex")
    async def test_ex(body: ExTestIn) -> dict:
        try:
            target = _mist_target(path, body)
            site = body.ex_site_id.strip()
            mac = body.ex_switch_mac.strip()
            if not site or not mac:
                raise ValueError("Enter both a Mist site ID and the EX switch MAC")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session = MistSession(target)
        try:
            hostname, version, ports = await session.poll_access_ports(site, mac)
            ports = mark_mist(ports)
        except MistError as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            await session.close()
        status: PollStatus = app.state.poll
        status.ex_ports = ports
        status.ex_ok = True
        status.ex_error = ""
        status.ex_hostname = hostname
        status.ex_version = version
        from datetime import datetime, timezone

        status.ex_polled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        clients = sum(len(port.clients) for port in ports)
        up = sum(1 for port in ports if port.status == "up")
        return {
            "ok": True,
            "hostname": hostname,
            "software_version": version,
            "ports_up": up,
            "clients": clients,
        }

    @app.post("/api/admin/test/junos")
    async def test_junos(body: JunosTestIn) -> dict:
        try:
            target = _junos_target(path, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session = JunosSession(target)
        try:
            hostname, version, links, sessions = await session.read_access()
        except JunosError as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            await session.close()
        ports = ports_from_junos(links, sessions)
        status: PollStatus = app.state.poll
        status.ex_ports = ports
        status.ex_ok = True
        status.ex_error = ""
        status.ex_hostname = hostname
        status.ex_version = version
        from datetime import datetime, timezone

        status.ex_polled_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        clients = sum(len(port.clients) for port in ports)
        up = sum(1 for port in ports if port.status == "up")
        return {
            "ok": True,
            "hostname": hostname,
            "software_version": version,
            "ports_up": up,
            "clients": clients,
        }

    @app.post("/api/admin/roles/junos")
    async def load_junos_roles(body: JunosLoadIn) -> dict:
        try:
            target = _junos_target(path, body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session = JunosSession(target)
        try:
            names = await session.filter_names()
        except JunosError as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            await session.close()
        if not names:
            return {"ok": False, "error": "Junos has no ethernet-switching filters"}
        merged = merge_named_colors(
            [role.model_dump() for role in body.mist_roles],
            names,
            JUNOS_FILTER_NOTE,
        )
        return {"ok": True, **merged}

    @app.post("/api/admin/roles/mist-template")
    async def load_mist_template_roles(body: MistTemplateLoadIn) -> dict:
        try:
            target = _mist_target(path, body)
            site = body.ex_site_id.strip()
            if not site:
                raise ValueError("Enter a Mist site ID")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session = MistSession(target)
        try:
            title, names = await session.switch_template_roles(site)
        except MistError as exc:
            return {"ok": False, "error": str(exc)}
        finally:
            await session.close()
        merged = merge_named_colors(
            [role.model_dump() for role in body.mist_roles],
            names,
            MIST_TEMPLATE_NOTE,
        )
        return {"ok": True, "template": title, **merged}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def get_roles_safe(path: Path):
    from app.db import get_roles

    return get_roles(path)


def _note_viewer(app: FastAPI) -> None:
    now = time.monotonic()
    was_idle = now - getattr(app.state, "last_view", 0.0) > 8
    app.state.last_view = now
    wake = getattr(app.state, "wake", None)
    if was_idle and wake is not None and not wake.is_set():
        wake.set()


def _watching(app: FastAPI, settings: dict) -> bool:
    interval = float(settings.get("poll_interval_sec") or 1)
    last_view = getattr(app.state, "last_view", 0.0)
    return viewer_is_active(last_view, interval)


def _cx_poll_view(app: FastAPI, settings: dict) -> dict:
    poll: PollStatus = app.state.poll
    return {
        "configured": bool(settings.get("switch_host")),
        "ok": poll.switch_ok,
        "error": poll.switch_error,
        "polled_at": poll.polled_at,
        "hostname": poll.hostname,
        "software_version": poll.software_version,
        "watching": _watching(app, settings),
        "clearpass_configured": bool(settings.get("clearpass_host")),
        "clearpass_ok": poll.clearpass_ok,
        "clearpass_error": poll.clearpass_error if settings.get("clearpass_host") else "",
    }


def _ex_poll_view(app: FastAPI, settings: dict) -> dict:
    poll: PollStatus = app.state.poll
    source = ex_source(settings)
    return {
        "configured": bool(source),
        "source": source,
        "choice": display_ex_choice(settings),
        "ok": poll.ex_ok,
        "error": poll.ex_error,
        "polled_at": poll.ex_polled_at,
        "hostname": poll.ex_hostname,
        "software_version": poll.ex_version,
        "watching": _watching(app, settings),
        "clearpass_configured": False,
        "clearpass_ok": False,
        "clearpass_error": "",
    }


def _poll_view(app: FastAPI, settings: dict) -> dict:
    view = _cx_poll_view(app, settings)
    view["ex"] = _ex_poll_view(app, settings)
    return view


def _switch_target(path: Path, body: SwitchTestIn) -> SwitchTarget:
    host = body.switch_host.strip()
    if not host:
        raise ValueError("Enter a switch host")
    username = body.switch_username.strip()
    if not username:
        raise ValueError("Enter the switch username")
    password = resolve_secret(path, "switch_password", body.switch_password)
    if not password:
        raise ValueError("Enter the switch password")
    cleaned, port = normalize_switch_host(host, int(body.switch_port))
    if not cleaned:
        raise ValueError("Enter a switch host")
    return SwitchTarget(
        host=cleaned,
        port=port,
        username=username,
        password=password,
        api_version=body.api_version.strip() or "v10.16",
        verify_tls=body.switch_verify_tls,
        vsf_member=int(body.vsf_member),
    )


def _clearpass_target(path: Path, body: ClearPassTestIn) -> ClearPassTarget:
    host = body.clearpass_host.strip()
    if not host:
        raise ValueError("Enter a ClearPass host")
    client_id = body.clearpass_client_id.strip()
    if not client_id:
        raise ValueError("Enter the ClearPass client ID")
    secret = resolve_secret(path, "clearpass_client_secret", body.clearpass_client_secret)
    if not secret:
        raise ValueError("Enter the ClearPass client secret")
    return ClearPassTarget(
        host=host,
        client_id=client_id,
        client_secret=secret,
        verify_tls=body.clearpass_verify_tls,
    )


def _mist_target(path: Path, body: MistTestIn) -> MistTarget:
    token = resolve_secret(path, "mist_api_token", body.mist_api_token)
    if not token:
        raise ValueError("Enter the Mist API token")
    host = body.mist_host.strip() or "api.mist.com"
    return MistTarget(host=host, api_token=token, verify_tls=body.mist_verify_tls)


def _junos_target(path: Path, body: JunosTestIn) -> JunosTarget:
    host = body.junos_host.strip()
    if not host:
        raise ValueError("Enter a Junos host")
    username = body.junos_username.strip()
    if not username:
        raise ValueError("Enter the Junos username")
    password = resolve_secret(path, "junos_password", body.junos_password)
    if not password:
        raise ValueError("Enter the Junos password")
    port = int(body.junos_port or 3443)
    if port < 1 or port > 65535:
        raise ValueError("Junos port is invalid")
    return JunosTarget(
        host=host,
        port=port,
        username=username,
        password=password,
        verify_tls=body.junos_verify_tls,
    )


app = create_app()


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


_configure_logging()
