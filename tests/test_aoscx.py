"""AOS-CX login and REST parsing. The password must never appear in an error."""

import asyncio
from urllib.parse import unquote

import httpx

from app.aoscx import (
    AoscxError,
    AoscxSession,
    SwitchTarget,
    identify_chassis,
    parse_clients,
    parse_lldp_name,
    ports_from_interfaces,
    resolved_role_name,
)


def chassis_body(part: str, kind: str = "chassis") -> dict:
    return {"1": {"type": kind, "part_number": part, "product_name": part}}

PASSWORD = "switch-session-secret"


def target() -> SwitchTarget:
    return SwitchTarget(
        host="192.0.2.10",
        port=443,
        username="admin",
        password=PASSWORD,
        api_version="v10.16",
        verify_tls=False,
        vsf_member=1,
    )


def test_access_ports_ignore_vlan_and_uplinks():
    payload = {
        "1/1/1": {"link_state": "up"},
        "1/1/2": "/rest/v10.16/system/interfaces/1%2F1%2F2",
        "1/1/13": {"link_state": "up"},
        "vlan20": {"link_state": "up"},
        "2/1/1": {"link_state": "up"},
    }
    ports = ports_from_interfaces(payload, 1)
    assert len(ports) == 12
    assert ports[0].status == "up"
    assert ports[0].name == "1/1/1"
    assert ports[1].status == "down"
    assert ports[1].name == "1/1/2"
    assert all(port.status == "down" for port in ports[2:])


def test_parse_client_role_mac_auth_and_ubt():
    payload = {
        "aa:bb:cc:dd:ee:01": {
            "mac": "aa:bb:cc:dd:ee:01",
            "applied_role": "/rest/v10.16/system/port_access_roles/%2AEmployee-4821",
            "onboarded_method": "mac-auth",
            "client_state": "authenticated",
            "access_vlan": "/rest/v10.16/system/vlans/30",
            "device_traffic_class": "data",
            "auth_attributes": {
                "mac-auth": {
                    "username": "badge-12",
                    "authentication_method": "mac-auth",
                    "auth_state": "authenticated",
                }
            },
            "ubt_client_state": "registered",
            "ubt_uac_tunnel": "/rest/v10.16/system/ubt_uac_tunnels/cluster-a",
        },
        "aa:bb:cc:dd:ee:02": {
            "client_state": "authenticating",
            "applied_role": "Employee",
            "mac": "aa:bb:cc:dd:ee:02",
        },
        "aa:bb:cc:dd:ee:03": {
            "client_state": "authentication-failed",
            "applied_role": "denyall",
            "mac": "aa:bb:cc:dd:ee:03",
            "onboarded_method": "dot1x",
        },
    }
    clients = parse_clients(payload)
    assert [client.mac for client in clients] == ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:03"]
    camera = clients[0]
    assert camera.role == "*Employee-4821"
    assert camera.username == "badge-12"
    assert camera.auth_method == "mac-auth"
    assert camera.vlan == "30"
    assert camera.device_type == "Data"
    assert camera.forwarding == "Tunneled"
    assert camera.tunnel == "cluster-a"
    assert clients[1].role == "denyall"


def test_parse_device_profile_client():
    payload = {
        "f0:1a:a0:45:b1:10": {
            "mac": "f0:1a:a0:45:b1:10",
            "applied_role": {"ARUBA-AP": "/rest/v10.17/system/port_access_roles/ARUBA-AP"},
            "client_state": "no-authentication-needed",
            "onboarded_method": "device-profile",
            "access_vlan": None,
            "device_profile": {"ARUBA-AP": "/rest/v10.17/system/device_profiles/ARUBA-AP"},
            "device_traffic_class": None,
            "role_state": "applied",
        }
    }
    clients = parse_clients(payload)
    assert len(clients) == 1
    client = clients[0]
    assert client.role == "ARUBA-AP"
    assert client.auth_method == "device-profile"
    assert client.vlan == ""
    assert client.device_type == ""
    assert client.mac == "f0:1a:a0:45:b1:10"


