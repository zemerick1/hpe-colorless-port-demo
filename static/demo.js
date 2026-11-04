const HINTS = {
  cx: "Ports 1–12 light from the access role. Click a lit port to pin its details. The 1G, SFP, and management ports on the right stay dark.",
  ex: "Ports ge-0/0/0–11 light from the Mist port profile applied to a connected client. Click a lit port to pin its details. SFP, management, and console stay dark.",
};

const state = {
  snap: null,
  first: true,
  platform: "cx",
  ticket: 0,
  signatures: new Map(),
  pinned: new Set(),
  open: new Set(),
  popovers: new Map(),
};

document.querySelectorAll(".faceplate").forEach((plate) => {
  plate.addEventListener("click", (event) => {
    const group = event.target.closest(".port");
    if (!group || plate.dataset.platform !== state.platform) return;
    onPortClick(Number(group.dataset.port));
  });
});

function activePlate() {
  return document.querySelector('.faceplate[data-platform="' + state.platform + '"]');
}

function portButton(number) {
  const plate = activePlate();
  return plate ? plate.querySelector('.port[data-port="' + number + '"]') : null;
}

function signature(port) {
  return JSON.stringify({
    status: port.status,
    color: port.color,
    lldp: port.lldp_neighbor,
    clients: port.clients,
  });
}

function apply(snap) {
  state.snap = snap;
  const first = state.first;
  state.first = false;
  const changed = [];
  for (const port of snap.ports) {
    const sig = signature(port);
    if (state.signatures.get(port.number) !== sig) {
      if (!first && state.signatures.has(port.number)) changed.push(port.number);
      state.signatures.set(port.number, sig);
    }
    paint(port);
    if (port.status !== "up" || !port.color) {
      state.pinned.delete(port.number);
      closePopover(port.number);
    }
  }
  if (first) {
    const autos = snap.ports.filter((port) => port.auto_popover);
    if (autos.length) showPopover(autos[autos.length - 1].number);
  } else if (changed.length && snap.hide_previous_popovers) {
    const autos = changed
      .map((number) => snap.ports.find((port) => port.number === number))
      .filter((port) => port && port.auto_popover && !heldClosed(port.number));
    if (autos.length) {
      const target = autos[autos.length - 1].number;
      for (const number of [...state.open]) {
        if (number !== target && !state.pinned.has(number)) closePopover(number);
      }
      showPopover(target);
    }
  } else if (changed.length) {
    for (const number of changed) {
      const port = snap.ports.find((item) => item.number === number);
      if (port && port.auto_popover && !heldClosed(number)) showPopover(number);
    }
  }
  for (const number of [...state.open]) showPopover(number);
  renderLegend(snap.legend || []);
  renderStatus(snap);
}

function heldClosed(number) {
  return state.pinned.has(number) && !state.open.has(number);
}

function paint(port) {
  const group = portButton(port.number);
  if (!group) return;
  const lit = Boolean(port.color) && port.status === "up";
  group.classList.toggle("is-lit", lit);
  group.classList.toggle("pinned", state.pinned.has(port.number) && state.open.has(port.number));
  if (lit) group.style.setProperty("--lamp", port.color);
  else group.style.removeProperty("--lamp");
}

function onPortClick(number) {
  const port = state.snap && state.snap.ports.find((item) => item.number === number);
  if (!port || !port.color) return;
  state.pinned.add(number);
  if (state.open.has(number)) closePopover(number);
  else showPopover(number);
  paint(port);
}

function showPopover(number) {
  const port = state.snap.ports.find((item) => item.number === number);
  const anchor = portButton(number);
  if (!port || !anchor || !port.color) return;
  let pop = state.popovers.get(number);
  if (!pop) {
    pop = document.createElement("div");
    pop.className = "popover";
    pop.addEventListener("click", (event) => event.stopPropagation());
    document.body.append(pop);
    state.popovers.set(number, pop);
  }
  pop.replaceChildren();
  const title = document.createElement("h3");
  title.textContent = state.platform === "ex" ? "Port " + (port.name || number) : "Switch port " + number;
  pop.append(title);
  if (state.pinned.has(number)) {
    const note = document.createElement("p");
    note.className = "pin-note";
    note.textContent = "Pinned. Click the port again to close it.";
    pop.append(note);
  }
  const lldp = document.createElement("p");
  lldp.append(strong("LLDP neighbor: "), document.createTextNode(port.lldp_neighbor || "N/A"));
  pop.append(lldp);
  if (port.num_clients > 0) {
    appendClients(pop, port);
  } else {
    const line = document.createElement("p");
    line.textContent = "Link is up. No authenticated client.";
    pop.append(line);
    if (port.role_label) pop.append(row("Link-up color", port.role_label));
  }
  state.open.add(number);
  pop.hidden = false;
  placePopover(pop, anchor, anchor.dataset.row === "top" ? "top" : "bottom");
  paint(port);
}

