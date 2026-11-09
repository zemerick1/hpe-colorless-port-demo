"""One settings record. Secrets are stored and are not returned to the browser."""

import asyncio
import json
from pathlib import Path

from app.aoscx import AoscxError, ChassisPoll, RawClient, RawPort
from app.clearpass import ClearPassError, EndpointInfo
from app.db import get_settings
from app.mist import MistError
from app.poller import Poller

PASSWORD = "saved-switch-password"
SECRET = "saved-clearpass-secret"
TOKEN = "saved-mist-token"


def roles_of(config):
    return config["roles"]


def test_seed_and_pages(client):
    health = client.get("/api/health")
    assert health.json() == {"ok": True}
    assert "no-store" in health.headers["cache-control"]
    page = client.get("/").text
    assert 'id="faceplate"' in page
    assert 'id="faceplate-6300"' in page
    assert 'id="faceplate-6300m"' in page
    assert "/static/cx6300f-24.png" in page
    assert "/static/cx6300m-24.png" in page
    assert 'width="1456" height="144"' in page
    assert page.count('width="1456" height="144"') == 2
    assert page.count('id="port-1"') == 1
    assert page.count('data-port="24"') == 2
    assert page.count('data-port="1" data-row="top" aria-label="Port 1" style="left:43.96%') == 2
    assert page.count('data-port="9" data-row="top" aria-label="Port 9" style="left:56.52%') == 1
    assert page.count('data-port="9" data-row="top" aria-label="Port 9" style="left:58.31%') == 1
    assert "6300F 24-port (JL666A)" in page
    assert "6300M 24-port (JL660A)" in page
    assert 'id="open-faq"' in page
    css = client.get("/static/demo.css").text
    assert "aspect-ratio: 1254 / 216" in css
    assert "object-fit" not in css
    assert "height: auto" in css
    admin = client.get("/admin")
    assert 'id="config-form"' in admin.text
    assert 'id="open-faq"' in admin.text
    assert "Single demo" in admin.text
    assert 'id="supported-models"' in admin.text
    assert "6300F 24-port (JL666A)" in admin.text
    assert "6300M 24-port (JL660A)" in admin.text

    config = client.get("/api/admin/config").json()
    blob = json.dumps(config)
    assert "switch_password" not in config
    assert config["switch_password_set"] is False
    assert config["clearpass_client_secret_set"] is False
    assert config["mist_api_token_set"] is False
    assert len(config["roles"]) == 9
    specials = {role["special"] for role in config["roles"]}
    assert specials == {"", "up", "down", "multi"}
    assert PASSWORD not in blob

    snap = client.get("/api/snapshot").json()
    assert snap["ports"] == []
    assert snap["access_port_count"] == 0
    assert snap["model"] == ""
    assert snap["supported_models"] == [
        "6200F 12-port",
        "6300F 24-port (JL666A)",
        "6300M 24-port (JL660A)",
    ]
    assert all(item["label"] != "Nothing Connected" for item in snap["legend"])