def test_generated_radius_role_uses_the_base_role_name():
    assert resolved_role_name("RADIUS_0", {"base_role_name": "allow-any-anyv4"}) == "allow-any-anyv4"
    assert resolved_role_name("RADIUS_Overridden_12", {"base_role_name": "Employee"}) == "Employee"
    assert resolved_role_name("RADIUS_0", {}) == "RADIUS_0"
    assert resolved_role_name("Employee", {"base_role_name": "Other"}) == "Employee"


def test_previously_applied_role_is_not_a_current_client():
    clients = parse_clients({
        "aa:bb:cc:dd:ee:09": {
            "mac": "aa:bb:cc:dd:ee:09",
            "applied_role": None,
            "previously_applied_role": "Employee",
            "client_state": "authentication-failed",
            "onboarded_method": "mac-auth",
        }
    })
    assert clients == []


def test_vlan_from_role_is_multi_when_the_role_trunks():
    from app.aoscx import vlan_from_role

    assert vlan_from_role({
        "vlan_mode": "native-untagged",
        "vlan_name_tag": "MGMT",
        "vlan_tag": 199,
        "vlan_trunks": [2, 199, 200, 300],
    }) == "multi"
    assert vlan_from_role({"vlan_tag": 20, "vlan_trunks": []}) == "20"


def test_parse_lldp_chassis_name():
    payload = {"aa:bb:cc:dd:ee:ff": {"neighbor_info": {"chassis_name": "ap-lobby"}}}
    assert parse_lldp_name(payload) == "ap-lobby"


def test_login_failure_does_not_include_the_password():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["password"] == PASSWORD
        assert request.headers["x-use-csrf-token"] == "true"
        return httpx.Response(401, text="no")

    async def run() -> str:
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = AoscxSession(target(), client)
        try:
            await session.login()
        except AoscxError as exc:
            return str(exc)
        raise AssertionError("login should fail")

    message = asyncio.run(run())
    assert message == "Login failed (401)"
    assert PASSWORD not in message


def test_uri_only_interface_map_reads_each_port_link_state():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, headers={"X-CSRF-Token": "csrf-token"})
        path = unquote(request.url.path)
        if path.endswith("/subsystems"):
            return httpx.Response(200, json=chassis_body("R8Q72A"))
        if path.endswith("/system"):
            return httpx.Response(200, json={"hostname": "Office6200", "software_version": "ML.10.17"})
        if path.endswith("/interfaces"):
            return httpx.Response(
                200,
                json={
                    "1/1/1": "/rest/v10.17/system/interfaces/1%2F1%2F1",
                    "1/1/11": "/rest/v10.17/system/interfaces/1%2F1%2F11",
                },
            )
        if path.endswith("/1/1/1") or path.endswith("/1/1/11"):
            return httpx.Response(200, json={"link_state": "up"})
        if "/interfaces/" in path and path.count("/") > 6 and "port_access" not in path and "lldp" not in path:
            return httpx.Response(200, json={"link_state": "down"})
        if path.endswith("/1/1/1/port_access_clients") or path.endswith("/1/1/11/port_access_clients"):
            mac = "f0:1a:a0:45:b1:10" if path.endswith("/1/1/1/port_access_clients") else "20:9c:b4:c9:42:54"
            return httpx.Response(
                200,
                json={
                    mac: {
                        "mac": mac,
                        "applied_role": {"ARUBA-AP": "/rest/v10.17/system/port_access_roles/ARUBA-AP"},
                        "onboarded_method": "device-profile",
                        "client_state": "no-authentication-needed",
                        "access_vlan": None,
                    }
                },
            )
        if path.endswith("/port_access_roles/ARUBA-AP"):
            return httpx.Response(200, json={"vlan_tag": 199, "vlan_name_tag": "MGMT", "vlan_trunks": [2, 199, 200]})
        if path.endswith("/lldp_neighbors"):
            return httpx.Response(404, json={})
        return httpx.Response(404, json={})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = AoscxSession(target(), client)
        return await session.poll_access_ports()

    read = asyncio.run(run())
    assert read.model_id == "cx6200f-12"
    ports = read.ports
    assert ports[0].status == "up"
    assert ports[0].clients[0].role == "ARUBA-AP"
    assert ports[0].clients[0].auth_method == "device-profile"
    assert ports[0].clients[0].vlan == "multi"
    assert ports[10].status == "up"
    assert ports[10].clients[0].mac == "20:9c:b4:c9:42:54"
    assert ports[1].status == "down"
    assert ports[1].clients == []


