"""ClearPass OAuth client-credentials exchange and endpoint lookup."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote, urlparse

import httpx


class ClearPassError(Exception):
    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


@dataclass
class EndpointInfo:
    device_type: str = ""
    device_name: str = ""
    ip_address: str = ""
    device_category: str = ""
    device_family: str = ""


@dataclass
class ClearPassTarget:
    host: str
    client_id: str
    client_secret: str
    verify_tls: bool

    def __repr__(self) -> str:
        return f"ClearPassTarget(host={self.host!r}, client_id={self.client_id!r})"


def clearpass_base(host: str) -> str:
    raw = host.strip().rstrip("/")
    if not raw:
        raise ClearPassError("ClearPass host is empty")
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    if parsed.path in ("", "/"):
        raw = raw + "/api"
    return raw


def mac_forms(mac: str) -> list[str]:
    hex_only = "".join(ch for ch in mac.lower() if ch in "0123456789abcdef")
    forms: list[str] = []
    if len(hex_only) == 12:
        colon = ":".join(hex_only[i : i + 2] for i in range(0, 12, 2))
        forms.append(colon)
        forms.append(hex_only)
    elif mac.strip():
        forms.append(mac.strip())
    return forms


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [str(item).strip() for item in value if str(item).strip()]
        return ", ".join(parts)
    text = str(value).strip()
    if text.casefold() == "unknown":
        return ""
    return text


def parse_endpoint(payload: object) -> EndpointInfo:
    """Read a profiler endpoint. Custom attributes win; profile_details fills the rest."""
    if not isinstance(payload, dict):
        return EndpointInfo()
    attributes = payload.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        profile = {}
    device_type = _text(attributes.get("Device Type") or attributes.get("device_type"))
    if not device_type:
        device_type = _text(profile.get("device_name"))
    device_name = _text(
        attributes.get("Display Name")
        or attributes.get("display_name")
        or attributes.get("Device Name")
        or profile.get("host_name")
    )
    return EndpointInfo(
        device_type=device_type,
        device_name=device_name,
        ip_address=_text(profile.get("ipv4_address") or attributes.get("IP Address")),
        device_category=_text(profile.get("device_category")),
        device_family=_text(profile.get("device_os_family")),
    )


class ClearPassSession:
    def __init__(self, target: ClearPassTarget, client: httpx.AsyncClient | None = None) -> None:
        self.target = target
        self.base = clearpass_base(target.host)
        self.client = client or httpx.AsyncClient(
            verify=target.verify_tls,
            timeout=httpx.Timeout(8.0),
            trust_env=False,
            follow_redirects=False,
        )
        self._owned = client is None
        self.access_token = ""

    async def close(self) -> None:
        if self._owned:
            await self.client.aclose()

    async def login(self) -> str:
        try:
            response = await self.client.post(
                self.base + "/oauth",
                data={
                    "grant_type": "client_credentials",
                    "client_id": self.target.client_id,
                    "client_secret": self.target.client_secret,
                },
            )
        except httpx.TimeoutException as exc:
            raise ClearPassError("ClearPass did not answer in time") from exc
        except httpx.RequestError as exc:
            raise ClearPassError("Cannot reach ClearPass") from exc
        if response.status_code >= 400:
            raise ClearPassError(
                f"ClearPass login failed ({response.status_code})",
                status=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise ClearPassError("ClearPass login did not return JSON") from exc
        token = str(body.get("access_token") or "")
        if not token:
            raise ClearPassError("ClearPass login did not return a token")
        self.access_token = token
        return token

    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        if not self.access_token:
            await self.login()
        headers = {"Authorization": f"Bearer {self.access_token}", "Accept": "application/json"}
        try:
            response = await self.client.get(self.base + path, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            raise ClearPassError("ClearPass did not answer in time") from exc
        except httpx.RequestError as exc:
            raise ClearPassError("Cannot reach ClearPass") from exc
        if response.status_code == 401:
            self.access_token = ""
            await self.login()
            headers["Authorization"] = f"Bearer {self.access_token}"
            try:
                response = await self.client.get(self.base + path, headers=headers, params=params)
            except httpx.RequestError as exc:
                raise ClearPassError("Cannot reach ClearPass") from exc
        return response

    async def endpoint(self, mac: str) -> EndpointInfo:
        info = EndpointInfo()
        last_status = 0
        for form in mac_forms(mac):
            response = await self._get(
                "/endpoint/mac-address/" + quote(form, safe=""),
                {"profile_details": "true"},
            )
            if response.status_code == 404:
                last_status = 404
                continue
            if response.status_code >= 400:
                raise ClearPassError(
                    f"ClearPass endpoint lookup failed ({response.status_code})",
                    status=response.status_code,
                )
            try:
                info = parse_endpoint(response.json())
            except ValueError as exc:
                raise ClearPassError("ClearPass endpoint did not return JSON") from exc
            last_status = response.status_code
            break
        if not info.ip_address:
            info.ip_address = await self._insight_ip(mac)
        if last_status == 404 and not info.ip_address:
            return EndpointInfo()
        return info

    async def _insight_ip(self, mac: str) -> str:
        """Insight keeps the last IP when the profiler profile has none."""
        try:
            for form in mac_forms(mac):
                response = await self._get("/insight/endpoint/mac/" + quote(form, safe=""))
                if response.status_code == 404:
                    continue
                if response.status_code >= 400:
                    return ""
                try:
                    body = response.json()
                except ValueError:
                    return ""
                if isinstance(body, dict):
                    ip = _text(body.get("ip"))
                    if ip:
                        return ip
        except ClearPassError:
            return ""
        return ""

    async def ping(self) -> None:
        """Prove the bearer token is accepted."""
        await self.login()
        response = await self._get("/endpoint", {"calculate_count": "false", "limit": "1"})
        if response.status_code >= 400:
            raise ClearPassError(
                f"ClearPass rejected the token ({response.status_code})",
                status=response.status_code,
            )