def test_secrets_round_trip_and_specials(client, db_path):
    config = client.get("/api/admin/config").json()
    payload = {
        "switch_host": "192.0.2.10",
        "switch_port": 443,
        "switch_username": "admin",
        "switch_password": "",
        "api_version": "v10.17",
        "switch_verify_tls": False,
        "vsf_member": 1,
        "clearpass_host": "",
        "clearpass_client_id": "",
        "clearpass_client_secret": "",
        "clearpass_verify_tls": False,
        "mist_host": "api.mist.com",
        "mist_api_token": "",
        "mist_verify_tls": True,
        "poll_interval_sec": 1,
        "screen_interval_sec": 0.5,
        "show_device_name_on_mac": True,
        "visualize_unknown": True,
        "hide_previous_popovers": True,
        "roles": roles_of(config),
    }
    missing = client.put("/api/admin/config", json=payload)
    assert missing.status_code == 400
    assert missing.json()["detail"] == "Switch password is required"

    payload["switch_password"] = PASSWORD
    payload["clearpass_host"] = "https://cppm.example/api"
    payload["clearpass_client_id"] = "demo-client"
    payload["clearpass_client_secret"] = SECRET
    payload["mist_api_token"] = TOKEN
    saved = client.put("/api/admin/config", json=payload)
    assert saved.status_code == 200
    body = saved.json()
    text = json.dumps(body)
    assert PASSWORD not in text
    assert SECRET not in text
    assert TOKEN not in text
    assert body["switch_password_set"] is True
    assert body["clearpass_client_secret_set"] is True
    assert body["mist_api_token_set"] is True
    assert body["api_version"] == "v10.17"

    payload["switch_password"] = ""
    payload["clearpass_client_secret"] = ""
    payload["mist_api_token"] = ""
    payload["switch_username"] = "operator"
    again = client.put("/api/admin/config", json=payload)
    assert again.status_code == 200
    stored = get_settings(db_path)
    assert stored["switch_username"] == "operator"
    assert stored["switch_password"] == PASSWORD
    assert stored["clearpass_client_secret"] == SECRET
    assert stored["mist_api_token"] == TOKEN

    broken = json.loads(json.dumps(payload))
    for role in broken["roles"]:
        role["special"] = ""
    rejected = client.put("/api/admin/config", json=broken)
    assert rejected.status_code == 400
    assert "Port up" in rejected.json()["detail"]

    bad_version = json.loads(json.dumps(payload))
    bad_version["api_version"] = "10.16"
    assert client.put("/api/admin/config", json=bad_version).status_code == 400


def test_connection_checks_do_not_echo_secrets(client, monkeypatch):
    config = client.get("/api/admin/config").json()
    payload = {
        "switch_host": "192.0.2.10",
        "switch_port": 443,
        "switch_username": "admin",
        "switch_password": PASSWORD,
        "api_version": "v10.16",
        "switch_verify_tls": False,
        "vsf_member": 1,
        "clearpass_host": "cppm.example",
        "clearpass_client_id": "demo-client",
        "clearpass_client_secret": SECRET,
        "clearpass_verify_tls": False,
        "mist_host": "api.mist.com",
        "mist_api_token": TOKEN,
        "mist_verify_tls": True,
        "poll_interval_sec": 1,
        "screen_interval_sec": 0.5,
        "show_device_name_on_mac": True,
        "visualize_unknown": True,
        "hide_previous_popovers": True,
        "roles": roles_of(config),
    }
    assert client.put("/api/admin/config", json=payload).status_code == 200

    class Boom:
        def __init__(self, target):
            self.target = target

        async def poll_access_ports(self):
            raise AoscxError("Login failed (401)")

        async def close(self):
            return None

    monkeypatch.setattr("app.main.AoscxSession", Boom)
    client.app.state.poll.hostname = "keep-me"
    client.app.state.poll.raw_ports = [RawPort(1, "1/1/1", "up")]
    failed = client.post("/api/admin/test/switch", json=payload)
    assert failed.status_code == 200
    assert failed.json() == {"ok": False, "error": "Login failed (401)"}
    assert PASSWORD not in failed.text
    assert client.app.state.poll.hostname == "keep-me"

    class Good:
        def __init__(self, target):
            assert target.password == PASSWORD

        async def poll_access_ports(self):
            return ChassisPoll(
                "lab-6200",
                "ML.10.17",
                [RawPort(1, "1/1/1", "up", "", [RawClient("aa", "", "mac-auth", "Employee", "", "", "1", "Bridged", "")])],
                model_id="cx6200f-12",
                model_label="6200F 12-port",
                model_heading="AOS-CX 6200F",
                detected_part="R8Q72A",
            )

        async def close(self):
            return None

    monkeypatch.setattr("app.main.AoscxSession", Good)
    ok = client.post("/api/admin/test/switch", json={**payload, "switch_password": ""})
    assert ok.json()["ok"] is True
    assert ok.json()["hostname"] == "lab-6200"
    assert ok.json()["ports_up"] == 1
    assert ok.json()["clients"] == 1
    assert client.app.state.poll.hostname == "lab-6200"
    assert PASSWORD not in ok.text

    async def clearpass_ok(self):
        return None

    monkeypatch.setattr("app.main.ClearPassSession.ping", clearpass_ok)
    checked = client.post("/api/admin/test/clearpass", json={**payload, "clearpass_client_secret": ""})
    assert checked.json()["ok"] is True
    assert SECRET not in checked.text

    async def mist_denied(target, client=None):
        raise MistError("Mist rejected the token (403)")

    monkeypatch.setattr("app.main.check_mist", mist_denied)
    denied = client.post("/api/admin/test/mist", json={**payload, "mist_api_token": ""})
    assert denied.json()["ok"] is False
    assert TOKEN not in denied.text