def test_poll_rewrites_a_generated_radius_role_from_its_base_name():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, headers={"X-CSRF-Token": "csrf-token"})
        path = unquote(request.url.path)
        if path.endswith("/subsystems"):
            return httpx.Response(200, json=chassis_body("R8V13A"))
        if path.endswith("/system"):
            return httpx.Response(200, json={"hostname": "Office6200", "software_version": "ML.10.17"})
        if path.endswith("/interfaces"):
            return httpx.Response(200, json={"1/1/2": {"link_state": "up"}})
        if path.endswith("/port_access_clients"):
            return httpx.Response(
                200,
                json={
                    "28:de:65:ba:43:e4": {
                        "mac": "28:de:65:ba:43:e4",
                        "applied_role": {"RADIUS_0": "/rest/v10.17/system/port_access_roles/RADIUS_0"},
                        "onboarded_method": "mac-auth",
                        "client_state": "authenticated",
                        "access_vlan": 200,
                    }
                },
            )
        if path.endswith("/port_access_roles/RADIUS_0"):
            return httpx.Response(
                200,
                json={"base_role_name": "allow-any-anyv4", "vlan_tag": 200, "vlan_trunks": []},
            )
        if path.endswith("/lldp_neighbors"):
            return httpx.Response(404, json={})
        return httpx.Response(404, json={})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = AoscxSession(target(), client)
        return await session.poll_access_ports()

    read = asyncio.run(run())
    assert read.model_id == "cx6200f-12"
    ports = read.ports
    assert ports[1].clients[0].role == "allow-any-anyv4"
    assert ports[1].clients[0].vlan == "200"


def test_poll_uses_csrf_token_and_falls_back_from_depth_2():
    calls: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.url.params.get("depth", "")))
        if request.url.path.endswith("/login"):
            assert PASSWORD not in request.url.path
            return httpx.Response(200, headers={"X-CSRF-Token": "csrf-token"})
        assert request.headers["x-csrf-token"] == "csrf-token"
        path = request.url.path
        if path.endswith("/subsystems"):
            return httpx.Response(200, json=chassis_body("R8Q72A"))
        if path.endswith("/system"):
            return httpx.Response(200, json={"hostname": "lab-6200", "software_version": "ML.10.17", "platform_name": "6200"})
        if path.endswith("/interfaces"):
            return httpx.Response(
                200,
                json={
                    "1/1/1": {"link_state": "up"},
                    "1/1/4": {"link_state": "down"},
                },
            )
        if path.endswith("/port_access_clients"):
            if request.url.params.get("depth") == "2":
                return httpx.Response(400, json={"message": "depth"})
            return httpx.Response(
                200,
                json={
                    "aa:bb:cc:dd:ee:10": {
                        "mac": "aa:bb:cc:dd:ee:10",
                        "applied_role": "/rest/v10.16/system/port_access_roles/SecurityCamera",
                        "onboarded_method": "mac-auth",
                        "client_state": "authenticated",
                        "auth_attributes": {
                            "mac-auth": {"username": "cam", "auth_state": "authenticated"}
                        },
                    }
                },
            )
        if path.endswith("/lldp_neighbors"):
            return httpx.Response(404, json={})
        return httpx.Response(500, json={})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = AoscxSession(target(), client)
        return await session.poll_access_ports()

    read = asyncio.run(run())
    hostname, version, ports = read.hostname, read.software_version, read.ports
    assert read.model_id == "cx6200f-12"
    assert hostname == "lab-6200"
    assert version == "ML.10.17"
    assert ports[0].status == "up"
    assert ports[0].clients[0].role == "SecurityCamera"
    assert ports[0].lldp_neighbor == ""
    assert ports[3].status == "down"
    assert ports[3].clients == []
    assert any(path.endswith("/port_access_clients") and depth == "2" for _, path, depth in calls)
    assert any(path.endswith("/port_access_clients") and depth == "1" for _, path, depth in calls)
    assert PASSWORD not in repr(calls)


