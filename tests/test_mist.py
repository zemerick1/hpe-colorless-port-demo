"""Mist wired-client parsing. Junos is a separate EX source."""

import asyncio

import httpx

from app.mist import MistSession, MistTarget, copper_index, ports_from_mist, roles_from_template


def test_copper_index_keeps_member_zero_access_ports():
    assert copper_index("ge-0/0/0") == 0
    assert copper_index("mge-0/0/11") == 11
    assert copper_index("xe-0/1/0") is None
    assert copper_index("ge-1/0/2") is None
    assert copper_index("ge-0/0/12") is None


def test_dynamic_filter_is_the_mist_role_and_hostname_is_kept():
    ports = ports_from_mist(
        [{"port_id": "mge-0/0/0", "up": True, "port_usage": "dot1x-only"}],
        [
            {
                "mac": "b827eb152c5e",
                "hostname": ["raspberrypi"],
                "manufacture": "Raspberry Pi Foundation",
                "port_id": ["mge-0/0/0"],
                "vlan": [2],
                "ip": ["172.16.17.12"],
                "device_mac_port": [
                    {"port_id": "mge-0/0/0", "dynamic_filter": "EMPLOYEE"},
                ],
            }
        ],
    )
    client = ports[0].clients[0]
    assert client.role == "dot1x-only"
    assert client.mist_role == "EMPLOYEE"
    assert client.device_name == "raspberrypi"
    assert client.device_type == "Raspberry Pi Foundation"
    assert client.vlan == "2"
    assert client.ip_address == "172.16.17.12"


def test_configured_profile_without_a_client_stays_dark():
    ports = ports_from_mist(
        [{"port_id": "ge-0/0/2", "up": True, "port_usage": "dot1x-only", "auth_state": "init", "mac_count": 0}],
        [],
    )
    port = ports[2]
    assert port.status == "up"
    assert port.clients == []


def test_connected_client_keeps_the_applied_profile_when_mist_role_is_absent():
    ports = ports_from_mist(
        [{"port_id": "mge-0/0/0", "up": True, "port_usage": "dot1x-only", "auth_state": ""}],
        [
            {
                "mac": "b827eb152c5e",
                "auth_state": "init",
                "port_id": ["mge-0/0/0"],
                "vlan": [-1],
                "dhcp_hostname": "raspberrypi",
            }
        ],
    )
    port = ports[0]
    assert port.name == "mge-0/0/0"
    assert port.status == "up"
    client = port.clients[0]
    assert client.role == "dot1x-only"
    assert client.mac == "b8:27:eb:15:2c:5e"
    assert client.device_name == "raspberrypi"
    assert client.vlan == ""


def test_poll_reads_device_ports_and_wired_clients_without_putting_the_token_in_the_url():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Token secret"
        assert "secret" not in str(request.url)
        path = request.url.path
        if path.endswith("/stats/devices/00000000-0000-0000-1000-001122334455"):
            return httpx.Response(
                200,
                json={"hostname": "lab-ex", "model": "EX4000-12MP", "version": "24.4R1"},
            )
        if path.endswith("/stats/ports/search"):
            assert request.url.params["mac"] == "001122334455"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "port_id": "mge-0/0/0",
                            "up": True,
                            "port_usage": "Employee",
                            "auth_state": "authenticated",
                            "neighbor_system_name": "ap-1",
                        },
                        {"port_id": "ge-0/0/0", "up": False, "port_usage": "ignored"},
                        {"port_id": "xe-0/1/2", "up": True, "port_usage": "uplink"},
                    ]
                },
            )
        if path.endswith("/wired_clients/search"):
            assert request.url.params["device_mac"] == "001122334455"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "mac": "112233445566",
                            "auth_state": "authenticated",
                            "auth_method": "mac_auth",
                            "port_id": ["mge-0/0/0"],
                            "vlan": [0, 100],
                            "ip": "172.16.17.12",
                            "dhcp_hostname": "lobby-pc",
                        }
                    ]
                },
            )
        return httpx.Response(404, json={})

    async def run():
        session = MistSession(
            MistTarget("api.mist.com", "secret", True),
            transport=httpx.MockTransport(handler),
        )
        try:
            return await session.poll_access_ports(
                "c168ddee-c14c-11e5-8e81-1258369c38a9",
                "00:11:22:33:44:55",
            )
        finally:
            await session.close()

    hostname, version, ports = asyncio.run(run())
    assert hostname == "lab-ex"
    assert version == "EX4000-12MP · 24.4R1"
    port = ports[0]
    assert port.name == "mge-0/0/0"
    assert port.status == "up"
    assert port.lldp_neighbor == "ap-1"
    assert port.clients[0].role == "Employee"
    assert port.clients[0].mac == "11:22:33:44:55:66"
    assert port.clients[0].ip_address == "172.16.17.12"
    assert port.clients[0].vlan == "100"
    assert port.clients[0].auth_method == "mac-auth"
    assert all(item.name != "xe-0/1/2" for item in ports)


def test_switch_template_keeps_radius_groups_and_drops_port_usage():
    names = roles_from_template({
        "name": "access",
        "acl_tags": {
            "EMPLOYEE": {"type": "radius_group", "radius_group": "EMPLOYEE"},
            "iot_tag": {"type": "aruba_user_role", "radius_group": "IOT"},
            "wired": {"type": "port_usage", "port_usage": "dot1x-only"},
            "guest": {"type": "subnet", "subnets": ["10.0.0.0/8"]},
        },
    })
    assert names == ["EMPLOYEE", "IOT"]