def test_clearpass_lookup_failure_keeps_the_switch_snapshot(db_path, monkeypatch):
    from types import SimpleNamespace

    from app.poller import PollStatus

    calls = {"n": 0}

    class SwitchFake:
        def __init__(self, target):
            pass

        async def close(self):
            return None

        async def poll_access_ports(self):
            return ChassisPoll(
                "lab-6200",
                "ML.10.17",
                [RawPort(1, "1/1/1", "up", "ap", [RawClient(
                    "aa:bb:cc:dd:ee:01", "", "mac-auth", "Employee", "", "", "20", "Bridged", ""
                )])],
                model_id="cx6200f-12",
                detected_part="R8Q72A",
            )

    class ClearPassFake:
        def __init__(self, target):
            pass

        async def close(self):
            return None

        async def endpoint(self, mac):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ClearPassError("ClearPass endpoint lookup failed (500)")
            return EndpointInfo(device_type="Camera", device_name="Lobby Cam")

    monkeypatch.setattr("app.poller.AoscxSession", SwitchFake)
    monkeypatch.setattr("app.poller.ClearPassSession", ClearPassFake)
    app = SimpleNamespace()
    app.state = SimpleNamespace(poll=PollStatus(), db_path=db_path)
    poller = Poller(app)
    settings = {
        "switch_host": "192.0.2.10",
        "switch_port": 443,
        "switch_username": "admin",
        "switch_password": PASSWORD,
        "api_version": "v10.16",
        "switch_verify_tls": False,
        "vsf_member": 1,
        "clearpass_host": "cppm.example",
        "clearpass_client_id": "demo-client",
        "clearpass_client_secret": SECRET,
        "clearpass_verify_tls": False,
    }
    asyncio.run(poller.poll_once(settings))
    assert app.state.poll.switch_ok is True
    assert app.state.poll.hostname == "lab-6200"
    assert app.state.poll.raw_ports[0].clients[0].device_name == ""
    assert app.state.poll.clearpass_ok is False
    assert "500" in app.state.poll.clearpass_error

    asyncio.run(poller.poll_once(settings))
    client = app.state.poll.raw_ports[0].clients[0]
    assert client.device_name == "Lobby Cam"
    assert client.device_type == "Camera"
    assert app.state.poll.clearpass_ok is True

    asyncio.run(poller.poll_once(settings))
    assert calls["n"] == 2


SITE = "c168ddee-c14c-11e5-8e81-1258369c38a9"
EX_MAC = "00:11:22:33:44:55"


