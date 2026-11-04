"""Turn switch clients into faceplate colors. One role, or the multiple-role color."""

from __future__ import annotations

import re

from app.aoscx import ACCESS_PORT_COUNT, RawClient, RawPort, empty_ports

MAC_METHODS = {"mac-auth", "port-security"}


def _norm(value: str) -> str:
    return re.sub(r"[ -]+", "_", value).casefold()


_COMPACT = {
    "accesspoint": "ap",
    "accesspt": "ap",
    "wirelessap": "ap",
    "securitycamera": "camera",
    "securitycam": "camera",
    "ipcamera": "camera",
    "ipphone": "phone",
    "voipphone": "phone",
}


def _compact(value: str) -> str:
    text = re.sub(r"[^a-z0-9]", "", value.casefold())
    if text.startswith("aruba"):
        text = text[5:]
    return _COMPACT.get(text, text)


def match_role(raw: str, roles: list[dict]) -> dict | None:
    name = (raw or "").strip()
    if name.startswith("*"):
        name = name[1:]
    if name.endswith("*"):
        name = name[:-1]
    if not name:
        return None
    candidates = [name]
    stripped = re.match(r"^(.*)-\d+$", name)
    if stripped and stripped.group(1):
        candidates.append(stripped.group(1))
    prefix = name[:-3] if name.endswith("...") else ""

    def consider(candidate: str) -> dict | None:
        folded = candidate.casefold()
        normalized = _norm(candidate)
        for role in roles:
            if role["name"] == candidate or role["name"].casefold() == folded:
                return role
        for role in roles:
            if _norm(role["name"]) == normalized:
                return role
            display = role.get("display_name") or ""
            if display and _norm(display) == normalized:
                return role
        return None

    for candidate in candidates:
        found = consider(candidate)
        if found is not None:
            return found
    if prefix:
        normalized = _norm(prefix)
        for role in roles:
            if _norm(role["name"]).startswith(normalized):
                return role
    for candidate in candidates:
        compact = _compact(candidate)
        if len(compact) < 2:
            continue
        for role in roles:
            labels = [role["name"]]
            if role.get("display_name"):
                labels.append(role["display_name"])
            if any(_compact(label) == compact for label in labels):
                return role
    return None


def auth_label(method: str) -> str:
    folded = (method or "").casefold()
    if folded == "device-profile":
        return "Device profile"
    if folded in MAC_METHODS:
        return "MAC-based"
    if folded in {"dot1x", "802.1x", "8021x"}:
        return "802.1X"
    return method or ""


def _role_label(role: dict) -> str:
    return role.get("display_name") or role["name"]


def match_profile(raw: str, profiles: list[dict]) -> dict | None:
    """Match a Mist port profile. Exact name wins, then spacing and case."""
    name = (raw or "").strip()
    if not name:
        return None
    folded = name.casefold()
    normalized = _norm(name)
    for profile in profiles:
        if profile["name"] == name or profile["name"].casefold() == folded:
            return profile
    for profile in profiles:
        if _norm(profile["name"]) == normalized:
            return profile
        display = profile.get("display_name") or ""
        if display and (display.casefold() == folded or _norm(display) == normalized):
            return profile
    return None


