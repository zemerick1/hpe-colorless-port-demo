"""AOS-CX REST session. Username and password are exchanged for a CSRF token."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from urllib.parse import quote, unquote

import httpx

ACCESS_PORT_COUNT = 12
CLIENT_ATTRIBUTES = (
    "mac,applied_role,onboarded_method,client_state,access_vlan,device_profile,"
    "ubt_client_state,ubt_tunnel_hw_programmed,ubt_uac_tunnel,auth_attributes"
)
SKIP_CLIENT_STATES = {"initialized", "authenticating"}


class AoscxError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class SwitchTarget:
    host: str
    port: int
    username: str
    password: str
    api_version: str
    verify_tls: bool
    vsf_member: int

    def __repr__(self) -> str:
        return f"SwitchTarget(host={self.host!r}, port={self.port}, user={self.username!r})"


@dataclass
class RawClient:
    mac: str
    username: str
    auth_method: str
    role: str
    device_type: str
    device_name: str
    vlan: str
    forwarding: str
    tunnel: str
    ip_address: str = ""
    device_category: str = ""
    device_family: str = ""
    mist_role: str = ""


@dataclass
class RawPort:
    number: int
    name: str
    status: str
    lldp_neighbor: str = ""
    clients: list[RawClient] = field(default_factory=list)


def normalize_switch_host(host: str, port: int) -> tuple[str, int]:
    text = re.sub(r"^https?://", "", host.strip(), flags=re.IGNORECASE).rstrip("/")
    if text.count(":") == 1 and text.rsplit(":", 1)[1].isdigit():
        name, embedded = text.rsplit(":", 1)
        if port == 443:
            port = int(embedded)
        text = name
    return text, port


def ref_name(value: object) -> str:
    """Last path segment of an AOS-CX reference, or the plain string."""
    if value is None:
        return ""
    if isinstance(value, dict):
        if isinstance(value.get("name"), str) and value["name"]:
            return unquote(value["name"])
        if len(value) == 1:
            return unquote(str(next(iter(value.keys()))))
        return ""
    text = unquote(str(value).strip())
    if text.startswith(("http://", "https://", "/")):
        text = unquote(text.rstrip("/").split("/")[-1])
    return text


_SINGLETON_KEYS = {
    "link_state",
    "hostname",
    "software_version",
    "applied_role",
    "mac",
    "neighbor_info",
    "client_state",
    "onboarded_method",
}


def iter_resources(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    if any(key in payload for key in _SINGLETON_KEYS):
        return [payload]
    items: list[dict] = []
    for key, value in payload.items():
        if isinstance(value, dict):
            row = dict(value)
            row.setdefault("name", unquote(str(key)))
            items.append(row)
        elif isinstance(value, str):
            items.append({"name": unquote(str(key)), "_uri": value})
    return items


def empty_ports(member: int) -> list[RawPort]:
    return [
        RawPort(number=number, name=f"{member}/1/{number}", status="down")
        for number in range(1, ACCESS_PORT_COUNT + 1)
    ]


def link_state_of(value: object) -> str:
    if isinstance(value, dict) and len(value) == 1:
        value = next(iter(value))
    text = str(value or "").strip().casefold()
    if text in {"up", "down"}:
        return text
    return ""


def ports_from_interfaces(payload: object, member: int) -> list[RawPort]:
    pattern = re.compile(rf"^{member}/1/(\d+)$")
    found: dict[int, RawPort] = {}
    for row in iter_resources(payload):
        name = str(row.get("name") or "")
        match = pattern.match(name)
        if match is None:
            continue
        number = int(match.group(1))
        if number < 1 or number > ACCESS_PORT_COUNT:
            continue
        found[number] = RawPort(
            number=number,
            name=name,
            status=link_state_of(row.get("link_state")) or "down",
        )
    ports = empty_ports(member)
    for port in ports:
        if port.number in found:
            found[port.number].lldp_neighbor = port.lldp_neighbor
            ports[port.number - 1] = found[port.number]
    return ports


def _username_from_auth(client: dict) -> str:
    attrs = client.get("auth_attributes") or {}
    if not isinstance(attrs, dict):
        return ""
    found = ""
    for key, value in attrs.items():
        if not isinstance(value, dict):
            continue
        name = str(value.get("username") or "")
        method = str(value.get("authentication_method") or key)
        state = str(value.get("auth_state") or "")
        if name and method.casefold() == "dot1x" and state in {"", "authenticated"}:
            return name
        if name and state == "authenticated":
            found = name
        elif name and not found:
            found = name
    return found


def _auth_method(client: dict) -> str:
    method = str(client.get("onboarded_method") or "")
    if method:
        return method
    attrs = client.get("auth_attributes") or {}
    if isinstance(attrs, dict):
        for key, value in attrs.items():
            if isinstance(value, dict) and value.get("auth_state") == "authenticated":
                return str(value.get("authentication_method") or key)
        if attrs:
            return str(next(iter(attrs.keys())))
    return ""


def _forwarding(client: dict) -> tuple[str, str]:
    state = str(client.get("ubt_client_state") or "")
    programmed = bool(client.get("ubt_tunnel_hw_programmed"))
    tunnel = ref_name(client.get("ubt_uac_tunnel"))
    if programmed or state == "registered":
        return "Tunneled", tunnel
    return "Bridged", ""


def _device_type(client: dict) -> str:
    traffic = str(client.get("device_traffic_class") or "")
    if traffic == "voice":
        return "Voice"
    if traffic == "data":
        return "Data"
    return ""


def vlan_from_role(role: object) -> str:
    """CLI prints multi when a role trunks more than the access VLAN."""
    if not isinstance(role, dict):
        return ""
    trunks = role.get("vlan_trunks") or []
    if isinstance(trunks, dict):
        trunks = [key for key, value in trunks.items() if value]
    if trunks:
        return "multi"
    name = role.get("vlan_name_tag") or ""
    if isinstance(name, str) and name:
        return name
    tag = role.get("vlan_tag")
    if isinstance(tag, int) and tag > 0:
        return str(tag)
    return ""


_GENERATED_ROLE = re.compile(r"^RADIUS_(?:Overridden_)?\d+$", re.IGNORECASE)


def is_generated_radius_role(role: str) -> bool:
    """CX names a RADIUS-derived role RADIUS_<n> or RADIUS_Overridden_<n>."""
    text = (role or "").strip().lstrip("*").rstrip("*")
    return bool(_GENERATED_ROLE.match(text))


def resolved_role_name(applied: str, role_payload: object) -> str:
    """Use the base role when CX published a generated RADIUS role name."""
    if not is_generated_radius_role(applied) or not isinstance(role_payload, dict):
        return applied
    base = str(role_payload.get("base_role_name") or "").strip()
    return base or applied


def parse_clients(payload: object) -> list[RawClient]:
    clients: list[RawClient] = []
    for row in iter_resources(payload):
        # previously_applied_role is the last role, not the current one.
        # Keeping it after applied_role is cleared leaves the old color on the jack.
        role = ref_name(row.get("applied_role"))
        state = str(row.get("client_state") or "")
        if not role or state in SKIP_CLIENT_STATES:
            continue
        mac = ref_name(row.get("mac")) or str(row.get("name") or row.get("_key") or "")
        if not mac and row.get("name"):
            mac = str(row["name"])
        forwarding, tunnel = _forwarding(row)
        clients.append(
            RawClient(
                mac=mac,
                username=_username_from_auth(row),
                auth_method=_auth_method(row),
                role=role,
                device_type=_device_type(row),
                device_name="",
                vlan=ref_name(row.get("access_vlan")),
                forwarding=forwarding,
                tunnel=tunnel,
            )
        )
    clients.sort(key=lambda client: client.mac)
    return clients


def parse_lldp_name(payload: object) -> str:
    for row in iter_resources(payload):
        info = row.get("neighbor_info")
        if isinstance(info, dict):
            name = info.get("chassis_name") or info.get("chassis_description") or ""
            if name:
                return str(name)
        if row.get("system_name"):
            return str(row["system_name"])
    return ""


class AoscxSession:
    def __init__(self, target: SwitchTarget, client: httpx.AsyncClient | None = None) -> None:
        self.target = target
        self.client = client or httpx.AsyncClient(
            verify=target.verify_tls,
            timeout=httpx.Timeout(8.0),
            trust_env=False,
            follow_redirects=False,
        )
        self._owned = client is None
        self.csrf = ""

    async def close(self) -> None:
        if self._owned:
            await self.client.aclose()

    def _base(self) -> str:
        return (
            f"https://{self.target.host}:{self.target.port}/rest/{self.target.api_version}"
        )

    async def login(self) -> None:
        url = self._base() + "/login"
        try:
            response = await self.client.post(
                url,
                params={"username": self.target.username, "password": self.target.password},
                headers={"Accept": "*/*", "x-use-csrf-token": "true"},
            )
        except httpx.TimeoutException as exc:
            raise AoscxError("Switch did not answer in time") from exc
        except httpx.RequestError as exc:
            raise AoscxError(f"Cannot reach switch {self.target.host}") from exc
        if response.status_code >= 400:
            raise AoscxError(f"Login failed ({response.status_code})", status=response.status_code)
        token = response.headers.get("x-csrf-token", "")
        if not token:
            raise AoscxError("Login did not return a session token")
        self.csrf = token

    async def get_json(self, path: str, params: dict | None = None) -> dict:
        if not self.csrf:
            await self.login()
        response = await self._request(path, params)
        if response.status_code == 401:
            self.csrf = ""
            await self.login()
            response = await self._request(path, params)
        if response.status_code == 404:
            raise AoscxError(f"Not found: {path}", status=404)
        if response.status_code >= 400:
            raise AoscxError(f"GET {path} failed ({response.status_code})", status=response.status_code)
        if not response.content:
            return {}
        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise AoscxError(f"GET {path} did not return JSON") from exc
        if isinstance(data, dict):
            return data
        raise AoscxError(f"GET {path} returned an unexpected payload")

    async def _request(self, path: str, params: dict | None) -> httpx.Response:
        try:
            return await self.client.get(
                self._base() + path,
                params=params,
                headers={"X-CSRF-Token": self.csrf, "Accept": "application/json"},
            )
        except httpx.TimeoutException as exc:
            raise AoscxError("Switch did not answer in time") from exc
        except httpx.RequestError as exc:
            raise AoscxError(f"Cannot reach switch {self.target.host}") from exc

    async def poll_access_ports(self) -> tuple[str, str, list[RawPort]]:
        system = await self.get_json(
            "/system",
            {"attributes": "hostname,software_version"},
        )
        hostname = str(system.get("hostname") or "")
        version = str(system.get("software_version") or "")
        interfaces = await self.get_json(
            "/system/interfaces",
            {"depth": 1, "attributes": "name,link_state", "selector": "status"},
        )
        ports = ports_from_interfaces(interfaces, self.target.vsf_member)
        # A collection of URIs has no link_state, so every port looks down and
        # the client read never runs. Ask each access port directly.
        if not any(port.status == "up" for port in ports):
            await self._refresh_link_states(ports)
        up_ports = [port for port in ports if port.status == "up"]

        async def load(port: RawPort) -> None:
            encoded = quote(port.name, safe="")
            try:
                clients = await self.get_json(
                    f"/system/interfaces/{encoded}/port_access_clients",
                    {"depth": 2, "attributes": CLIENT_ATTRIBUTES},
                )
            except AoscxError as exc:
                if exc.status == 400:
                    clients = await self.get_json(
                        f"/system/interfaces/{encoded}/port_access_clients",
                        {"depth": 1},
                    )
                elif exc.status == 404:
                    clients = {}
                else:
                    raise
            try:
                lldp = await self.get_json(
                    f"/system/interfaces/{encoded}/lldp_neighbors",
                    {"depth": 1},
                )
            except AoscxError as exc:
                if exc.status == 404:
                    lldp = {}
                else:
                    raise
            port.clients = parse_clients(clients)
            if port.clients:
                port.status = "up"
            port.lldp_neighbor = parse_lldp_name(lldp)

        results = await asyncio.gather(*(load(port) for port in up_ports), return_exceptions=True)
        for result in results:
            if isinstance(result, AoscxError):
                raise result
            if isinstance(result, Exception):
                raise AoscxError("Failed to read port access clients") from result
        await self._resolve_generated_roles(ports)
        await self._fill_missing_vlans(ports)
        return hostname, version, ports

    async def _refresh_link_states(self, ports: list[RawPort]) -> None:
        async def one(port: RawPort) -> None:
            encoded = quote(port.name, safe="")
            try:
                payload = await self.get_json(
                    f"/system/interfaces/{encoded}",
                    {"attributes": "link_state", "selector": "status"},
                )
            except AoscxError:
                return
            state = link_state_of(payload.get("link_state") if isinstance(payload, dict) else "")
            if state:
                port.status = state

        await asyncio.gather(*(one(port) for port in ports))

    async def _resolve_generated_roles(self, ports: list[RawPort]) -> None:
        pending: dict[str, list[RawClient]] = {}
        for port in ports:
            for client in port.clients:
                key = client.role.lstrip("*").rstrip("*")
                if is_generated_radius_role(key):
                    pending.setdefault(key, []).append(client)
        for role, clients in pending.items():
            try:
                payload = await self.get_json(
                    f"/system/port_access_roles/{quote(role, safe='')}",
                    {"attributes": "base_role_name,vlan_tag,vlan_name_tag,vlan_trunks"},
                )
            except AoscxError:
                continue
            name = resolved_role_name(role, payload)
            label = vlan_from_role(payload)
            for client in clients:
                if name and name != role:
                    client.role = name
                if label and not client.vlan:
                    client.vlan = label

    async def _fill_missing_vlans(self, ports: list[RawPort]) -> None:
        pending: dict[str, list[RawClient]] = {}
        for port in ports:
            for client in port.clients:
                if client.vlan or not client.role:
                    continue
                pending.setdefault(client.role.lstrip("*").rstrip("*"), []).append(client)
        for role, clients in pending.items():
            try:
                payload = await self.get_json(
                    f"/system/port_access_roles/{quote(role, safe='')}",
                    {"attributes": "vlan_tag,vlan_name_tag,vlan_trunks"},
                )
            except AoscxError:
                continue
            label = vlan_from_role(payload)
            if not label:
                continue
            for client in clients:
                client.vlan = label
