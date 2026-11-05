"""EX polling follows the saved choice. With no choice saved, Junos wins when it is filled in."""

import asyncio
from types import SimpleNamespace

from app.poller import PollStatus, Poller, ex_source


def test_junos_wins_and_a_cleared_host_returns_to_mist():
    both = {
        "junos_host": "192.0.2.8",
        "junos_username": "lab",
        "junos_password": "secret",
        "ex_site_id": "site",
        "ex_switch_mac": "aa:bb:cc:dd:ee:ff",
        "mist_api_token": "token",
    }
    assert ex_source(both) == "junos"
    assert ex_source({**both, "junos_host": ""}) == "mist"
    assert ex_source({**both, "junos_host": "", "mist_api_token": ""}) == ""
    assert ex_source({**both, "ex_source_choice": "mist"}) == "mist"
    assert ex_source({**both, "ex_source_choice": "junos"}) == "junos"
    assert ex_source({**both, "ex_source_choice": "junos", "junos_host": ""}) == ""


def test_poller_does_not_call_mist_while_junos_is_configured():
    app = SimpleNamespace(state=SimpleNamespace(poll=PollStatus()))
    poller = Poller(app)
    calls = []

    async def poll_ex(settings):
        calls.append("mist")

    async def poll_junos(settings):
        calls.append("junos")

    poller.poll_ex = poll_ex
    poller.poll_junos = poll_junos
    settings = {
        "junos_host": "192.0.2.8",
        "junos_username": "lab",
        "junos_password": "secret",
        "ex_site_id": "site",
        "ex_switch_mac": "aa:bb:cc:dd:ee:ff",
        "mist_api_token": "token",
    }
    asyncio.run(poller.poll_active_ex(settings))
    settings = {**settings, "junos_host": ""}
    asyncio.run(poller.poll_active_ex(settings))
    settings = {**settings, "junos_host": "192.0.2.8", "ex_source_choice": "mist"}
    asyncio.run(poller.poll_active_ex(settings))
    assert calls == ["junos", "mist", "mist"]