function appendClients(pop, port) {
  const clients = port.clients;
  let active = clients.length - 1;
  const panes = [];
  if (clients.length > 1) {
    const tabs = document.createElement("div");
    tabs.className = "tabs";
    clients.forEach((client, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = client.username || client.mac || "Client " + (index + 1);
      const color = client.color || "#ddd";
      button.style.background = color;
      button.style.color = luminance(color) < 140 ? "#fff" : "#1a1e24";
      if (index === active) button.classList.add("active");
      button.addEventListener("click", () => {
        active = index;
        tabs.querySelectorAll("button").forEach((item, itemIndex) => {
          item.classList.toggle("active", itemIndex === index);
        });
        panes.forEach((pane, paneIndex) => {
          pane.hidden = paneIndex !== index;
        });
      });
      tabs.append(button);
    });
    pop.append(tabs);
  }
  clients.forEach((client, index) => {
    const pane = document.createElement("div");
    pane.hidden = index !== active;
    fillClient(pane, client);
    panes.push(pane);
    pop.append(pane);
  });
}

function fillClient(pane, client) {
  if (!client.detail) {
    pane.append(row("Description", client.role_description || "—"));
    return;
  }
  const profile = client.kind === "profile";
  pane.append(row("Auth method", client.auth_method || "—"));
  if (profile) {
    pane.append(row("Port profile", client.role_label || "—"));
    pane.append(row("Role", client.mist_role_label || "—"));
  } else {
    pane.append(row("Role", client.role_label || "—"));
  }
  pane.append(row(client.username_title || "Username", client.username || "—"));
  pane.append(row("MAC", client.mac || "—"));
  if (client.ip_address) pane.append(row("IP address", client.ip_address));
  pane.append(row("Device type", client.device_type || "—"));
  if (client.device_category) pane.append(row("Category", client.device_category));
  if (client.device_family) pane.append(row("OS family", client.device_family));
  pane.append(row("VLAN", client.vlan || "—"));
  pane.append(row("Forwarding", client.forwarding || "—"));
  if (client.forwarding === "Tunneled" && client.tunnel) pane.append(row("Tunnel", client.tunnel));
  if (profile) {
    if (client.role_description) pane.append(row("Profile notes", client.role_description));
    if (client.mist_role_description) pane.append(row("Role notes", client.mist_role_description));
  } else {
    pane.append(row("Permissions", client.role_description || "—"));
  }
}

function row(label, value) {
  const line = document.createElement("p");
  line.append(strong(label + ": "), document.createTextNode(value));
  return line;
}

function strong(text) {
  const node = document.createElement("strong");
  node.textContent = text;
  return node;
}

function closePopover(number) {
  const pop = state.popovers.get(number);
  if (pop) pop.hidden = true;
  state.open.delete(number);
  const port = state.snap && state.snap.ports.find((item) => item.number === number);
  if (port) paint(port);
}

function placePopover(pop, anchor, prefer) {
  pop.style.left = "0px";
  pop.style.top = "0px";
  const rect = anchor.getBoundingClientRect();
  const width = pop.offsetWidth;
  const height = pop.offsetHeight;
  let left = rect.left + rect.width / 2 - width / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - width - 8));
  let top = prefer === "top" ? rect.top - height - 12 : rect.bottom + 12;
  if (top < 8) top = rect.bottom + 12;
  if (top + height > window.innerHeight - 8) top = Math.max(8, rect.top - height - 12);
  pop.style.left = left + "px";
  pop.style.top = top + "px";
}

function legendChip(item) {
  const row = document.createElement("div");
  row.className = "legend-item";
  const swatch = document.createElement("span");
  swatch.className = "swatch" + (item.color ? " on" : "");
  if (item.color) swatch.style.setProperty("--swatch", item.color);
  const label = document.createElement("span");
  label.textContent = item.label;
  row.append(swatch, label);
  return row;
}

function legendGroup(title, items) {
  const group = document.createElement("div");
  group.className = "legend-group";
  const heading = document.createElement("p");
  heading.className = "legend-label";
  heading.textContent = title;
  const chips = document.createElement("div");
  chips.className = "legend-chips";
  for (const item of items) chips.append(legendChip(item));
  group.append(heading, chips);
  return group;
}

function renderLegend(items) {
  const root = document.getElementById("legend");
  root.replaceChildren();
  const grouped = state.platform === "ex";
  root.classList.toggle("grouped", grouped);
  if (!grouped) {
    for (const item of items) root.append(legendChip(item));
    return;
  }
  root.append(legendGroup("Roles", items.filter((item) => item.kind === "role")));
  root.append(legendGroup("Port profiles", items.filter((item) => item.kind === "profile")));
}