def test_product_info_holds_the_part_number():
    model, part = identify_chassis(
        {
            "chassis,1": {
                "type": "chassis",
                "product_info": {
                    "part_number": "R8Q72A#ACC",
                    "product_name": "6200F 12G Class4 PoE 2G/2SFP+ 139W Switch",
                },
            }
        }
    )
    assert model is not None and model.id == "cx6200f-12"
    assert part == "R8Q72A"


def test_part_number_picks_the_face_and_ignores_platform_name():
    model, part = identify_chassis({"1": {"type": "chassis", "part_number": "JL666A#ACC"}})
    assert model is not None and model.id == "cx6300f-24"
    assert part == "JL666A"
    model, part = identify_chassis(
        {
            "fan": {"type": "fan", "part_number": "JL666A"},
            "1": {"type": "chassis", "part_number": "R8V13A"},
        }
    )
    assert model is not None and model.id == "cx6200f-12"
    assert part == "R8V13A"
    model, part = identify_chassis(
        {"1": {"type": "chassis", "part_number": "JL725A", "product_description": "not a JL666A"}}
    )
    assert model is None
    assert part == "JL725A"
    model, part = identify_chassis({"1": {"type": "chassis", "product_name": "6300"}})
    assert model is None
    assert part == ""


def test_twenty_four_port_face_keeps_copper_and_drops_sfp():
    payload = {f"1/1/{number}": {"link_state": "up"} for number in (1, 24, 25)}
    ports = ports_from_interfaces(payload, 1, 24)
    assert [port.number for port in ports] == list(range(1, 25))
    assert ports[23].name == "1/1/24"
    assert ports[23].status == "up"
    assert all(port.number != 25 for port in ports)


def _poll(part: str, interfaces: dict, platform_name: str = "6300", queries: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/login"):
            return httpx.Response(200, headers={"X-CSRF-Token": "csrf-token"})
        path = unquote(request.url.path)
        if path.endswith("/subsystems"):
            if queries is not None:
                queries.append(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    "chassis,1": {
                        "type": "chassis",
                        "product_info": {"part_number": part, "product_name": part},
                    }
                },
            )
        if path.endswith("/system"):
            return httpx.Response(
                200,
                json={"hostname": "core", "software_version": "LL.10.15", "platform_name": platform_name},
            )
        if path.endswith("/interfaces") and "/interfaces/" not in path:
            return httpx.Response(200, json=interfaces)
        if path.endswith("/port_access_clients"):
            return httpx.Response(200, json={})
        if path.endswith("/lldp_neighbors"):
            return httpx.Response(404, json={})
        return httpx.Response(404, json={})

    async def run():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        session = AoscxSession(target(), client)
        return await session.poll_access_ports()

    return asyncio.run(run())


def test_subsystem_read_asks_for_product_info():
    queries: list[dict] = []
    read = _poll("R8Q72A", {"1/1/1": {"link_state": "up"}}, queries=queries)
    assert read.model_id == "cx6200f-12"
    assert queries[0]["attributes"] == "type,product_info"
    assert queries[0]["depth"] == "2"
    assert "part_number" not in queries[0]["attributes"]


def test_jl666a_and_taa_twin_select_the_24_port_face():
    for part in ("JL666A", "JL666A#ACC", "S0G96A"):
        read = _poll(part, {"1/1/1": {"link_state": "up"}, "1/1/24": {"link_state": "down"}, "1/1/25": {"link_state": "up"}})
        assert read.model_id == "cx6300f-24"
        assert read.model_heading == "AOS-CX 6300F"
        assert [port.number for port in read.ports] == list(range(1, 25))
        assert read.ports[0].status == "up"
        assert all(port.number < 25 for port in read.ports)
        assert read.model_note == ""


def test_unknown_part_and_extra_interfaces_leave_the_face_blank():
    unknown = _poll("JL725A", {"1/1/1": {"link_state": "up"}}, platform_name="6300")
    assert unknown.model_id == ""
    assert unknown.ports == []
    assert unknown.detected_part == "JL725A"
    assert "6200F 12-port" in unknown.model_note
    assert "6300F 24-port (JL666A)" in unknown.model_note

    conflict = _poll("JL666A", {"1/1/1": {"link_state": "up"}, "1/1/48": {"link_state": "up"}})
    assert conflict.model_id == ""
    assert conflict.ports == []
    assert "1/1/48" in conflict.model_note
