"""Faceplate colors follow the old demo rules, and unknown roles stay visible."""

from app.aoscx import RawClient, RawPort
from app.snapshot import build_snapshot, match_profile, match_role

ROLES = [
    {
        "id": 1,
        "name": "Nothing_Connected",
        "display_name": "Nothing Connected",
        "description": "Nothing connected on this port.",
        "port_color": "",
        "legend_order": 0,
        "no_popover": True,
    },
    {
        "id": 2,
        "name": "Infrastructure",
        "display_name": "Infrastructure",
        "description": "Infrastructure device access.",
        "port_color": "#888888",
        "legend_order": 1,
        "no_popover": True,
    },
    {
        "id": 3,
        "name": "Employee",
        "display_name": "Employee",
        "description": "Standard access to the corporate network.",
        "port_color": "#FF8300",
        "legend_order": 3,
        "no_popover": False,
    },
    {
        "id": 4,
        "name": "SecurityCamera",
        "display_name": "SecurityCamera",
        "description": "Cloud video storage access only.",
        "port_color": "#D5D654",
        "legend_order": 5,
        "no_popover": False,
    },
    {
        "id": 5,
        "name": "Phone",
        "display_name": "Phone",
        "description": "PBX access only.",
        "port_color": "#307AF2",
        "legend_order": 6,
        "no_popover": False,
    },
    {
        "id": 8,
        "name": "Multiple_Roles",
        "display_name": "Multiple Roles",
        "description": "Port has multiple clients connected with multiple roles.",
        "port_color": "#E702F7",
        "legend_order": 7,
        "no_popover": False,
    },
]

SETTINGS = {
    "vsf_member": 1,
    "port_up_role_id": 2,
    "port_down_role_id": 1,
    "multiple_roles_role_id": 8,
    "show_device_name_on_mac": True,
    "visualize_unknown": True,
    "hide_previous_popovers": True,
    "screen_interval_sec": 0.5,
}


def paint(ports, **overrides):
    settings = dict(SETTINGS)
    settings.update(overrides)
    snap = build_snapshot(ports, settings, ROLES, {"configured": True})
    return {port["number"]: port for port in snap["ports"]}, snap


def client(mac, role, method="mac-auth", username="", device_name="", forwarding="Bridged"):
    return RawClient(mac, username, method, role, "", device_name, "20", forwarding, "")


def port(number, status="up", clients=None, lldp=""):
    return RawPort(number, f"1/1/{number}", status, lldp, list(clients or []))


def test_role_match_strips_downloadable_prefix_and_suffix():
    assert match_role("*Employee-12", ROLES)["name"] == "Employee"
    assert match_role("*Employee-4821", ROLES)["name"] == "Employee"
    assert match_role("Employee*", ROLES)["name"] == "Employee"
    roles = ROLES + [{
        "id": 3,
        "name": "AccessPoint",
        "display_name": "AccessPoint",
        "description": "Access point.",
        "port_color": "#26F263",
        "legend_order": 2,
        "no_popover": False,
    }]
    assert match_role("ARUBA-AP", roles)["name"] == "AccessPoint"
    assert match_role("ARUBA-AP", roles + [{
        "id": 9,
        "name": "ARUBA-AP",
        "display_name": "ARUBA-AP",
        "description": "Exact switch role.",
        "port_color": "#112233",
        "legend_order": 2,
        "no_popover": False,
    }])["name"] == "ARUBA-AP"
    roles = [{**ROLES[3], "name": "Security_Camera", "display_name": "Security Camera"}]
    assert match_role("Security Camera", roles)["name"] == "Security_Camera"
    assert match_role("Security-Camera", roles)["name"] == "Security_Camera"
    assert match_role("", ROLES) is None


def test_one_client_uses_that_role_color():
    ports, snap = paint([
        port(5, clients=[client("aa:bb:cc:dd:ee:05", "SecurityCamera", device_name="Lobby Cam")], lldp="ap-1")
    ])
    painted = ports[5]
    assert painted["color"] == "#D5D654"
    assert painted["status"] == "up"
    assert painted["num_clients"] == 1
    assert painted["auto_popover"] is True
    assert painted["lldp_neighbor"] == "ap-1"
    assert painted["clients"][0]["username_title"] == "Device name"
    assert painted["clients"][0]["username"] == "Lobby Cam"
    assert painted["clients"][0]["auth_method"] == "MAC-based"
    assert painted["clients"][0]["role_description"] == "Cloud video storage access only."
    labels = [item["label"] for item in snap["legend"]]
    assert "Nothing Connected" not in labels
    assert "SecurityCamera" in labels
    assert ports[1]["color"] == ""
    assert ports[1]["status"] == "down"


