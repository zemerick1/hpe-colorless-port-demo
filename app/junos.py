"""Direct Junos REST for the EX faceplate. Mist is not called from here.

The switch must already be serving `system services rest https`. This module
reads sessions and ethernet-switching filters. It does not push configuration.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

_SCHEME = re.compile(r"^https?://", re.IGNORECASE)


class JunosError(Exception):
    pass


@dataclass
class JunosTarget:
    host: str
    port: int
    username: str
    password: str
    verify_tls: bool

    def __repr__(self) -> str:
        return f"JunosTarget(host={self.host!r}, port={self.port}, user={self.username!r})"


@dataclass
class JunosLink:
    name: str
    up: bool


@dataclass
class Dot1xSession:
    interface: str
    mac: str
    username: str
    filter_name: str
    vlan: str
    state: str


def junos_base(host: str, port: int) -> str:
    raw = _SCHEME.sub("", (host or "").strip()).split("/")[0].strip()
    if not raw:
        raise JunosError("Junos host is empty")
    if not 1 <= int(port) <= 65535:
        raise JunosError("Junos port is invalid")
    return f"https://{raw}:{int(port)}"


def junos_data(node: object) -> str:
    """Read a Junos JSON value. Strings and {\"data\": ...} both occur."""
    if isinstance(node, str):
        return node.strip()
    if isinstance(node, bool) or node is None:
        return ""
    if isinstance(node, (int, float)):
        return str(node).strip()
    if isinstance(node, dict):
        if "data" in node:
            return junos_data(node.get("data"))
        return ""
    if isinstance(node, list):
        for item in node:
            text = junos_data(item)
            if text:
                return text
        return ""
    return ""


def _as_list(node: object) -> list:
    if isinstance(node, list):
        return node
    if isinstance(node, dict):
        return [node]
    return []


def _find_key(node: object, key: str) -> list:
    found: list = []
    if isinstance(node, dict):
        for item_key, value in node.items():
            if item_key == key:
                if isinstance(value, list):
                    found.extend(value)
                else:
                    found.append(value)
            else:
                found.extend(_find_key(value, key))
    elif isinstance(node, list):
        for item in node:
            found.extend(_find_key(item, key))
    return found


def _rpc_failed(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    for key in payload:
        if "error" in str(key).casefold():
            return True
    return False


def _authenticated(state: str) -> bool:
    folded = state.casefold().replace("_", " ").replace("-", " ")
    return folded == "authenticated" or folded.startswith("authenticated ")


def _filter_name(row: dict) -> str:
    for key in ("filter-name", "dynamic-filter", "filter"):
        if key not in row:
            continue
        text = junos_data(row.get(key))
        if text:
            return text
        for item in _as_list(row.get(key)):
            if not isinstance(item, dict):
                continue
            named = junos_data(item.get("name") or item.get("filter-name"))
            if named:
                return named
    return ""


def _supplicants(interface: dict) -> list[dict]:
    found: list[dict] = []
    for bucket in _as_list(interface.get("supplicant-list")):
        if isinstance(bucket, dict) and "supplicant" in bucket:
            found.extend(item for item in _as_list(bucket.get("supplicant")) if isinstance(item, dict))
        elif isinstance(bucket, dict):
            found.append(bucket)
    if not found:
        found.extend(item for item in _as_list(interface.get("supplicant")) if isinstance(item, dict))
    return found


def links_from_interfaces(payload: object) -> list[JunosLink]:
    links: list[JunosLink] = []
    for row in _find_key(payload, "physical-interface"):
        if not isinstance(row, dict):
            continue
        name = junos_data(row.get("name"))
        if not name:
            continue
        links.append(JunosLink(name=name, up=junos_data(row.get("oper-status")).casefold() == "up"))
    return links


def sessions_from_dot1x(payload: object) -> list[Dot1xSession]:
    sessions: list[Dot1xSession] = []
    for interface in _find_key(payload, "interface"):
        if not isinstance(interface, dict):
            continue
        name = junos_data(interface.get("interface-name") or interface.get("interface-name-string"))
        if not name:
            continue
        for row in _supplicants(interface):
            state = junos_data(row.get("supplicant-state") or row.get("state"))
            if not _authenticated(state):
                continue
            sessions.append(
                Dot1xSession(
                    interface=name,
                    mac=junos_data(row.get("supplicant-mac-address") or row.get("mac-address")),
                    username=junos_data(row.get("supplicant-name") or row.get("user-name")),
                    filter_name=_filter_name(row),
                    vlan=junos_data(row.get("vlan") or row.get("vlan-name") or row.get("authenticated-vlan")),
                    state=state,
                )
            )
    return sessions


def identity_from_software(payload: object) -> tuple[str, str]:
    host = ""
    version = ""
    for row in _find_key(payload, "host-name"):
        host = host or junos_data(row)
    for row in _find_key(payload, "junos-version"):
        version = version or junos_data(row)
    return host, version


def filters_from_config(payload: object) -> list[str]:
    """Filter names under firewall family ethernet-switching. Other families are ignored."""
    names: list[str] = []
    seen: set[str] = set()
    for family in _find_key(payload, "ethernet-switching"):
        if not isinstance(family, dict):
            continue
        for row in _as_list(family.get("filter")):
            if not isinstance(row, dict):
                continue
            name = junos_data(row.get("name"))
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            names.append(name)
    return names


def filters_from_firewall(payload: object) -> list[str]:
    """Installed filter names from `show firewall`.

    Mist installs this filter after the role is applied to a Switch Policy.
    The filter is on the firewall table and is absent from `get-configuration`.
    """
    names: list[str] = []
    seen: set[str] = set()
    for row in _find_key(payload, "filter-information"):
        if not isinstance(row, dict):
            continue
        name = junos_data(row.get("filter-name"))
        if not name or name.startswith("__") or name.casefold() in seen:
            continue
        seen.add(name.casefold())
        names.append(name)
    return names


def _unique_names(groups: list[list[str]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for name in group:
            fold = name.casefold()
            if not name or fold in seen:
                continue
            seen.add(fold)
            names.append(name)
    return names


_XML_MESSAGE = re.compile(r"<message>(.*?)</message>", re.IGNORECASE | re.DOTALL)


def decode_rpc_response(content_type: str, body: bytes) -> object:
    """Read a Junos REST body. A successful POST /rpc is multipart/mixed around JSON."""
    blobs = _rpc_blobs(content_type, body)
    parsed: list[object] = []
    xml_error = ""
    for blob in blobs:
        text = blob.lstrip()
        if text.startswith((b"{", b"[")):
            try:
                parsed.append(json.loads(text))
            except ValueError:
                continue
            continue
        if text.startswith(b"<") and not xml_error:
            xml_error = _xml_error_message(text)
    if len(parsed) == 1:
        return parsed[0]
    if parsed:
        return parsed
    if xml_error:
        raise JunosError(xml_error)
    raise JunosError("Junos did not return JSON")


def _rpc_blobs(content_type: str, body: bytes) -> list[bytes]:
    boundary = _multipart_boundary(content_type)
    if not boundary:
        stripped = body.strip()
        return [stripped] if stripped else []
    blobs: list[bytes] = []
    for chunk in body.split(b"--" + boundary):
        part = _part_body(chunk)
        if part:
            blobs.append(part)
    return blobs


def _multipart_boundary(content_type: str) -> bytes:
    if "multipart/" not in content_type.casefold():
        return b""
    for piece in content_type.split(";"):
        piece = piece.strip()
        if piece.casefold().startswith("boundary="):
            token = piece.split("=", 1)[1].strip().strip('"')
            if token:
                return token.encode()
    return b""


def _part_body(chunk: bytes) -> bytes:
    chunk = chunk.lstrip(b"\r\n")
    if chunk.startswith(b"--"):
        return b""
    for separator in (b"\r\n\r\n", b"\n\n"):
        if separator in chunk:
            return chunk.split(separator, 1)[1].strip()
    return b""


def _xml_error_message(blob: bytes) -> str:
    text = blob.decode("utf-8", "replace")
    if "error" not in text.casefold():
        return ""
    match = _XML_MESSAGE.search(text)
    if match is None:
        return "Junos rejected the request"
    message = re.sub(r"\s+", " ", match.group(1)).strip()
    message = message.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return message[:300] or "Junos rejected the request"


class JunosSession:
    def __init__(self, target: JunosTarget, transport: httpx.AsyncBaseTransport | None = None) -> None:
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

    async def read_access(self) -> tuple[str, str, list[JunosLink], list[Dot1xSession]]:
        software = await self._rpc("<get-software-information/>")
        interfaces = await self._rpc("<get-interface-information><terse/></get-interface-information>")
        dot1x = await self._rpc("<get-dot1x-interface-information><detail/></get-dot1x-interface-information>")
        hostname, version = identity_from_software(software)
        return hostname, version, links_from_interfaces(interfaces), sessions_from_dot1x(dot1x)

    async def filter_names(self) -> list[str]:
        configured = filters_from_config(
            await self._rpc(
                "<get-configuration format=\"json\">"
                "<configuration><firewall><family><ethernet-switching/></family></firewall></configuration>"
                "</get-configuration>"
            )
        )
        installed = filters_from_firewall(await self._rpc("<get-firewall-information/>"))
        return _unique_names([configured, installed])

    async def _rpc(self, body: str) -> object:
        if not self.target.username or not self.target.password:
            raise JunosError("Junos username and password are required")
        url = junos_base(self.target.host, self.target.port) + "/rpc"
        try:
            response = await self.http.post(
                url,
                content=body.encode(),
                headers={"Accept": "application/json", "Content-Type": "application/xml"},
                auth=(self.target.username, self.target.password),
            )
        except httpx.TimeoutException as exc:
            raise JunosError("Junos did not answer in time") from exc
        except httpx.RequestError as exc:
            raise JunosError("Cannot reach Junos") from exc
        if response.status_code in {401, 403}:
            raise JunosError(f"Junos rejected the login ({response.status_code})")
        if response.status_code >= 400:
            raise JunosError(f"Junos rejected the request ({response.status_code})")
        payload = decode_rpc_response(response.headers.get("content-type", ""), response.content)
        if _rpc_failed(payload):
            raise JunosError("Junos rejected the request")
        return payload
