"""ClearPass and Mist credential checks. Tokens stay out of error text."""

import asyncio

import httpx

from app.clearpass import ClearPassError, ClearPassSession, ClearPassTarget, parse_endpoint
from app.mist import MistError, MistTarget, check_mist

SECRET = "clearpass-client-secret"
TOKEN = "mist-api-token-value"


def test_clearpass_oauth_and_mac_fallback():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path.endswith("/oauth"):
            body = request.content.decode()
            assert "grant_type=client_credentials" in body
            assert SECRET in body
            return httpx.Response(200, json={"access_token": "bearer-1"})
        assert request.headers["authorization"] == "Bearer bearer-1"
        if request.url.path.endswith("aa:bb:cc:dd:ee:ff"):
            return httpx.Response(404, json={})
        if request.url.path.endswith("aabbccddeeff"):
            return httpx.Response(
                200,
                json={"attributes": {"Device Type": "Camera", "Display Name": "Lobby Cam"}},
            )
        return httpx.Response(404, json={})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = ClearPassSession(
            ClearPassTarget("cppm.example", "demo-client", SECRET, False),
            client,
        )
        return await session.endpoint("AA-BB-CC-DD-EE-FF")

    info = asyncio.run(run())
    assert info.device_type == "Camera"
    assert info.device_name == "Lobby Cam"
    assert seen[0].endswith("/api/oauth")


def test_profile_details_fill_name_type_and_ip_when_attributes_are_empty():
    info = parse_endpoint({
        "status": "Unknown",
        "attributes": {},
        "profile": {
            "host_name": "CNQJKYV08N",
            "device_category": "Network Monitoring",
            "device_os_family": "HPE Aruba Networking",
            "device_name": "UXI Sensor",
            "ipv4_address": "",
        },
    })
    assert info.device_name == "CNQJKYV08N"
    assert info.device_type == "UXI Sensor"
    assert info.device_category == "Network Monitoring"
    assert info.device_family == "HPE Aruba Networking"
    assert info.ip_address == ""

    custom = parse_endpoint({
        "attributes": {"Device Type": "Camera", "Display Name": "Lobby Cam"},
    })
    assert custom.device_type == "Camera"
    assert custom.device_name == "Lobby Cam"


def test_endpoint_asks_for_profile_and_falls_back_to_insight_for_ip():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/oauth"):
            return httpx.Response(200, json={"access_token": "bearer-1"})
        if "/endpoint/mac-address/" in request.url.path:
            assert request.url.params.get("profile_details") == "true"
            return httpx.Response(
                200,
                json={
                    "attributes": {},
                    "profile": {
                        "host_name": "CNQJKYV08N",
                        "device_category": "Network Monitoring",
                        "device_os_family": "HPE Aruba Networking",
                        "device_name": "UXI Sensor",
                    },
                },
            )
        if request.url.path.endswith("/insight/endpoint/mac/28de65ba43e4"):
            return httpx.Response(200, json={"ip": "172.16.17.12", "device_name": "UXI Sensor"})
        return httpx.Response(404, json={})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = ClearPassSession(
            ClearPassTarget("https://cppm.example/api", "demo-client", SECRET, False),
            client,
        )
        return await session.endpoint("28:de:65:ba:43:e4")

    info = asyncio.run(run())
    assert info.device_name == "CNQJKYV08N"
    assert info.device_type == "UXI Sensor"
    assert info.ip_address == "172.16.17.12"
    assert info.device_category == "Network Monitoring"


def test_clearpass_login_error_hides_the_secret():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text=SECRET)

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = ClearPassSession(
            ClearPassTarget("https://cppm.example/api", "demo-client", SECRET, False),
            client,
        )
        await session.login()

    try:
        asyncio.run(run())
    except ClearPassError as exc:
        assert str(exc) == "ClearPass login failed (401)"
        assert SECRET not in str(exc)
    else:
        raise AssertionError("login should fail")


def test_mist_token_header_and_error_text():
    def ok(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == f"Token {TOKEN}"
        assert request.url.path == "/api/v1/self"
        return httpx.Response(200, json={"name": "lab"})

    async def success():
        client = httpx.AsyncClient(transport=httpx.MockTransport(ok))
        return await check_mist(MistTarget("api.mist.com", TOKEN, True), client)

    assert asyncio.run(success()) == {"name": "lab"}

    def denied(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text=TOKEN)

    async def failure():
        client = httpx.AsyncClient(transport=httpx.MockTransport(denied))
        await check_mist(MistTarget("https://api.mist.com/extra", TOKEN, True), client)

    try:
        asyncio.run(failure())
    except MistError as exc:
        assert str(exc) == "Mist rejected the token (403)"
        assert TOKEN not in str(exc)
    else:
        raise AssertionError("mist check should fail")