function renderStatus(snap) {
  const poll = snap.poll || {};
  const dot = document.getElementById("status-dot");
  const text = document.getElementById("status-text");
  const banner = document.getElementById("banner");
  const notes = [];
  dot.className = "dot";
  if (!poll.configured) {
    dot.classList.add("idle");
    text.textContent = "No switch configured";
    if ((snap.platform || state.platform) === "ex") {
      notes.push("Open Admin, save a Mist API token, and enter the EX site and switch MAC. Junos is not contacted.");
    } else {
      notes.push("Open Admin and enter the AOS-CX switch. Username and password are exchanged for a session token.");
    }
  } else if (poll.error) {
    dot.classList.add("bad");
    text.textContent = poll.hostname || "Switch unreachable";
    notes.push(poll.error);
  } else if (!poll.polled_at) {
    dot.classList.add("idle");
    text.textContent = "Reading the switch…";
  } else {
    dot.classList.add("ok");
    const ver = poll.software_version ? " · " + poll.software_version : "";
    text.textContent = (poll.hostname || "Switch") + ver + " · " + timeAgo(poll.polled_at);
  }
  if (poll.clearpass_configured && poll.clearpass_error) notes.push("ClearPass: " + poll.clearpass_error);
  banner.hidden = notes.length === 0;
  banner.textContent = notes.join(" ");
}

function timeAgo(iso) {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "just now";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 2) return "just now";
  if (seconds < 60) return seconds + "s ago";
  return Math.round(seconds / 60) + "m ago";
}

function luminance(hex) {
  const match = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex || "");
  if (!match) return 200;
  const red = parseInt(match[1], 16);
  const green = parseInt(match[2], 16);
  const blue = parseInt(match[3], 16);
  return red * 0.2126 + green * 0.7152 + blue * 0.0722;
}

window.addEventListener("resize", () => {
  for (const number of state.open) {
    const pop = state.popovers.get(number);
    const anchor = portButton(number);
    if (pop && anchor) placePopover(pop, anchor, anchor.dataset.row === "top" ? "top" : "bottom");
  }
});

function showPlatform(platform) {
  state.platform = platform;
  document.querySelectorAll(".faceplate").forEach((plate) => {
    const active = plate.dataset.platform === platform;
    plate.classList.toggle("is-active", active);
    if (!active) {
      plate.querySelectorAll(".port").forEach((port) => {
        port.classList.remove("is-lit", "pinned");
        port.style.removeProperty("--lamp");
      });
    }
  });
  const cx = document.getElementById("platform-cx");
  const ex = document.getElementById("platform-ex");
  cx.setAttribute("aria-pressed", platform === "cx" ? "true" : "false");
  ex.setAttribute("aria-pressed", platform === "ex" ? "true" : "false");
  document.getElementById("platform-label").textContent = platform === "ex" ? "EX4000 · Mist" : "AOS-CX 6200F";
  document.getElementById("legend-title").textContent = platform === "ex" ? "EX colors" : "Role colors";
  document.getElementById("legend-hint").textContent = HINTS[platform];
  try {
    localStorage.setItem("colorless-platform", platform);
  } catch (err) {
    /* The toggle still works for this page view. */
  }
}

function choosePlatform(platform) {
  if (platform !== "cx" && platform !== "ex") platform = "cx";
  if (state.platform === platform && document.querySelector(".faceplate.is-active")) {
    showPlatform(platform);
    return;
  }
  for (const number of [...state.open]) closePopover(number);
  state.pinned.clear();
  state.open.clear();
  state.signatures.clear();
  state.first = true;
  state.snap = null;
  showPlatform(platform);
  loop();
}

document.getElementById("platform-cx").addEventListener("click", () => choosePlatform("cx"));
document.getElementById("platform-ex").addEventListener("click", () => choosePlatform("ex"));

async function loop() {
  const ticket = ++state.ticket;
  const platform = state.platform;
  try {
    const response = await fetch("/api/snapshot?platform=" + platform, { cache: "no-store" });
    if (ticket !== state.ticket) return;
    if (!response.ok) throw new Error("status " + response.status);
    const snap = await response.json();
    if (ticket !== state.ticket || (snap.platform && snap.platform !== state.platform)) return;
    apply(snap);
    const wait = Math.max(300, (snap.screen_interval_sec || 0.5) * 1000);
    window.setTimeout(() => {
      if (ticket === state.ticket) loop();
    }, wait);
  } catch (err) {
    if (ticket !== state.ticket) return;
    document.getElementById("status-dot").className = "dot bad";
    document.getElementById("status-text").textContent = "Cannot reach the demo service";
    window.setTimeout(() => {
      if (ticket === state.ticket) loop();
    }, 2000);
  }
}

let stored = "cx";
try {
  stored = localStorage.getItem("colorless-platform") || "cx";
} catch (err) {
  stored = "cx";
}
showPlatform(stored === "ex" ? "ex" : "cx");
loop();
