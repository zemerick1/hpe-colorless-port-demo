"""Single-demo settings and role colors. One SQLite file, no user accounts."""

from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")
API_VERSION = re.compile(r"^v\d+\.\d+$")
SITE_ID = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

SEED_MIST_ROLES: tuple[tuple[str, str, str, str, int], ...] = (
    ("EMPLOYEE", "Employee", "Radius-group role on the Mist switch template.", "#FF8300", 1),
    ("IOT", "IoT", "Radius-group role on the Mist switch template.", "#99DAF8", 2),
)

SEED_ROLES: tuple[tuple[str, str, str, str, int, int, str], ...] = (
    ("Nothing_Connected", "Nothing Connected", "Nothing connected on this port.", "", 0, 1, "down"),
    ("Infrastructure", "Infrastructure", "Infrastructure device access.", "#888888", 1, 1, "up"),
    ("AccessPoint", "AccessPoint", "All traffic sent to the controller.", "#26F263", 2, 0, ""),
    ("Employee", "Employee", "Standard access to the corporate network.", "#FF8300", 3, 0, ""),
    ("IoT", "IoT", "Internet access only. Tunneled to the DMZ.", "#99DAF8", 4, 0, ""),
    (
        "SecurityCamera",
        "SecurityCamera",
        "Cloud video storage access only. Tunneled to the DMZ.",
        "#D5D654",
        5,
        0,
        "",
    ),
    ("Phone", "Phone", "PBX access only. Tunneled to the DMZ.", "#307AF2", 6, 0, ""),
    (
        "Multiple_Roles",
        "Multiple Roles",
        "Port has multiple clients connected with multiple roles.",
        "#E702F7",
        7,
        0,
        "multi",
    ),
    ("denyall", "denyall", "Access denied.", "#FF0000", 8, 0, ""),
)

SETTING_DEFAULTS = {
    "switch_host": "",
    "switch_port": 443,
    "switch_username": "",
    "switch_password": "",
    "api_version": "v10.16",
    "switch_verify_tls": 0,
    "vsf_member": 1,
    "clearpass_host": "",
    "clearpass_client_id": "",
    "clearpass_client_secret": "",
    "clearpass_verify_tls": 0,
    "mist_host": "api.mist.com",
    "mist_api_token": "",
    "mist_verify_tls": 1,
    "ex_site_id": "",
    "ex_switch_mac": "",
    "junos_host": "",
    "junos_port": 3443,
    "junos_username": "",
    "junos_password": "",
    "junos_verify_tls": 0,
    "ex_source_choice": "",
    "poll_interval_sec": 1.0,
    "screen_interval_sec": 0.5,
    "show_device_name_on_mac": 1,
    "visualize_unknown": 1,
    "hide_previous_popovers": 1,
}