def test_two_roles_use_the_multiple_color_and_two_of_the_same_do_not():
    mixed, _snap = paint([
        port(7, clients=[
            client("aa:bb:cc:dd:ee:07", "Employee", username="ada"),
            client("aa:bb:cc:dd:ee:08", "Phone", method="dot1x", username="phone"),
        ])
    ])
    assert mixed[7]["color"] == "#E702F7"
    assert mixed[7]["role_label"] == "Multiple Roles"
    assert mixed[7]["num_clients"] == 2
    assert mixed[7]["clients"][1]["username_title"] == "Username"
    assert mixed[7]["clients"][1]["auth_method"] == "802.1X"

    same, _snap = paint([
        port(7, clients=[
            client("aa:bb:cc:dd:ee:07", "*Employee-3", username="ada"),
            client("aa:bb:cc:dd:ee:08", "Employee", username="bob"),
        ])
    ])
    assert same[7]["color"] == "#FF8300"
    assert same[7]["num_clients"] == 2


def test_port_up_client_stays_visible_and_an_empty_link_stays_dark():
    session, _snap = paint([
        port(2, clients=[client("aa:bb:cc:dd:ee:02", "Infrastructure", username="badge")])
    ])
    assert session[2]["num_clients"] == 1
    assert session[2]["color"] == "#888888"
    assert session[2]["auto_popover"] is False
    assert session[2]["clients"][0]["role_label"] == "Infrastructure"
    assert session[2]["clients"][0]["username"] == "badge"
    assert session[2]["clients"][0]["detail"] is True

    bare, _snap = paint([port(2)])
    assert bare[2]["status"] == "up"
    assert bare[2]["num_clients"] == 0
    assert bare[2]["color"] == ""
    assert bare[2]["role_label"] == ""
    assert bare[2]["auto_popover"] is False

    unknown, _snap = paint([
        port(3, clients=[client("aa:bb:cc:dd:ee:03", "Contractor", username="sam")])
    ])
    assert unknown[3]["color"] == "#888888"
    assert unknown[3]["num_clients"] == 1
    assert unknown[3]["clients"][0]["role_label"] == "Contractor"
    assert unknown[3]["auto_popover"] is True


def test_device_profile_client_uses_its_role_color():
    roles = ROLES + [{
        "id": 9,
        "name": "ARUBA-AP",
        "display_name": "ARUBA-AP",
        "description": "Wired access point.",
        "port_color": "#26F263",
        "legend_order": 2,
        "no_popover": False,
    }]
    snap = build_snapshot(
        [RawPort(1, "1/1/1", "up", "ap-lobby", [
            RawClient("f0:1a:a0:45:b1:10", "", "device-profile", "ARUBA-AP", "", "", "multi", "Bridged", ""),
        ])],
        SETTINGS,
        roles,
        {"configured": True},
    )
    painted = snap["ports"][0]
    assert painted["color"] == "#26F263"
    assert painted["num_clients"] == 1
    assert painted["auto_popover"] is True
    client = painted["clients"][0]
    assert client["auth_method"] == "Device profile"
    assert client["role_label"] == "ARUBA-AP"
    assert client["username_title"] == "Device name"
    assert client["username"] == "f0:1a:a0:45:b1:10"
    assert client["vlan"] == "multi"


