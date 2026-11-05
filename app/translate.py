"""Turn an EX source record into the faceplate access name.

Mist and Junos keep their own field names. This module is the only place that
decides the jack name is a Mist role or a Junos firewall filter.
"""

from __future__ import annotations

from app.aoscx import RawClient, RawPort
from app.junos import Dot1xSession, JunosLink
from app.mist import copper_index, display_mac

ACCESS_PORTS = 12


def physical_name(name: str) -> str:
    text = str(name or "").strip()
    if "." in text:
        text = text.split(".", 1)[0]
    return text


def mark_mist(ports: list[RawPort]) -> list[RawPort]:
    """A Mist dynamic_filter is a role. The port profile stays on the client."""
    for port in ports:
        for client in port.clients:
            client.mist_role = str(client.mist_role or "").strip()
            client.access_kind = "role"
    return ports


def ports_from_junos(links: list[JunosLink], sessions: list[Dot1xSession]) -> list[RawPort]:
    """Twelve copper jacks. The access name is the ethernet-switching filter.

    There is no Mist port profile on this path. An authenticated session with
    no filter is kept so the jack can show gray. A link with no session is dark.
    """
    ports = [RawPort(number=number, name=f"ge-0/0/{number}", status="down") for number in range(ACCESS_PORTS)]
    chosen: dict[int, JunosLink] = {}
    for link in links:
        name = physical_name(link.name)
        number = copper_index(name)
        if number is None:
            continue
        current = chosen.get(number)
        if current is None or _prefer_link(name, link.up, physical_name(current.name), current.up):
            chosen[number] = JunosLink(name=name, up=link.up)

    grouped: dict[int, list[RawClient]] = {number: [] for number in range(ACCESS_PORTS)}
    for session in sessions:
        name = physical_name(session.interface)
        number = copper_index(name)
        if number is None:
            continue
        grouped[number].append(
            RawClient(
                mac=display_mac(session.mac),
                username=session.username,
                auth_method="dot1x",
                role="",
                device_type="",
                device_name="",
                vlan=session.vlan,
                forwarding="Bridged",
                tunnel="",
                mist_role=session.filter_name.strip(),
                access_kind="filter",
            )
        )

    for port in ports:
        link = chosen.get(port.number)
        if link is not None:
            port.name = link.name or port.name
            port.status = "up" if link.up else "down"
        clients = grouped[port.number]
        if clients:
            port.status = "up"
            port.clients = clients
    return ports


def _prefer_link(new_name: str, new_up: bool, old_name: str, old_up: bool) -> bool:
    if new_up != old_up:
        return new_up
    return new_name.casefold().startswith("mge-") and not old_name.casefold().startswith("mge-")