def default_db_path() -> Path:
    env = os.environ.get("COLORLESS_DB")
    if env:
        return Path(env)
    return ROOT / "data" / "colorless.db"


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def init_db(path: Path) -> None:
    with connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                switch_host TEXT NOT NULL DEFAULT '',
                switch_port INTEGER NOT NULL DEFAULT 443,
                switch_username TEXT NOT NULL DEFAULT '',
                switch_password TEXT NOT NULL DEFAULT '',
                api_version TEXT NOT NULL DEFAULT 'v10.16',
                switch_verify_tls INTEGER NOT NULL DEFAULT 0,
                vsf_member INTEGER NOT NULL DEFAULT 1,
                clearpass_host TEXT NOT NULL DEFAULT '',
                clearpass_client_id TEXT NOT NULL DEFAULT '',
                clearpass_client_secret TEXT NOT NULL DEFAULT '',
                clearpass_verify_tls INTEGER NOT NULL DEFAULT 0,
                mist_host TEXT NOT NULL DEFAULT 'api.mist.com',
                mist_api_token TEXT NOT NULL DEFAULT '',
                mist_verify_tls INTEGER NOT NULL DEFAULT 1,
                ex_site_id TEXT NOT NULL DEFAULT '',
                ex_switch_mac TEXT NOT NULL DEFAULT '',
                poll_interval_sec REAL NOT NULL DEFAULT 1.0,
                screen_interval_sec REAL NOT NULL DEFAULT 0.5,
                show_device_name_on_mac INTEGER NOT NULL DEFAULT 1,
                visualize_unknown INTEGER NOT NULL DEFAULT 1,
                hide_previous_popovers INTEGER NOT NULL DEFAULT 1,
                port_up_role_id INTEGER,
                port_down_role_id INTEGER,
                multiple_roles_role_id INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                port_color TEXT NOT NULL DEFAULT '',
                legend_order INTEGER NOT NULL DEFAULT 0,
                no_popover INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        mist_roles_new = (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='mist_roles'"
            ).fetchone()
            is None
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mist_roles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                port_color TEXT NOT NULL DEFAULT '',
                legend_order INTEGER NOT NULL DEFAULT 0,
                no_popover INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        if mist_roles_new:
            for name, display, description, color, order in SEED_MIST_ROLES:
                conn.execute(
                    """
                    INSERT INTO mist_roles
                        (name, display_name, description, port_color, legend_order, no_popover)
                    VALUES (?, ?, ?, ?, ?, 0)
                    """,
                    (name, display, description, color, order),
                )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS port_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                display_name TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                port_color TEXT NOT NULL DEFAULT '',
                legend_order INTEGER NOT NULL DEFAULT 0,
                no_popover INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        _ensure_ex_columns(conn)
        _ensure_junos_columns(conn)
        row = conn.execute("SELECT id FROM settings WHERE id = 1").fetchone()
        if row is None:
            conn.execute("INSERT INTO settings (id) VALUES (1)")
        count = conn.execute("SELECT COUNT(*) AS n FROM roles").fetchone()["n"]
        if count == 0:
            for name, display, description, color, order, no_popover, _special in SEED_ROLES:
                conn.execute(
                    """
                    INSERT INTO roles (name, display_name, description, port_color, legend_order, no_popover)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (name, display, description, color, order, no_popover),
                )
            _assign_seed_specials(conn)


def _ensure_ex_columns(conn: sqlite3.Connection) -> None:
    have = {row["name"] for row in conn.execute("PRAGMA table_info(settings)")}
    if "ex_site_id" not in have:
        conn.execute("ALTER TABLE settings ADD COLUMN ex_site_id TEXT NOT NULL DEFAULT ''")
    if "ex_switch_mac" not in have:
        conn.execute("ALTER TABLE settings ADD COLUMN ex_switch_mac TEXT NOT NULL DEFAULT ''")


def _ensure_junos_columns(conn: sqlite3.Connection) -> None:
    have = {row["name"] for row in conn.execute("PRAGMA table_info(settings)")}
    adds = (
        ("junos_host", "TEXT NOT NULL DEFAULT ''"),
        ("junos_port", "INTEGER NOT NULL DEFAULT 3443"),
        ("junos_username", "TEXT NOT NULL DEFAULT ''"),
        ("junos_password", "TEXT NOT NULL DEFAULT ''"),
        ("junos_verify_tls", "INTEGER NOT NULL DEFAULT 0"),
        ("ex_source_choice", "TEXT NOT NULL DEFAULT ''"),
    )
    for name, declaration in adds:
        if name not in have:
            conn.execute(f"ALTER TABLE settings ADD COLUMN {name} {declaration}")


LOAD_PALETTE = (
    "#FF8300",
    "#99DAF8",
    "#26F263",
    "#D5D654",
    "#307AF2",
    "#E702F7",
    "#888888",
    "#C46B4A",
)


def merge_named_colors(existing: list[dict], names: list[str], description: str) -> dict:
    """Append names that are not already on the list. Keep colors already chosen."""
    kept: list[dict] = []
    by_fold: dict[str, dict] = {}
    for raw in existing:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        fold = name.casefold()
        if fold in by_fold:
            continue
        row = dict(raw)
        row["name"] = name
        kept.append(row)
        by_fold[fold] = row
    used = {str(row.get("port_color") or "").casefold() for row in kept if row.get("port_color")}
    orders = [int(row.get("legend_order") or 0) for row in kept]
    next_order = (max(orders) if orders else 0) + 1
    unused = [color for color in LOAD_PALETTE if color.casefold() not in used]
    added: list[str] = []
    present: list[str] = []
    fallback = 0
    for raw_name in names:
        name = str(raw_name or "").strip()
        if not name:
            continue
        fold = name.casefold()
        if fold in by_fold:
            present.append(str(by_fold[fold].get("name") or name))
            continue
        if unused:
            color = unused.pop(0)
        else:
            color = LOAD_PALETTE[fallback % len(LOAD_PALETTE)]
            fallback += 1
        used.add(color.casefold())
        row = {
            "id": None,
            "name": name,
            "display_name": "",
            "description": description,
            "port_color": color,
            "legend_order": next_order,
            "no_popover": False,
        }
        next_order += 1
        kept.append(row)
        by_fold[fold] = row
        added.append(name)
    return {"roles": kept, "added": added, "present": present}


def _assign_seed_specials(conn: sqlite3.Connection) -> None:
    ids = {row["name"]: row["id"] for row in conn.execute("SELECT id, name FROM roles")}
    conn.execute(
        """
        UPDATE settings
        SET port_up_role_id = ?, port_down_role_id = ?, multiple_roles_role_id = ?
        WHERE id = 1
        """,
        (ids["Infrastructure"], ids["Nothing_Connected"], ids["Multiple_Roles"]),
    )


def _bool(value: object) -> bool:
    return bool(int(value or 0))


def get_settings(path: Path) -> dict:
    init_db(path)
    with connect(path) as conn:
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
    data = dict(row)
    for key in (
        "switch_verify_tls",
        "clearpass_verify_tls",
        "mist_verify_tls",
        "junos_verify_tls",
        "show_device_name_on_mac",
        "visualize_unknown",
        "hide_previous_popovers",
    ):
        data[key] = _bool(data[key])
    data["poll_interval_sec"] = float(data["poll_interval_sec"])
    data["screen_interval_sec"] = float(data["screen_interval_sec"])
    return data


def get_roles(path: Path) -> list[dict]:
    init_db(path)
    with connect(path) as conn:
        rows = conn.execute(
            "SELECT * FROM roles ORDER BY legend_order ASC, id ASC"
        ).fetchall()
    return [_public_row(row) for row in rows]


def get_profiles(path: Path) -> list[dict]:
    return _named_rows(path, "port_profiles")


def get_mist_roles(path: Path) -> list[dict]:
    return _named_rows(path, "mist_roles")


def _named_rows(path: Path, table: str) -> list[dict]:
    if table not in {"port_profiles", "mist_roles"}:
        raise ValueError("Unknown color list")
    init_db(path)
    with connect(path) as conn:
        rows = conn.execute(
            f"SELECT * FROM {table} ORDER BY legend_order ASC, id ASC"
        ).fetchall()
    return [_public_row(row) for row in rows]


def _public_row(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["no_popover"] = _bool(item["no_popover"])
    return item


def public_config(path: Path) -> dict:
    settings = get_settings(path)
    roles = get_roles(path)
    specials = {
        settings.get("port_up_role_id"): "up",
        settings.get("port_down_role_id"): "down",
        settings.get("multiple_roles_role_id"): "multi",
    }
    public_roles = []
    for role in roles:
        public_roles.append(
            {
                "id": role["id"],
                "name": role["name"],
                "display_name": role["display_name"],
                "description": role["description"],
                "port_color": role["port_color"],
                "legend_order": role["legend_order"],
                "no_popover": role["no_popover"],
                "special": specials.get(role["id"], "") or "",
            }
        )
    return {
        "switch_host": settings["switch_host"],
        "switch_port": settings["switch_port"],
        "switch_username": settings["switch_username"],
        "switch_password_set": bool(settings["switch_password"]),
        "api_version": settings["api_version"],
        "switch_verify_tls": settings["switch_verify_tls"],
        "vsf_member": settings["vsf_member"],
        "clearpass_host": settings["clearpass_host"],
        "clearpass_client_id": settings["clearpass_client_id"],
        "clearpass_client_secret_set": bool(settings["clearpass_client_secret"]),
        "clearpass_verify_tls": settings["clearpass_verify_tls"],
        "mist_host": settings["mist_host"],
        "mist_api_token_set": bool(settings["mist_api_token"]),
        "mist_verify_tls": settings["mist_verify_tls"],
        "ex_site_id": settings.get("ex_site_id") or "",
        "ex_switch_mac": settings.get("ex_switch_mac") or "",
        "junos_host": settings.get("junos_host") or "",
        "junos_port": int(settings.get("junos_port") or 3443),
        "junos_username": settings.get("junos_username") or "",
        "junos_password_set": bool(settings.get("junos_password")),
        "junos_verify_tls": settings.get("junos_verify_tls"),
        "ex_source_choice": settings.get("ex_source_choice") or "",
        "poll_interval_sec": settings["poll_interval_sec"],
        "screen_interval_sec": settings["screen_interval_sec"],
        "show_device_name_on_mac": settings["show_device_name_on_mac"],
        "visualize_unknown": settings["visualize_unknown"],
        "hide_previous_popovers": settings["hide_previous_popovers"],
        "roles": public_roles,
        "profiles": get_profiles(path),
        "mist_roles": get_mist_roles(path),
    }


def _clean_text(value: object, field: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        raise ValueError(f"{field} is too long")
    return text


def _require_number(value: object, field: str, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if number < low or number > high:
        raise ValueError(f"{field} must be between {low:g} and {high:g}")
    return number


def save_config(path: Path, payload: dict) -> dict:
    current = get_settings(path)
    switch_host = _clean_text(payload.get("switch_host"), "Switch host", 255)
    switch_port = int(_require_number(payload.get("switch_port", 443), "HTTPS port", 1, 65535))
    switch_username = _clean_text(payload.get("switch_username"), "Switch username", 64)
    api_version = _clean_text(payload.get("api_version") or "v10.16", "API version", 16)
    if not API_VERSION.match(api_version):
        raise ValueError("API version looks like v10.16")
    vsf_member = int(_require_number(payload.get("vsf_member", 1), "VSF member", 1, 8))
    clearpass_host = _clean_text(payload.get("clearpass_host"), "ClearPass host", 255)
    clearpass_client_id = _clean_text(payload.get("clearpass_client_id"), "ClearPass client ID", 128)
    mist_host = _clean_text(payload.get("mist_host") or "api.mist.com", "Mist host", 255)
    poll_interval = _require_number(payload.get("poll_interval_sec", 1), "Poll interval", 0.5, 30)
    screen_interval = _require_number(
        payload.get("screen_interval_sec", 0.5), "Screen interval", 0.3, 5
    )

    switch_password = str(payload.get("switch_password") or "")
    if not switch_password:
        switch_password = current["switch_password"]
    clearpass_secret = str(payload.get("clearpass_client_secret") or "")
    if not clearpass_secret:
        clearpass_secret = current["clearpass_client_secret"]
    mist_token = str(payload.get("mist_api_token") or "")
    if not mist_token:
        mist_token = current["mist_api_token"]
    junos_host = _clean_text(payload.get("junos_host"), "Junos host", 255)
    junos_port = int(_require_number(payload.get("junos_port", 3443), "Junos port", 1, 65535))
    junos_username = _clean_text(payload.get("junos_username"), "Junos username", 64)
    junos_password = str(payload.get("junos_password") or "")
    if not junos_password:
        junos_password = current.get("junos_password") or ""

    if switch_host and not switch_username:
        raise ValueError("Switch username is required")
    if switch_host and not switch_password:
        raise ValueError("Switch password is required")
    if clearpass_host and not clearpass_client_id:
        raise ValueError("ClearPass client ID is required")
    if clearpass_host and not clearpass_secret:
        raise ValueError("ClearPass client secret is required")
    if mist_token and not mist_host:
        raise ValueError("Mist host is required")
    ex_site_id = _clean_text(payload.get("ex_site_id"), "EX site ID", 64)
    ex_switch_mac = _switch_mac(payload.get("ex_switch_mac"))
    if bool(ex_site_id) != bool(ex_switch_mac):
        raise ValueError("Enter both a Mist site ID and the EX switch MAC")
    if ex_site_id and not SITE_ID.match(ex_site_id):
        raise ValueError("EX site ID must be a UUID")
    if ex_site_id and not mist_token:
        raise ValueError("Mist API token is required for the EX switch")
    if junos_host and not junos_username:
        raise ValueError("Junos username is required")
    if junos_host and not junos_password:
        raise ValueError("Junos password is required")
    ex_source_choice = str(payload.get("ex_source_choice") or "").strip().casefold()
    if ex_source_choice not in {"", "mist", "junos"}:
        raise ValueError("EX polling must be Mist or Junos")

    roles_in = payload.get("roles")
    if not isinstance(roles_in, list) or not roles_in:
        raise ValueError("Add at least the three special roles")

    roles: list[dict] = []
    seen: set[str] = set()
    specials = {"up": 0, "down": 0, "multi": 0}
    for raw in roles_in:
        if not isinstance(raw, dict):
            raise ValueError("Role entry is invalid")
        name = _clean_text(raw.get("name"), "Role name", 64)
        if not name:
            raise ValueError("Role name is required")
        fold = name.casefold()
        if fold in seen:
            raise ValueError(f"Role name {name} is duplicated")
        seen.add(fold)
        color = _clean_text(raw.get("port_color"), "Role color", 7)
        if color and not HEX_COLOR.match(color):
            raise ValueError(f"Color for {name} must be #RRGGBB or empty")
        special = _clean_text(raw.get("special"), "Role special", 8)
        if special not in {"", "up", "down", "multi"}:
            raise ValueError("Role special must be port up, port down, or multiple")
        if special:
            specials[special] += 1
        legend = int(_require_number(raw.get("legend_order", 0), "Legend order", 0, 99))
        roles.append(
            {
                "id": raw.get("id"),
                "name": name,
                "display_name": _clean_text(raw.get("display_name"), "Role label", 64),
                "description": _clean_text(raw.get("description"), "Role description", 4000),
                "port_color": color,
                "legend_order": legend,
                "no_popover": 1 if raw.get("no_popover") else 0,
                "special": special,
            }
        )
    if specials["up"] != 1 or specials["down"] != 1 or specials["multi"] != 1:
        raise ValueError("Choose one Port up role, one Port down role, and one Multiple roles role")

    profiles_in = payload.get("profiles", None)
    profiles: list[dict] | None
    if profiles_in is None:
        profiles = None
    else:
        profiles = _clean_named(profiles_in, "Port profile")
    mist_roles_in = payload.get("mist_roles", None)
    mist_roles: list[dict] | None
    if mist_roles_in is None:
        mist_roles = None
    else:
        mist_roles = _clean_named(mist_roles_in, "Mist role")

    init_db(path)
    with connect(path) as conn:
        existing = {row["id"] for row in conn.execute("SELECT id FROM roles")}
        kept: list[int] = []
        for role in roles:
            role_id = role["id"]
            try:
                role_id = int(role_id) if role_id not in (None, "", "null") else None
            except (TypeError, ValueError):
                role_id = None
            fields = (
                role["name"],
                role["display_name"],
                role["description"],
                role["port_color"],
                role["legend_order"],
                role["no_popover"],
            )
            if role_id in existing:
                conn.execute(
                    """
                    UPDATE roles
                    SET name = ?, display_name = ?, description = ?, port_color = ?,
                        legend_order = ?, no_popover = ?
                    WHERE id = ?
                    """,
                    (*fields, role_id),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO roles (name, display_name, description, port_color, legend_order, no_popover)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    fields,
                )
                role_id = int(cursor.lastrowid)
            role["id"] = role_id
            kept.append(role_id)
        if kept:
            marks = ",".join("?" for _ in kept)
            conn.execute(f"DELETE FROM roles WHERE id NOT IN ({marks})", kept)
        if profiles is not None:
            _store_named(conn, "port_profiles", profiles)
        if mist_roles is not None:
            _store_named(conn, "mist_roles", mist_roles)
        up_id = next(role["id"] for role in roles if role["special"] == "up")
        down_id = next(role["id"] for role in roles if role["special"] == "down")
        multi_id = next(role["id"] for role in roles if role["special"] == "multi")
        conn.execute(
            """
            UPDATE settings SET
                switch_host = ?, switch_port = ?, switch_username = ?, switch_password = ?,
                api_version = ?, switch_verify_tls = ?, vsf_member = ?,
                clearpass_host = ?, clearpass_client_id = ?, clearpass_client_secret = ?,
                clearpass_verify_tls = ?,
                mist_host = ?, mist_api_token = ?, mist_verify_tls = ?,
                ex_site_id = ?, ex_switch_mac = ?, ex_source_choice = ?,
                junos_host = ?, junos_port = ?, junos_username = ?, junos_password = ?,
                junos_verify_tls = ?,
                poll_interval_sec = ?, screen_interval_sec = ?,
                show_device_name_on_mac = ?, visualize_unknown = ?, hide_previous_popovers = ?,
                port_up_role_id = ?, port_down_role_id = ?, multiple_roles_role_id = ?
            WHERE id = 1
            """,
            (
                switch_host,
                switch_port,
                switch_username,
                switch_password,
                api_version,
                1 if payload.get("switch_verify_tls") else 0,
                vsf_member,
                clearpass_host,
                clearpass_client_id,
                clearpass_secret,
                1 if payload.get("clearpass_verify_tls") else 0,
                mist_host,
                mist_token,
                1 if payload.get("mist_verify_tls", True) else 0,
                ex_site_id,
                ex_switch_mac,
                ex_source_choice,
                junos_host,
                junos_port,
                junos_username,
                junos_password,
                1 if payload.get("junos_verify_tls") else 0,
                poll_interval,
                screen_interval,
                1 if payload.get("show_device_name_on_mac", True) else 0,
                1 if payload.get("visualize_unknown") else 0,
                1 if payload.get("hide_previous_popovers", True) else 0,
                up_id,
                down_id,
                multi_id,
            ),
        )
    return public_config(path)


def _clean_named(raw_list: object, noun: str) -> list[dict]:
    if not isinstance(raw_list, list):
        raise ValueError(f"{noun} list is invalid")
    rows: list[dict] = []
    seen: set[str] = set()
    for raw in raw_list:
        if not isinstance(raw, dict):
            raise ValueError(f"{noun} entry is invalid")
        name = _clean_text(raw.get("name"), f"{noun} name", 128)
        if not name:
            raise ValueError(f"{noun} name is required")
        fold = name.casefold()
        if fold in seen:
            raise ValueError(f"{noun} {name} is duplicated")
        seen.add(fold)
        color = _clean_text(raw.get("port_color"), f"{noun} color", 7)
        if color and not HEX_COLOR.match(color):
            raise ValueError(f"Color for {name} must be #RRGGBB or empty")
        legend = int(_require_number(raw.get("legend_order", 0), "Legend order", 0, 99))
        rows.append(
            {
                "id": raw.get("id"),
                "name": name,
                "display_name": _clean_text(raw.get("display_name"), f"{noun} label", 128),
                "description": _clean_text(raw.get("description"), f"{noun} notes", 4000),
                "port_color": color,
                "legend_order": legend,
                "no_popover": 1 if raw.get("no_popover") else 0,
            }
        )
    return rows


def _store_named(conn: sqlite3.Connection, table: str, profiles: list[dict]) -> None:
    if table not in {"port_profiles", "mist_roles"}:
        raise ValueError("Unknown color list")
    existing = {row["id"] for row in conn.execute(f"SELECT id FROM {table}")}
    kept: list[int] = []
    for profile in profiles:
        profile_id = profile["id"]
        try:
            profile_id = int(profile_id) if profile_id not in (None, "", "null") else None
        except (TypeError, ValueError):
            profile_id = None
        fields = (
            profile["name"],
            profile["display_name"],
            profile["description"],
            profile["port_color"],
            profile["legend_order"],
            profile["no_popover"],
        )
        if profile_id in existing:
            conn.execute(
                f"""
                UPDATE {table}
                SET name = ?, display_name = ?, description = ?, port_color = ?,
                    legend_order = ?, no_popover = ?
                WHERE id = ?
                """,
                (*fields, profile_id),
            )
        else:
            cursor = conn.execute(
                f"""
                INSERT INTO {table}
                    (name, display_name, description, port_color, legend_order, no_popover)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                fields,
            )
            profile_id = int(cursor.lastrowid)
        profile["id"] = profile_id
        kept.append(profile_id)
    if kept:
        marks = ",".join("?" for _ in kept)
        conn.execute(f"DELETE FROM {table} WHERE id NOT IN ({marks})", kept)
    else:
        conn.execute(f"DELETE FROM {table}")


def _switch_mac(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if not re.fullmatch(r"[0-9a-fA-F]{12}|[0-9a-fA-F]{2}([:\-][0-9a-fA-F]{2}){5}", text):
        raise ValueError("EX switch MAC must be 12 hex digits")
    hexes = re.sub(r"[^0-9a-fA-F]", "", text).lower()
    return ":".join(hexes[i : i + 2] for i in range(0, 12, 2))


def resolve_secret(path: Path, column: str, incoming: str) -> str:
    text = str(incoming or "")
    if text:
        return text
    settings = get_settings(path)
    return str(settings.get(column) or "")