def test_ex_applied_profile_uses_its_own_list_and_an_empty_link_stays_dark():
    from app.mist import ports_from_mist

    profiles = [
        {
            "id": 1,
            "name": "dot1x-only",
            "display_name": "802.1X only",
            "description": "Wired 802.1X access.",
            "port_color": "#307AF2",
            "legend_order": 1,
            "no_popover": False,
        },
        {
            "id": 2,
            "name": "Phone",
            "display_name": "Phone",
            "description": "",
            "port_color": "#99DAF8",
            "legend_order": 2,
            "no_popover": False,
        },
    ]
    ports = ports_from_mist(
        [
            {
                "port_id": "mge-0/0/0",
                "up": True,
                "port_usage": "dot1x-only",
                "auth_state": "",
                "neighbor_system_name": "",
            },
            {"port_id": "ge-0/0/1", "up": True, "port_usage": "Employee", "auth_state": "init"},
            {"port_id": "xe-0/1/0", "up": True, "port_usage": "uplink"},
            {"port_id": "ge-0/0/3", "up": True, "port_usage": "Phone", "auth_state": "authenticated"},
            {"port_id": "ge-0/0/4", "up": True, "port_usage": "lan", "mac_count": 1},
        ],
        [
            {
                "mac": "b827eb152c5e",
                "auth_state": "init",
                "auth_method": "",
                "port_id": ["mge-0/0/0"],
                "vlan": [-1],
                "ip": "",
                "dhcp_hostname": "raspberrypi",
            }
        ],
    )
    snap = build_snapshot(ports, SETTINGS, ROLES, {"configured": True}, platform="ex", profiles=profiles)
    assert snap["platform"] == "ex"
    assert [item["label"] for item in snap["legend"]] == ["802.1X only", "Phone", "lan"]
    assert snap["legend"][-1]["color"] == "#888888"
    assert match_profile("Dot1X Only", profiles)["name"] == "dot1x-only"
    lit = snap["ports"][0]
    assert lit["name"] == "mge-0/0/0"
    assert lit["color"] == "#307AF2"
    client = lit["clients"][0]
    assert client["kind"] == "profile"
    assert client["role_label"] == "802.1X only"
    assert client["username"] == "raspberrypi"
    assert client["username_title"] == "Device name"
    assert client["vlan"] == ""
    assert client["mac"] == "b8:27:eb:15:2c:5e"
    assert snap["ports"][1]["color"] == ""
    assert snap["ports"][1]["status"] == "up"
    phone = snap["ports"][3]
    assert phone["color"] == "#99DAF8"
    assert phone["name"] == "ge-0/0/3"
    unknown = snap["ports"][4]
    assert unknown["color"] == "#888888"
    assert unknown["clients"][0]["role_label"] == "lan"
    assert unknown["clients"][0]["role_description"] == "This port profile is not on the admin list yet."
    assert all(port["name"] != "xe-0/1/0" for port in snap["ports"])
    cx = build_snapshot(ports, SETTINGS, ROLES, {"configured": True}, profiles=profiles)
    assert "802.1X only" not in [item["label"] for item in cx["legend"]]


def test_ex_mist_role_colors_the_jack_ahead_of_the_port_profile():
    mist_roles = [
        {
            "id": 1,
            "name": "EMPLOYEE",
            "display_name": "Employee",
            "description": "Staff access.",
            "port_color": "#FF8300",
            "legend_order": 1,
            "no_popover": False,
        },
        {
            "id": 2,
            "name": "IOT",
            "display_name": "IoT",
            "description": "",
            "port_color": "#99DAF8",
            "legend_order": 2,
            "no_popover": False,
        },
    ]
    profiles = [
        {
            "id": 3,
            "name": "dot1x-only",
            "display_name": "802.1X only",
            "description": "Wired 802.1X.",
            "port_color": "#307AF2",
            "legend_order": 1,
            "no_popover": False,
        }
    ]
    ports = [
        RawPort(0, "mge-0/0/0", "up", "", [
            RawClient(
                "b8:27:eb:15:2c:5e", "", "", "dot1x-only",
                "Raspberry Pi Foundation", "raspberrypi", "2", "Bridged", "",
                "172.16.17.12", mist_role="EMPLOYEE",
            ),
        ]),
        RawPort(1, "ge-0/0/1", "up", "", [
            RawClient("aa:bb:cc:dd:ee:10", "", "", "dot1x-only", "", "cam", "200", "Bridged", "", mist_role="CAMERA"),
        ]),
        RawPort(2, "ge-0/0/2", "up", "", [
            RawClient("aa:bb:cc:dd:ee:11", "", "", "dot1x-only", "", "lobby", "999", "Bridged", ""),
        ]),
    ]
    snap = build_snapshot(
        ports, SETTINGS, ROLES, {"configured": True},
        platform="ex", profiles=profiles, mist_roles=mist_roles,
    )
    employee = snap["ports"][0]
    assert employee["color"] == "#FF8300"
    assert employee["clients"][0]["role_label"] == "802.1X only"
    assert employee["clients"][0]["mist_role_label"] == "Employee"
    assert employee["clients"][0]["username"] == "raspberrypi"
    camera = snap["ports"][1]
    assert camera["color"] == "#888888"
    assert camera["clients"][0]["mist_role_label"] == "CAMERA"
    plain = snap["ports"][2]
    assert plain["color"] == "#307AF2"
    assert plain["clients"][0]["mist_role_label"] == ""
    kinds = [(item["kind"], item["label"]) for item in snap["legend"]]
    assert ("role", "Employee") in kinds
    assert ("role", "IoT") in kinds
    assert ("role", "CAMERA") in kinds
    assert ("profile", "802.1X only") in kinds


def test_link_down_and_hidden_port_up_have_no_lamp_when_visualize_is_off():
    down, _snap = paint([port(4, status="down", clients=[client("aa:bb:cc:dd:ee:04", "Employee")])])
    assert down[4]["color"] == ""
    assert down[4]["auto_popover"] is False

    dark, _snap = paint([port(6)], visualize_unknown=False)
    assert dark[6]["status"] == "up"
    assert dark[6]["color"] == ""
    assert dark[6]["auto_popover"] is False