def build_snapshot(
    raw_ports: list[RawPort] | None,
    settings: dict,
    roles: list[dict],
    poll: dict,
    platform: str = "cx",
    profiles: list[dict] | None = None,
    mist_roles: list[dict] | None = None,
) -> dict:
    member = int(settings.get("vsf_member") or 1)
    by_number = {port.number: port for port in raw_ports or []}
    if platform == "ex":
        base_ports = [RawPort(number=number, name=f"ge-0/0/{number}", status="down") for number in range(12)]
    else:
        base_ports = empty_ports(member)
    ports_in = []
    for blank in base_ports:
        ports_in.append(by_number.get(blank.number, blank))

    by_id = {role["id"]: role for role in roles}
    up = by_id.get(settings.get("port_up_role_id"))
    down = by_id.get(settings.get("port_down_role_id"))
    multi = by_id.get(settings.get("multiple_roles_role_id"))
    up_color = (up or {}).get("port_color") or ""
    multi_color = (multi or {}).get("port_color") or "#E702F7"
    show_device = bool(settings.get("show_device_name_on_mac", True))
    ex = platform == "ex"
    profile_list = profiles or []
    mist_role_list = mist_roles or []

    painted = []
    for port in ports_in:
        if ex:
            visible = _visible_profiles(port.clients, profile_list, mist_role_list)
            color, port_role, no_popover = _port_color(port, visible, None, None, "")
        else:
            visible = _visible_clients(port.clients, roles, down, show_device, up_color)
            color, port_role, no_popover = _port_color(
                port, visible, down, multi, multi_color
            )
        clients_quiet = bool(visible) and all(client.get("no_popover") for client in visible)
        painted.append(
            {
                "number": port.number,
                "name": port.name,
                "status": port.status,
                "color": color,
                "lldp_neighbor": port.lldp_neighbor or "",
                "num_clients": len(visible),
                "auto_popover": (
                    bool(color)
                    and port.status == "up"
                    and not (len(visible) == 0 and no_popover)
                    and not clients_quiet
                ),
                "no_popover": (no_popover and len(visible) == 0) or clients_quiet,
                "role_label": _role_label(port_role) if port_role else "",
                "role_description": (port_role or {}).get("description") or "",
                "clients": visible,
            }
        )

    if ex:
        legend = _legend_rows(mist_role_list, "role")
        _add_unlisted(
            legend,
            mist_role_list,
            painted,
            name_key="mist_role_name",
            label_key="mist_role_label",
            color_key="mist_role_color",
            kind="role",
        )
        profile_legend = _legend_rows(profile_list, "profile")
        _add_unlisted(
            profile_legend,
            profile_list,
            painted,
            name_key="profile_name",
            label_key="profile_label",
            color_key="profile_color",
            kind="profile",
        )
        legend.extend(profile_legend)
    else:
        legend = _legend_rows(roles, "")
    return {
        "platform": platform,
        "screen_interval_sec": float(settings.get("screen_interval_sec") or 0.5),
        "hide_previous_popovers": bool(settings.get("hide_previous_popovers", True)),
        "poll": poll,
        "legend": legend,
        "ports": painted,
        "access_port_count": ACCESS_PORT_COUNT,
    }


def _visible_clients(
    clients: list[RawClient],
    roles: list[dict],
    down: dict | None,
    show_device: bool,
    up_color: str,
) -> list[dict]:
    visible = []
    for client in clients:
        role = match_role(client.role, roles)
        # Port down is "nothing connected", not a session. A client on the
        # port-up role is a real session and must stay visible; the port-up
        # color is only the fill for a link with no clients.
        if role is not None and down is not None and role["id"] == down["id"]:
            continue
        if role is None:
            label = client.role.lstrip("*") or "Unknown"
            description = "This role is not on the admin role list yet."
            color = up_color or "#888888"
            no_popover = False
            role_name = client.role
        else:
            label = _role_label(role)
            description = role.get("description") or ""
            color = role.get("port_color") or up_color or "#888888"
            no_popover = bool(role.get("no_popover"))
            role_name = role["name"]
        method = auth_label(client.auth_method)
        if method == "Device profile" or (show_device and method == "MAC-based"):
            title = "Device name"
            username = client.device_name or client.username or client.mac
        else:
            title = "Username"
            username = client.username or ""
        visible.append(
            {
                "mac": client.mac,
                "username": username,
                "username_title": title,
                "auth_method": method,
                "kind": "role",
                "role_name": role_name,
                "role_label": label,
                "role_description": description,
                "color": color,
                "device_type": client.device_type,
                "device_category": client.device_category,
                "device_family": client.device_family,
                "ip_address": client.ip_address,
                "vlan": client.vlan,
                "forwarding": client.forwarding,
                "tunnel": client.tunnel,
                "detail": True,
                "no_popover": no_popover,
            }
        )
    return visible


def _legend_rows(items: list[dict], kind: str) -> list[dict]:
    rows = []
    for item in sorted(items, key=lambda item: (item.get("legend_order") or 0, item["id"])):
        if (item.get("legend_order") or 0) <= 0:
            continue
        row = {
            "id": item["id"],
            "label": _role_label(item),
            "color": item.get("port_color") or "",
        }
        if kind:
            row["kind"] = kind
        rows.append(row)
    return rows


