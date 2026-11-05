"""Mist API for the EX faceplate. The token is sent on each request.

AOS-CX does not use this module. Junos is not contacted. See SUPPORT.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlparse

import httpx

from app.aoscx import RawClient, RawPort

COPPER = re.compile(r"^(mge|ge)-(\d+)/(\d+)/(\d+)$", re.IGNORECASE)
ACCESS_PORTS = 12


class MistError(Exception):
    pass


@dataclass
class MistTarget:
    host: str
    api_token: str
    verify_tls: bool

    def __repr__(self) -> str:
        return f"MistTarget(host={self.host!r})"


def mist_base(host: str) -> str:
    raw = (host or "api.mist.com").strip().rstrip("/")
    if not raw:
        raise MistError("Mist host is empty")
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    return f"{parsed.scheme}://{parsed.netloc}"


def mac_hex(value: str) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch in "0123456789abcdef")


def display_mac(value: str) -> str:
    hexes = mac_hex(value)
    if len(hexes) != 12:
        return str(value or "").strip()
    return ":".join(hexes[i : i + 2] for i in range(0, 12, 2))


def device_id(mac: str) -> str:
    """Mist device id. The stats path does not accept a bare chassis MAC."""
    return f"00000000-0000-0000-1000-{mac}"


_ROLE_TAG_TYPES = {"radius_group", "aruba_user_role"}


def roles_from_template(template: object) -> list[str]:
    """Radius-group names on a switch template. Port-usage tags are not roles."""
    if not isinstance(template, dict):
        return []
    tags = template.get("acl_tags")
    if not isinstance(tags, dict):
        return []
    names: list[str] = []
    seen: set[str] = set()
    for key, tag in tags.items():
        if not isinstance(tag, dict):
            continue
        kind = str(tag.get("type") or "").strip().casefold().replace("-", "_")
        if kind not in _ROLE_TAG_TYPES:
            continue
        name = str(tag.get("radius_group") or "").strip() or str(key or "").strip()
        fold = name.casefold()
        if not name or fold in seen:
            continue
        seen.add(fold)
        names.append(name)
    return names


def copper_index(port_id: str) -> int | None:
    """Map ge-0/0/N and mge-0/0/N, N in 0..11, onto the EX4000 copper jacks.

    SFP names such as xe-0/1/0 stay unmapped. Member other than 0 is ignored.
    """
    match = COPPER.match(str(port_id or "").strip())
    if match is None:
        return None
    fpc = int(match.group(2))
    pic = int(match.group(3))
    port = int(match.group(4))
    if fpc != 0 or pic != 0 or port < 0 or port >= ACCESS_PORTS:
        return None
    return port


def _text(value: object) -> str:
    if isinstance(value, list):
        for item in value:
            text = str(item or "").strip()
            if text:
                return text
        return ""
    return str(value or "").strip()


def _vlan_keep(text: str) -> bool:
    if not text or text in {"0", "-1"}:
        return False
    try:
        return int(text) > 0
    except ValueError:
        return True


def _vlan_text(value: object) -> str:
    if isinstance(value, list):
        labels = []
        for item in value:
            text = str(item).strip()
            if _vlan_keep(text):
                labels.append(text)
        seen: list[str] = []
        for label in labels:
            if label not in seen:
                seen.append(label)
        return ", ".join(seen)
    text = str(value or "").strip()
    return text if _vlan_keep(text) else ""


def _mac_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return 0
    try:
        count = int(value)
    except ValueError:
        return 0
    return count if count > 0 else 0


def _auth_method(value: object) -> str:
    folded = str(value or "").strip().casefold().replace("_", "-")
    if folded in {"mac-auth", "macauth"}:
        return "mac-auth"
    if folded in {"dot1x", "802.1x", "8021x", "eap"}:
        return "dot1x"
    return str(value or "").strip()


def _session_filter(row: dict, port_id: str) -> str:
    """Mist role applied to this client. The switch template stores it as a radius group."""
    sessions = row.get("device_mac_port")
    if isinstance(sessions, list):
        for session in sessions:
            if isinstance(session, dict) and str(session.get("port_id") or "") == port_id:
                return _text(session.get("dynamic_filter"))
    return _text(row.get("dynamic_filter"))


def _as_dicts(rows: object) -> list[dict]:
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


@dataclass
class _PortFact:
    name: str
    up: bool
    usage: str
    neighbor: str
    auth_state: str
    mac_count: int
    mge: bool


def _better(new: _PortFact, old: _PortFact) -> bool:
    if new.up != old.up:
        return new.up
    if new.mge != old.mge:
        return new.mge
    return False


def ports_from_mist(port_rows: object, client_rows: object) -> list[RawPort]:
    """Twelve copper ports. The applied profile is port_usage.

    A connected wired client is kept even when Mist has no user role.
    An up port with a configured profile and no client stays dark.
    """
    ports = [RawPort(number=number, name=f"ge-0/0/{number}", status="down") for number in range(ACCESS_PORTS)]
    facts: dict[int, _PortFact] = {}
    for row in _as_dicts(port_rows):
        port_id = str(row.get("port_id") or "").strip()
        number = copper_index(port_id)
        if number is None:
            continue
        fact = _PortFact(
            name=port_id,
            up=bool(row.get("up")),
            usage=_text(row.get("port_usage")),
            neighbor=_text(row.get("neighbor_system_name")),
            auth_state=_text(row.get("auth_state")).casefold(),
            mac_count=_mac_count(row.get("mac_count")),
            mge=port_id.casefold().startswith("mge-"),
        )
        current = facts.get(number)
        if current is None or _better(fact, current):
            facts[number] = fact

    grouped: dict[int, list[RawClient]] = {number: [] for number in range(ACCESS_PORTS)}
    for row in _as_dicts(client_rows):
        mac = display_mac(_text(row.get("mac")))
        device_name = _text(row.get("hostname")) or _text(row.get("dhcp_hostname"))
        if not mac and not device_name:
            continue
        targets = []
        raw_ports = row.get("port_id")
        if isinstance(raw_ports, list):
            targets = [str(item) for item in raw_ports]
        elif raw_ports:
            targets = [str(raw_ports)]
        for port_id in targets:
            number = copper_index(port_id)
            if number is None:
                continue
            usage = facts[number].usage if number in facts else ""
            grouped[number].append(
                RawClient(
                    mac=mac,
                    username="",
                    auth_method=_auth_method(row.get("auth_method")),
                    role=usage,
                    device_type=_text(row.get("manufacture")),
                    device_name=device_name,
                    vlan=_vlan_text(row.get("vlan")),
                    forwarding="Bridged",
                    tunnel="",
                    ip_address=_text(row.get("ip")),
                    mist_role=_session_filter(row, port_id),
                )
            )

    for port in ports:
        fact = facts.get(port.number)
        if fact is not None:
            port.name = fact.name or port.name
            port.status = "up" if fact.up else "down"
            port.lldp_neighbor = fact.neighbor
        clients = grouped[port.number]
        if port.status != "up" and clients and fact is None:
            port.status = "up"
        if port.status != "up":
            continue
        port.clients = clients
        if port.clients or fact is None:
            continue
        if fact.usage and (fact.auth_state == "authenticated" or fact.mac_count > 0):
            port.clients = [
                RawClient(
                    mac="",
                    username="",
                    auth_method="",
                    role=fact.usage,
                    device_type="",
                    device_name="",
                    vlan="",
                    forwarding="Bridged",
                    tunnel="",
                )
            ]
    return ports


async def check_mist(target: MistTarget, client: httpx.AsyncClient | None = None) -> dict:
    if not target.api_token:
        raise MistError("Mist API token is required")
    owns = client is None
    http = client or httpx.AsyncClient(
        verify=target.verify_tls,
        timeout=httpx.Timeout(8.0),
        trust_env=False,
        follow_redirects=False,
    )
    try:
        try:
            response = await http.get(
                mist_base(target.host) + "/api/v1/self",
                headers={"Authorization": f"Token {target.api_token}", "Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise MistError("Mist did not answer in time") from exc
        except httpx.RequestError as exc:
            raise MistError("Cannot reach Mist") from exc
        if response.status_code >= 400:
            raise MistError(f"Mist rejected the token ({response.status_code})")
        try:
            body = response.json()
        except ValueError as exc:
            raise MistError("Mist did not return JSON") from exc
        if not isinstance(body, dict):
            body = {}
        name = str(body.get("name") or body.get("email") or "")
        return {"name": name}
    finally:
        if owns:
            await http.aclose()


class MistSession:
    def __init__(self, target: MistTarget, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.target = target
        self.http = httpx.AsyncClient(
            verify=target.verify_tls,
            timeout=httpx.Timeout(10.0),
            trust_env=False,
            follow_redirects=False,
            transport=transport,
        )

    async def close(self) -> None:
        await self.http.aclose()

    async def poll_access_ports(self, site_id: str, switch_mac: str) -> tuple[str, str, list[RawPort]]:
        if not self.target.api_token:
            raise MistError("Mist API token is required")
        site = site_id.strip()
        mac = mac_hex(switch_mac)
        if len(mac) != 12:
            raise MistError("Switch MAC must be 12 hex digits")
        hostname, version = await self._device(site, mac)
        port_rows = await self._search(f"/api/v1/sites/{site}/stats/ports/search", {"mac": mac})
        client_rows = await self._search(
            f"/api/v1/sites/{site}/wired_clients/search",
            {"device_mac": mac},
        )
        return hostname or display_mac(mac), version, ports_from_mist(port_rows, client_rows)

    async def switch_template_roles(self, site_id: str) -> tuple[str, list[str]]:
        """Role names from the switch template assigned to this site."""
        if not self.target.api_token:
            raise MistError("Mist API token is required")
        site = site_id.strip()
        if not site:
            raise MistError("Enter a Mist site ID")
        _status, body = await self._get(f"/api/v1/sites/{site}")
        if not isinstance(body, dict):
            raise MistError("Mist did not return the site")
        org_id = _text(body.get("org_id"))
        template_id = _text(body.get("networktemplate_id"))
        if not template_id:
            raise MistError("This site has no switch template")
        if not org_id:
            raise MistError("Mist did not return the site organization")
        _status, template = await self._get(f"/api/v1/orgs/{org_id}/networktemplates/{template_id}")
        if not isinstance(template, dict):
            raise MistError("Mist did not return the switch template")
        names = roles_from_template(template)
        if not names:
            raise MistError("This switch template has no radius-group roles. Port profiles are not roles.")
        title = _text(template.get("name")) or template_id
        return title, names

    async def _device(self, site: str, mac: str) -> tuple[str, str]:
        status, body = await self._get(
            f"/api/v1/sites/{site}/stats/devices/{device_id(mac)}",
            missing_ok=True,
        )
        if status == 404 or not isinstance(body, dict):
            return "", ""
        hostname = _text(body.get("hostname")) or _text(body.get("name"))
        model = _text(body.get("model"))
        version = _text(body.get("version"))
        software = " · ".join(part for part in (model, version) if part)
        return hostname, software

    async def _search(self, path: str, params: dict[str, str]) -> list[dict]:
        rows: list[dict] = []
        query = {**params, "limit": "100"}
        seen: set[str] = set()
        for _ in range(6):
            _status, body = await self._get(path, params=query)
            if not isinstance(body, dict):
                break
            results = body.get("results") or []
            if isinstance(results, list):
                rows.extend(item for item in results if isinstance(item, dict))
            nxt = body.get("next") or ""
            if not isinstance(nxt, str) or not nxt or nxt in seen:
                break
            seen.add(nxt)
            if nxt.startswith("/") or nxt.startswith("http"):
                parsed = urlparse(nxt if nxt.startswith("http") else "https://mist.local" + nxt)
                path = parsed.path
                query = {key: value for key, value in parse_qsl(parsed.query)}
                continue
            query = {**params, "limit": "100", "search_after": nxt}
        return rows

    async def _get(
        self,
        path: str,
        params: dict[str, str] | None = None,
        missing_ok: bool = False,
    ) -> tuple[int, object]:
        try:
            response = await self.http.get(
                mist_base(self.target.host) + path,
                params=params,
                headers={"Authorization": f"Token {self.target.api_token}", "Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise MistError("Mist did not answer in time") from exc
        except httpx.RequestError as exc:
            raise MistError("Cannot reach Mist") from exc
        if response.status_code == 404 and missing_ok:
            return 404, None
        if response.status_code == 401:
            raise MistError("Mist rejected the token (401)")
        if response.status_code == 404:
            raise MistError("Mist site or switch was not found (404)")
        if response.status_code >= 400:
            raise MistError(f"Mist rejected the request ({response.status_code})")
        try:
            return response.status_code, response.json()
        except ValueError as exc:
            raise MistError("Mist did not return JSON") from exc