def _base_payload(config):
    return {
        "switch_host": "",
        "switch_port": 443,
        "switch_username": "",
        "switch_password": "",
        "api_version": "v10.16",
        "switch_verify_tls": False,
        "vsf_member": 1,
        "clearpass_host": "",
        "clearpass_client_id": "",
        "clearpass_client_secret": "",
        "clearpass_verify_tls": False,
        "mist_host": "api.mist.com",
        "mist_api_token": "",
        "mist_verify_tls": True,
        "ex_site_id": "",
        "ex_switch_mac": "",
        "poll_interval_sec": 1,
        "screen_interval_sec": 0.5,
        "show_device_name_on_mac": True,
        "visualize_unknown": False,
        "hide_previous_popovers": True,
        "roles": roles_of(config),
    }


def test_ex_faceplate_is_separate_and_settings_round_trip(client, db_path):
    page = client.get("/").text
    assert 'id="platform-ex"' in page
    assert 'id="faceplate-ex"' in page
    assert "ex12p.png" in page
    css = Path(__file__).parents[1].joinpath("static/demo.css").read_text()
    assert ".faceplate .port {" in css
    assert "#faceplate .port" not in css
    admin = client.get("/admin").text
    assert 'data-section="aruba"' in admin
    assert 'data-section="juniper"' in admin
    assert 'data-section="ex"' in admin
    assert 'data-section="profiles"' in admin
    assert 'data-section="mist-roles"' in admin
    assert "<summary>Aruba</summary>" in admin
    assert "<summary>Aruba Roles</summary>" in admin
    assert "<summary>Juniper/Mist</summary>" in admin
    assert "<summary>Roles</summary>" in admin
    assert "<summary>ClearPass</summary>" in admin
    assert "<summary>Timing</summary>" in admin
    assert "Port profiles" in admin
    assert "Junos" in admin
    aruba = admin.index('data-section="aruba"')
    switch = admin.index('data-section="switch"')
    roles = admin.index('data-section="roles"')
    juniper = admin.index('data-section="juniper"')
    mist = admin.index('data-section="mist"')
    ex = admin.index('data-section="ex"')
    profiles = admin.index('data-section="profiles"')
    mist_roles = admin.index('data-section="mist-roles"')
    clearpass = admin.index('data-section="clearpass"')
    timing = admin.index('data-section="timing"')
    assert aruba < switch < roles < juniper
    assert juniper < mist < ex < profiles < mist_roles
    assert mist_roles < clearpass < timing

    cx = client.get("/api/snapshot").json()
    assert cx["platform"] == "cx"
    assert cx["ports"] == []
    assert cx["model"] == ""
    ex = client.get("/api/snapshot?platform=ex").json()
    assert ex["platform"] == "ex"
    assert [port["number"] for port in ex["ports"]] == list(range(12))
    assert ex["poll"]["configured"] is False
    assert client.get("/api/snapshot?platform=junos").status_code == 400

    config = client.get("/api/admin/config").json()
    payload = _base_payload(config)
    payload["ex_site_id"] = SITE
    missing = client.put("/api/admin/config", json=payload)
    assert missing.status_code == 400
    payload["ex_switch_mac"] = EX_MAC
    needs_token = client.put("/api/admin/config", json=payload)
    assert needs_token.status_code == 400
    assert "token" in needs_token.json()["detail"].lower()

    payload["mist_api_token"] = TOKEN
    saved = client.put("/api/admin/config", json=payload)
    assert saved.status_code == 200
    body = saved.json()
    assert TOKEN not in json.dumps(body)
    assert body["ex_site_id"] == SITE
    assert body["ex_switch_mac"] == EX_MAC
    assert body["mist_api_token_set"] is True
    assert body["poll"]["ex"]["configured"] is True
    stored = get_settings(db_path)
    assert stored["mist_api_token"] == TOKEN
    assert stored["ex_switch_mac"] == EX_MAC

    payload["mist_api_token"] = ""
    payload["ex_site_id"] = ""
    payload["ex_switch_mac"] = ""
    cleared = client.put("/api/admin/config", json=payload)
    assert cleared.status_code == 200
    assert cleared.json()["ex_site_id"] == ""
    assert get_settings(db_path)["mist_api_token"] == TOKEN


