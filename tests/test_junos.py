"""Junos REST parsing. The password stays out of the URL and the error text."""

import asyncio
import json

import httpx

from app.junos import (
    JunosError,
    JunosSession,
    JunosTarget,
    filters_from_config,
    filters_from_firewall,
    links_from_interfaces,
    sessions_from_dot1x,
)


def test_ethernet_switching_filters_keep_both_json_shapes_and_ignore_inet():
    payload = {
        "configuration": {
            "firewall": {
                "family": {
                    "ethernet-switching": {
                        "filter": [
                            {"name": "EMPLOYEE", "term": [{"name": "01"}]},
                            {"name": {"data": "IOT"}},
                        ]
                    },
                    "inet": {"filter": [{"name": "PROTECT"}]},
                }
            }
        }
    }
    wrapped = {
        "configuration": [
            {
                "firewall": [
                    {
                        "family": [
                            {
                                "ethernet-switching": [
                                    {"filter": [{"name": [{"data": "EMPLOYEE"}]}, {"name": [{"data": "IOT"}]}]}
                                ],
                                "inet": [{"filter": [{"name": [{"data": "PROTECT"}]}]}],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    assert filters_from_config(payload) == ["EMPLOYEE", "IOT"]
    assert filters_from_config(wrapped) == ["EMPLOYEE", "IOT"]


def test_dot1x_detail_reads_the_session_filter_and_skips_other_states():
    payload = {
        "dot1x-interface-information": [
            {
                "interface": [
                    {
                        "interface-name": [{"data": "ge-0/0/0.0"}],
                        "supplicant-list": [
                            {
                                "supplicant": [
                                    {
                                        "supplicant-mac-address": [{"data": "aa:bb:cc:dd:ee:ff"}],
                                        "supplicant-name": [{"data": "user"}],
                                        "supplicant-state": [{"data": "Authenticated"}],
                                        "filter-name": [{"data": "EMPLOYEE"}],
                                        "vlan": [{"data": "20"}],
                                    },
                                    {
                                        "supplicant-state": "Connecting",
                                        "filter-name": "IGNORE",
                                    },
                                ]
                            }
                        ],
                    },
                    {
                        "interface-name": "ge-0/0/3.0",
                        "supplicant": {
                            "supplicant-mac-address": "00:11:22:33:44:55",
                            "supplicant-state": "Authenticated",
                            "filter": {"name": {"data": "IOT"}},
                        },
                    },
                ]
            }
        ]
    }
    sessions = sessions_from_dot1x(payload)
    assert [(item.interface, item.filter_name) for item in sessions] == [
        ("ge-0/0/0.0", "EMPLOYEE"),
        ("ge-0/0/3.0", "IOT"),
    ]
    links = links_from_interfaces({
        "interface-information": {
            "physical-interface": [
                {"name": [{"data": "ge-0/0/0"}], "oper-status": [{"data": "up"}]},
                {"name": "xe-0/1/0", "oper-status": "up"},
            ]
        }
    })
    assert [(link.name, link.up) for link in links] == [("ge-0/0/0", True), ("xe-0/1/0", True)]


def test_rejected_login_does_not_echo_the_password():
    password = "junos-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rpc"
        assert password not in str(request.url)
        assert b"get-software-information" in request.content
        return httpx.Response(401, json={"rpc-error": {"message": password}})

    async def run():
        session = JunosSession(
            JunosTarget("192.0.2.8", 3443, "lab", password, False),
            transport=httpx.MockTransport(handler),
        )
        try:
            await session.read_access()
        finally:
            await session.close()

    try:
        asyncio.run(run())
    except Exception as exc:
        assert password not in str(exc)
        assert "401" in str(exc)
    else:
        raise AssertionError("login failure was not raised")


def _multipart(payload: dict, boundary: str = "bound") -> httpx.Response:
    body = (
        f"--{boundary}\n"
        "Content-Type: application/json; charset=utf-8\n"
        "\n"
        + json.dumps(payload)
        + f"\n--{boundary}--\n"
    )
    return httpx.Response(
        200,
        content=body.encode(),
        headers={"Content-Type": f"multipart/mixed; boundary={boundary}"},
    )


def test_multipart_json_is_read_as_the_rpc_payload():
    software = {
        "multi-routing-engine-results": [
            {
                "multi-routing-engine-item": [
                    {
                        "software-information": [
                            {
                                "host-name": [{"data": "Office4000-12MP"}],
                                "junos-version": [{"data": "24.4R2.25"}],
                            }
                        ]
                    }
                ]
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if b"get-software-information" in request.content:
            return _multipart(software)
        if b"get-interface-information" in request.content:
            return _multipart({
                "interface-information": [{
                    "physical-interface": [
                        {"name": [{"data": "mge-0/0/0"}], "oper-status": [{"data": "up"}]},
                    ]
                }]
            })
        return _multipart({
            "dot1x-interface-information": [{
                "interface": [{
                    "interface-name": [{"data": "mge-0/0/0.0"}],
                    "supplicant": [{
                        "supplicant-mac-address": [{"data": "aa:bb:cc:dd:ee:ff"}],
                        "supplicant-name": [{"data": "camera"}],
                        "supplicant-state": [{"data": "Authenticated"}],
                        "filter-name": [{"data": "IOT"}],
                        "vlan": [{"data": "IOT"}],
                    }],
                }]
            }]
        })

    async def run():
        session = JunosSession(
            JunosTarget("192.0.2.8", 3443, "lab", "secret", False),
            transport=httpx.MockTransport(handler),
        )
        try:
            return await session.read_access()
        finally:
            await session.close()

    hostname, version, links, sessions = asyncio.run(run())
    assert (hostname, version) == ("Office4000-12MP", "24.4R2.25")
    assert [(link.name, link.up) for link in links] == [("mge-0/0/0", True)]
    assert [(item.interface, item.filter_name) for item in sessions] == [("mge-0/0/0.0", "IOT")]


def test_installed_filters_fill_in_when_the_configuration_is_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        if b"get-configuration" in request.content:
            return httpx.Response(200, json={"configuration": {}})
        assert b"get-firewall-information" in request.content
        return httpx.Response(200, json={
            "firewall-information": [{
                "filter-information": [
                    {"filter-name": [{"data": "EMPLOYEE"}]},
                    {"filter-name": [{"data": "__default_arp_policer__"}]},
                    {"filter-name": [{"data": "IOT"}]},
                ]
            }]
        })

    async def run():
        session = JunosSession(
            JunosTarget("192.0.2.8", 3443, "lab", "secret", False),
            transport=httpx.MockTransport(handler),
        )
        try:
            return await session.filter_names()
        finally:
            await session.close()

    assert asyncio.run(run()) == ["EMPLOYEE", "IOT"]
    assert filters_from_firewall({
        "filter-information": [{"filter-name": "EMPLOYEE"}, {"filter-name": "employee"}]
    }) == ["EMPLOYEE"]


def test_xml_error_inside_multipart_is_the_junos_message():
    boundary = "bound"
    body = (
        f"--{boundary}\n"
        "Content-Type: application/xml\n"
        "\n"
        "<xnm:error><message>missing mandatory argument: filtername</message></xnm:error>\n"
        f"--{boundary}--\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body.encode(),
            headers={"Content-Type": f"multipart/mixed; boundary={boundary}"},
        )

    async def run():
        session = JunosSession(
            JunosTarget("192.0.2.8", 3443, "lab", "secret", False),
            transport=httpx.MockTransport(handler),
        )
        try:
            await session.read_access()
        finally:
            await session.close()

    try:
        asyncio.run(run())
    except JunosError as exc:
        assert str(exc) == "missing mandatory argument: filtername"
    else:
        raise AssertionError("xml error was not raised")
