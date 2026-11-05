"""Mist dynamic_filter is a role. A Junos session filter is a firewall filter."""

from app.aoscx import RawClient, RawPort
from app.junos import Dot1xSession, JunosLink
from app.translate import mark_mist, ports_from_junos


def test_mist_dynamic_filter_stays_a_role_and_keeps_the_port_profile():
    ports = mark_mist([
        RawPort(0, "mge-0/0/0", "up", "", [
            RawClient(
                "b8:27:eb:15:2c:5e", "", "dot1x", "dot1x-only",
                "", "raspberrypi", "2", "Bridged", "",
                mist_role="EMPLOYEE",
            ),
        ]),
    ])
    client = ports[0].clients[0]
    assert client.mist_role == "EMPLOYEE"
    assert client.access_kind == "role"
    assert client.role == "dot1x-only"


def test_junos_filter_is_a_filter_and_does_not_set_a_port_profile():
    ports = ports_from_junos(
        [
            JunosLink("ge-0/0/0", True),
            JunosLink("xe-0/1/0", True),
            JunosLink("ge-0/0/2.0", False),
        ],
        [
            Dot1xSession("ge-0/0/0.0", "aabbccddeeff", "user", "EMPLOYEE", "20", "Authenticated"),
            Dot1xSession("ge-0/0/1", "001122334455", "other", "", "", "Authenticated"),
        ],
    )
    employee = ports[0].clients[0]
    assert ports[0].name == "ge-0/0/0"
    assert ports[0].status == "up"
    assert employee.mist_role == "EMPLOYEE"
    assert employee.access_kind == "filter"
    assert employee.role == ""
    assert employee.mac == "aa:bb:cc:dd:ee:ff"
    bare = ports[1].clients[0]
    assert bare.mist_role == ""
    assert bare.access_kind == "filter"
    assert ports[1].status == "up"
    assert ports[2].status == "down"
    assert ports[2].clients == []
    assert all(port.name != "xe-0/1/0" for port in ports)