def test_port_profiles_are_separate_from_roles(client, db_path):
    config = client.get("/api/admin/config").json()
    assert config["profiles"] == []
    assert [role["name"] for role in config["mist_roles"]] == ["EMPLOYEE", "IOT"]
    payload = _base_payload(config)
    payload["profiles"] = [
        {
            "name": "dot1x-only",
            "display_name": "802.1X only",
            "description": "Wired access.",
            "port_color": "#307AF2",
            "legend_order": 1,
            "no_popover": False,
        }
    ]
    saved = client.put("/api/admin/config", json=payload)
    assert saved.status_code == 200
    body = saved.json()
    assert body["profiles"][0]["name"] == "dot1x-only"
    assert body["profiles"][0]["display_name"] == "802.1X only"
    assert body["profiles"][0]["id"]
    profile_id = body["profiles"][0]["id"]

    payload["profiles"] = [
        body["profiles"][0],
        {
            "name": "DOT1X-ONLY",
            "display_name": "Duplicate",
            "port_color": "#000000",
            "legend_order": 2,
        },
    ]
    duplicate = client.put("/api/admin/config", json=payload)
    assert duplicate.status_code == 400
    assert "duplicated" in duplicate.json()["detail"].lower()

    payload["profiles"] = [body["profiles"][0]]
    payload["profiles"][0]["display_name"] = "Dot1x"
    again = client.put("/api/admin/config", json=payload)
    assert again.status_code == 200
    assert again.json()["profiles"][0]["id"] == profile_id
    assert again.json()["profiles"][0]["display_name"] == "Dot1x"

    omitted = _base_payload(client.get("/api/admin/config").json())
    kept = client.put("/api/admin/config", json=omitted)
    assert kept.status_code == 200
    assert kept.json()["profiles"][0]["name"] == "dot1x-only"

    cx = client.get("/api/snapshot").json()
    assert "802.1X only" not in [item["label"] for item in cx["legend"]]
    assert "Dot1x" not in [item["label"] for item in cx["legend"]]

    from app.aoscx import RawClient, RawPort

    client.app.state.poll.ex_ports = [
        RawPort(0, "mge-0/0/0", "up", "", [
            RawClient("b8:27:eb:15:2c:5e", "", "", "dot1x-only", "", "raspberrypi", "", "Bridged", ""),
        ])
    ]
    ex = client.get("/api/snapshot?platform=ex").json()
    assert [item["label"] for item in ex["legend"] if item["kind"] == "profile"] == ["Dot1x"]
    assert [item["label"] for item in ex["legend"] if item["kind"] == "role"][:2] == ["Employee", "IoT"]
    assert ex["ports"][0]["color"] == "#307AF2"
    assert ex["ports"][0]["clients"][0]["kind"] == "profile"
    assert ex["ports"][0]["clients"][0]["username"] == "raspberrypi"

    payload = _base_payload(client.get("/api/admin/config").json())
    payload["profiles"] = []
    cleared = client.put("/api/admin/config", json=payload)
    assert cleared.status_code == 200
    assert cleared.json()["profiles"] == []


def test_ex_check_failure_keeps_the_last_ports(client, monkeypatch):
    from app.aoscx import RawPort
    from app.mist import MistError

    client.app.state.poll.ex_hostname = "keep-me"
    client.app.state.poll.ex_ports = [RawPort(0, "ge-0/0/0", "up")]

    class Boom:
        def __init__(self, target):
            assert target.api_token == TOKEN

        async def poll_access_ports(self, site, mac):
            raise MistError("Mist site or switch was not found (404)")

        async def close(self):
            return None

    monkeypatch.setattr("app.main.MistSession", Boom)
    failed = client.post(
        "/api/admin/test/ex",
        json={
            "mist_host": "api.mist.com",
            "mist_api_token": TOKEN,
            "mist_verify_tls": True,
            "ex_site_id": SITE,
            "ex_switch_mac": EX_MAC,
        },
    )
    assert failed.status_code == 200
    assert failed.json() == {"ok": False, "error": "Mist site or switch was not found (404)"}
    assert TOKEN not in failed.text
    assert client.app.state.poll.ex_hostname == "keep-me"
    assert client.app.state.poll.ex_ports[0].status == "up"