def _known_names(items: list[dict]) -> set[str]:
    known = set()
    for item in items:
        known.add((item.get("name") or "").casefold())
        display = item.get("display_name") or ""
        if display:
            known.add(display.casefold())
    return known


def _add_unlisted(
    legend: list[dict],
    items: list[dict],
    ports: list[dict],
    name_key: str,
    label_key: str,
    color_key: str,
    kind: str,
) -> None:
    """Show a gray chip for a profile or role the admin list does not have yet."""
    known = _known_names(items)
    seen = {str(row.get("label") or "").casefold() for row in legend}
    seen.update(known)
    for port in ports:
        for client in port["clients"]:
            key = str(client.get(name_key) or "").strip()
            fold = key.casefold()
            if not key or fold in seen or fold == "unknown":
                continue
            color = client.get(color_key) or "#888888"
            if not color:
                continue
            seen.add(fold)
            legend.append(
                {
                    "id": "seen:" + kind + ":" + fold,
                    "label": client.get(label_key) or key,
                    "color": color,
                    "kind": kind,
                }
            )


def _named_paint(raw: str, items: list[dict], missing: str) -> dict:
    matched = match_profile(raw, items) if raw else None
    if matched is None:
        return {
            "name": raw,
            "label": raw,
            "description": missing if raw else "",
            "color": "#888888" if raw else "",
            "no_popover": False,
            "known": False,
        }
    return {
        "name": matched["name"],
        "label": _role_label(matched),
        "description": matched.get("description") or "",
        "color": matched.get("port_color") or "",
        "no_popover": bool(matched.get("no_popover")),
        "known": True,
    }


def _visible_profiles(
    clients: list[RawClient],
    profiles: list[dict],
    mist_roles: list[dict],
) -> list[dict]:
    """Color an EX client from its Mist role, then from the applied port profile."""
    visible = []
    for client in clients:
        profile = _named_paint(
            client.role,
            profiles,
            "This port profile is not on the admin list yet.",
        )
        role = _named_paint(
            client.mist_role,
            mist_roles,
            "This Mist role is not on the admin list yet.",
        )
        if client.mist_role and (role["color"] or not role["known"]):
            color = role["color"] or "#888888"
            no_popover = role["no_popover"]
            identity = role["name"]
        else:
            color = profile["color"]
            no_popover = profile["no_popover"]
            identity = profile["name"] or "Unknown"
        method = auth_label(client.auth_method)
        visible.append(
            {
                "mac": client.mac,
                "username": client.device_name or client.username or client.mac,
                "username_title": "Device name",
                "auth_method": method,
                "kind": "profile",
                "role_name": identity or "Unknown",
                "role_label": profile["label"] or "Unknown",
                "role_description": profile["description"],
                "profile_name": profile["name"],
                "profile_label": profile["label"],
                "profile_color": profile["color"] or ("#888888" if profile["name"] and not profile["known"] else ""),
                "mist_role_name": role["name"],
                "mist_role_label": role["label"],
                "mist_role_description": role["description"],
                "mist_role_color": role["color"] or ("#888888" if role["name"] and not role["known"] else ""),
                "color": color,
                "device_type": client.device_type,
                "device_category": client.device_category,
                "device_family": client.device_family,
                "ip_address": client.ip_address,
                "vlan": client.vlan,
                "forwarding": client.forwarding,
                "tunnel": client.tunnel,
                "detail": True,
                "no_popover": no_popover,
            }
        )
    return visible


def _port_color(
    port: RawPort,
    visible: list[dict],
    down: dict | None,
    multi: dict | None,
    multi_color: str,
) -> tuple[str, dict | None, bool]:
    if port.status != "up":
        return "", down, bool(down and down.get("no_popover"))
    # A link with no authenticated client stays dark. The Port up role color
    # is not a lamp for "something is plugged in".
    if not visible:
        return "", None, True
    keys = []
    for client in visible:
        keys.append(client["role_name"] or client["mac"])
    if len(set(keys)) > 1 and multi is not None:
        return multi_color, multi, bool(multi.get("no_popover"))
    return visible[0]["color"], None, False