JUNOS_PASSWORD = "junos-secret"


def test_role_loads_merge_colors_and_keep_stored_secrets(client, db_path, monkeypatch):
    admin = client.get("/admin").text
    assert admin.index('data-section="mist"') < admin.index('data-section="junos"')
    assert admin.index('data-section="junos"') < admin.index('data-section="ex"')
    assert 'id="load-junos-roles"' in admin
    assert 'id="load-mist-roles"' in admin
    assert 'id="ex-source-mist"' in admin
    assert 'id="ex-source-junos"' in admin
    assert admin.index('data-section="ex-source"') < admin.index('data-section="mist"')
    assert 'id="junos-status"' in admin
    assert admin.index("</form>") < admin.index('id="faq"')
    page = client.get("/").text
    actions = page.index('class="top-actions"')
    assert actions < page.index('id="open-faq"') < page.index('href="/admin"')

    config = client.get("/api/admin/config").json()
    employee = next(role for role in config["mist_roles"] if role["name"] == "EMPLOYEE")
    payload = _base_payload(config)
    payload.update({
        "junos_host": "192.0.2.8",
        "junos_port": 3443,
        "junos_username": "lab",
        "junos_password": JUNOS_PASSWORD,
        "mist_api_token": TOKEN,
        "ex_site_id": SITE,
        "ex_switch_mac": EX_MAC,
    })
    saved = client.put("/api/admin/config", json=payload)
    assert saved.status_code == 200
    assert JUNOS_PASSWORD not in saved.text
    assert TOKEN not in saved.text
    assert saved.json()["junos_password_set"] is True
    assert saved.json()["poll"]["ex"]["source"] == "junos"

    seen = {}

    class FakeJunos:
        def __init__(self, target):
            seen["password"] = target.password
            seen["host"] = target.host

        async def filter_names(self):
            return ["EMPLOYEE", "CAMERA"]

        async def close(self):
            return None

    monkeypatch.setattr("app.main.JunosSession", FakeJunos)
    loaded = client.post(
        "/api/admin/roles/junos",
        json={
            "junos_host": "192.0.2.8",
            "junos_port": 3443,
            "junos_username": "lab",
            "junos_password": "",
            "mist_roles": [employee],
        },
    )
    assert loaded.status_code == 200
    body = loaded.json()
    assert body["ok"] is True
    assert body["added"] == ["CAMERA"]
    assert body["present"] == ["EMPLOYEE"]
    kept = next(role for role in body["roles"] if role["name"] == "EMPLOYEE")
    assert kept["port_color"] == employee["port_color"]
    camera = next(role for role in body["roles"] if role["name"] == "CAMERA")
    assert camera["port_color"] != employee["port_color"]
    assert camera["description"] == "Ethernet-switching firewall filter on the switch."
    assert JUNOS_PASSWORD not in loaded.text
    assert seen["password"] == JUNOS_PASSWORD
    assert [role["name"] for role in client.get("/api/admin/config").json()["mist_roles"]] == [
        "EMPLOYEE",
        "IOT",
    ]

    class EmptyJunos(FakeJunos):
        async def filter_names(self):
            return []

    monkeypatch.setattr("app.main.JunosSession", EmptyJunos)
    empty = client.post(
        "/api/admin/roles/junos",
        json={
            "junos_host": "192.0.2.8",
            "junos_username": "lab",
            "junos_password": "",
            "mist_roles": [employee],
        },
    )
    assert empty.status_code == 200
    assert empty.json() == {"ok": False, "error": "Junos has no ethernet-switching filters"}
    assert JUNOS_PASSWORD not in empty.text

    class FakeMist:
        def __init__(self, target):
            seen["token"] = target.api_token

        async def switch_template_roles(self, site):
            assert site == SITE
            return ("access", ["EMPLOYEE", "IOT"])

        async def close(self):
            return None

    monkeypatch.setattr("app.main.MistSession", FakeMist)
    custom = dict(employee)
    custom["port_color"] = "#112233"
    templated = client.post(
        "/api/admin/roles/mist-template",
        json={
            "mist_host": "api.mist.com",
            "mist_api_token": "",
            "mist_verify_tls": True,
            "ex_site_id": SITE,
            "mist_roles": [custom],
        },
    )
    assert templated.status_code == 200
    listed = templated.json()
    assert listed["ok"] is True
    assert listed["template"] == "access"
    assert listed["added"] == ["IOT"]
    assert listed["present"] == ["EMPLOYEE"]
    kept_employee = next(role for role in listed["roles"] if role["name"] == "EMPLOYEE")
    assert kept_employee["port_color"] == "#112233"
    iot = next(role for role in listed["roles"] if role["name"] == "IOT")
    assert iot["description"] == "Radius-group role on the Mist switch template."
    assert TOKEN not in templated.text
    assert JUNOS_PASSWORD not in templated.text
    assert seen["token"] == TOKEN

    after = client.get("/api/admin/config").json()
    assert [role["name"] for role in after["mist_roles"]] == ["EMPLOYEE", "IOT"]
    stored_employee = next(role for role in after["mist_roles"] if role["name"] == "EMPLOYEE")
    assert stored_employee["port_color"] == employee["port_color"]

    payload["junos_host"] = ""
    payload["junos_password"] = ""
    cleared = client.put("/api/admin/config", json=payload)
    assert cleared.status_code == 200
    assert cleared.json()["junos_host"] == ""
    assert cleared.json()["junos_password_set"] is True
    assert cleared.json()["poll"]["ex"]["source"] == "mist"
    assert get_settings(db_path)["junos_password"] == JUNOS_PASSWORD
    assert JUNOS_PASSWORD not in cleared.text


def test_ex_polling_choice_switches_without_clearing_the_other_source(client, db_path):
    config = client.get("/api/admin/config").json()
    assert config["ex_source_choice"] == "mist"
    payload = _base_payload(config)
    payload.update({
        "junos_host": "192.0.2.8",
        "junos_username": "lab",
        "junos_password": JUNOS_PASSWORD,
        "mist_api_token": TOKEN,
        "ex_site_id": SITE,
        "ex_switch_mac": EX_MAC,
        "ex_source_choice": "mist",
    })
    mist = client.put("/api/admin/config", json=payload)
    assert mist.status_code == 200
    assert mist.json()["ex_source_choice"] == "mist"
    assert mist.json()["poll"]["ex"]["source"] == "mist"
    assert mist.json()["poll"]["ex"]["choice"] == "mist"
    assert mist.json()["junos_host"] == "192.0.2.8"
    assert get_settings(db_path)["junos_password"] == JUNOS_PASSWORD

    payload["ex_source_choice"] = "junos"
    payload["junos_password"] = ""
    payload["mist_api_token"] = ""
    junos = client.put("/api/admin/config", json=payload)
    assert junos.status_code == 200
    body = junos.json()
    assert body["ex_source_choice"] == "junos"
    assert body["poll"]["ex"]["source"] == "junos"
    assert body["ex_site_id"] == SITE
    assert body["junos_host"] == "192.0.2.8"
    assert get_settings(db_path)["mist_api_token"] == TOKEN
    assert JUNOS_PASSWORD not in junos.text

    payload["ex_source_choice"] = "both"
    rejected = client.put("/api/admin/config", json=payload)
    assert rejected.status_code == 400
