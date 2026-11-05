const fields = document.getElementById("fields");
const form = document.getElementById("config-form");
const rolesRoot = document.getElementById("roles");
const profilesRoot = document.getElementById("profiles");
const mistRolesRoot = document.getElementById("mist-roles");
const formMsg = document.getElementById("form-msg");

const ids = {
  switchHost: "switch-host",
  switchPort: "switch-port",
  switchUsername: "switch-username",
  switchPassword: "switch-password",
  apiVersion: "api-version",
  vsfMember: "vsf-member",
  switchVerify: "switch-verify",
  clearpassHost: "clearpass-host",
  clearpassClientId: "clearpass-client-id",
  clearpassSecret: "clearpass-client-secret",
  clearpassVerify: "clearpass-verify",
  mistHost: "mist-host",
  mistToken: "mist-token",
  mistVerify: "mist-verify",
  exSite: "ex-site-id",
  exMac: "ex-switch-mac",
  junosHost: "junos-host",
  junosPort: "junos-port",
  junosUsername: "junos-username",
  junosPassword: "junos-password",
  junosVerify: "junos-verify",
  exSourceMist: "ex-source-mist",
  exSourceJunos: "ex-source-junos",
  pollInterval: "poll-interval",
  screenInterval: "screen-interval",
  hidePrevious: "hide-previous",
  showDevice: "show-device-name",
};

function byId(id) {
  return document.getElementById(id);
}

function errorText(data) {
  if (!data) return "Request failed";
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail)) {
    return data.detail.map((item) => item.msg || JSON.stringify(item)).join(" ");
  }
  return "Request failed";
}

function fill(data) {
  byId(ids.switchHost).value = data.switch_host || "";
  byId(ids.switchPort).value = data.switch_port || 443;
  byId(ids.switchUsername).value = data.switch_username || "";
  byId(ids.switchPassword).value = "";
  byId(ids.switchPassword).placeholder = data.switch_password_set
    ? "Saved password kept if blank"
    : "Switch password";
  byId(ids.apiVersion).value = data.api_version || "v10.16";
  byId(ids.vsfMember).value = data.vsf_member || 1;
  byId(ids.switchVerify).checked = Boolean(data.switch_verify_tls);
  byId(ids.clearpassHost).value = data.clearpass_host || "";
  byId(ids.clearpassClientId).value = data.clearpass_client_id || "";
  byId(ids.clearpassSecret).value = "";
  byId(ids.clearpassSecret).placeholder = data.clearpass_client_secret_set
    ? "Saved secret kept if blank"
    : "Client secret";
  byId(ids.clearpassVerify).checked = Boolean(data.clearpass_verify_tls);
  byId(ids.mistHost).value = data.mist_host || "api.mist.com";
  byId(ids.mistToken).value = "";
  byId(ids.mistToken).placeholder = data.mist_api_token_set
    ? "Saved token kept if blank"
    : "API token";
  byId(ids.mistVerify).checked = data.mist_verify_tls !== false;
  byId(ids.exSite).value = data.ex_site_id || "";
  byId(ids.exMac).value = data.ex_switch_mac || "";
  byId(ids.junosHost).value = data.junos_host || "";
  byId(ids.junosPort).value = data.junos_port || 3443;
  byId(ids.junosUsername).value = data.junos_username || "";
  byId(ids.junosPassword).value = "";
  byId(ids.junosPassword).placeholder = data.junos_password_set
    ? "Saved password kept if blank"
    : "Junos password";
  byId(ids.junosVerify).checked = Boolean(data.junos_verify_tls);
  const exChoice = data.ex_source_choice === "junos" ? "junos" : "mist";
  byId(ids.exSourceJunos).checked = exChoice === "junos";
  byId(ids.exSourceMist).checked = exChoice === "mist";
  byId(ids.pollInterval).value = data.poll_interval_sec;
  byId(ids.screenInterval).value = data.screen_interval_sec;
  byId(ids.hidePrevious).checked = Boolean(data.hide_previous_popovers);
  byId(ids.showDevice).checked = Boolean(data.show_device_name_on_mac);
  renderRoles(data.roles || []);
  renderProfiles(data.profiles || []);
  renderMistRoles(data.mist_roles || []);
  renderPoll(data.poll || {});
}

function renderPoll(poll) {
  const switchLine = byId("switch-status");
  const clearpassLine = byId("clearpass-status");
  if (!poll.configured) {
    switchLine.textContent = "Idle until the faceplate is open and a switch host is saved.";
  } else if (!poll.watching && !poll.polled_at) {
    switchLine.textContent = "Idle. Open the faceplate to start polling.";
  } else if (poll.error) {
    switchLine.textContent = poll.error;
  } else if (poll.polled_at) {
    switchLine.textContent = (poll.hostname || "Switch") + (poll.software_version ? " · " + poll.software_version : "") + " · last poll " + poll.polled_at;
  } else {
    switchLine.textContent = poll.watching ? "Waiting for the first poll." : "Idle. Open the faceplate to start polling.";
  }
  if (!poll.clearpass_configured) clearpassLine.textContent = "";
  else if (poll.clearpass_error) clearpassLine.textContent = poll.clearpass_error;
  else if (poll.clearpass_ok) clearpassLine.textContent = "ClearPass lookups are succeeding.";
  else clearpassLine.textContent = "";
  renderEx(poll.ex || {});
}

function renderEx(ex) {
  const line = byId("ex-status");
  const junos = byId("junos-status");
  const choiceLine = byId("ex-source-status");
  const detail = exDetail(ex);
  const choice = ex.choice || "";
  const active = ex.source || "";
  if (choiceLine) choiceLine.textContent = sourceStatus(choice, active);
  if (active === "junos") {
    line.textContent = "Idle. Junos is the EX source.";
    junos.textContent = detail || "Polling Junos.";
    return;
  }
  if (active === "mist") {
    junos.textContent = "Idle. Mist is the EX source.";
    line.textContent = detail || "Polling Mist.";
    return;
  }
  junos.textContent = choice === "junos"
    ? "Selected. Enter a host, username, and password, then Save."
    : "Idle. Mist is selected under EX polling.";
  line.textContent = choice === "mist"
    ? "Selected. Enter a site, switch MAC, and API token, then Save."
    : "Idle. Junos is selected under EX polling.";
}

function sourceStatus(choice, active) {
  if (active === "junos") return "Junos is the EX source. Choose Mist and Save to switch. The Junos host can stay filled in.";
  if (active === "mist") return "Mist is the EX source. Choose Junos and Save to switch. The Mist site and token can stay filled in.";
  if (choice === "junos") return "Junos is selected. Enter a host, username, and password, then Save.";
  if (choice === "mist") return "Mist is selected. Enter a site, switch MAC, and API token, then Save.";
  return "Choose Mist or Junos, then Save.";
}

function exDetail(ex) {
  if (!ex.configured) return "";
  if (!ex.watching && !ex.polled_at) return "Idle. Open the faceplate and choose EX to start polling.";
  if (ex.error) return ex.error;
  if (ex.polled_at) {
    return (ex.hostname || "EX") + (ex.software_version ? " · " + ex.software_version : "") + " · last poll " + ex.polled_at;
  }
  return ex.watching ? "Waiting for the first poll." : "Idle. Open the faceplate and choose EX to start polling.";
}

const specialLabels = { up: "Port up", down: "Port down", multi: "Multiple" };

function openKeys(root) {
  const keys = new Set();
  root.querySelectorAll(".role").forEach((card) => {
    const details = card.querySelector("details");
    if (!details || !details.open) return;
    if (card.dataset.id) keys.add("id:" + card.dataset.id);
    const name = (card.querySelector(".name")?.value || "").trim();
    if (name) keys.add("name:" + name);
  });
  return keys;
}

function renderRoles(roles) {
  const open = openKeys(rolesRoot);
  rolesRoot.replaceChildren();
  const ordered = [...roles].sort((a, b) => (a.legend_order - b.legend_order) || ((a.id || 0) - (b.id || 0)));
  for (const role of ordered) {
    const name = (role.name || "").trim();
    const wasOpen = (role.id && open.has("id:" + role.id)) || (name && open.has("name:" + name));
    rolesRoot.append(roleCard(role, wasOpen));
  }
}

function roleCard(role, open) {
  const card = document.createElement("article");
  card.className = "role";
  if (role.id) card.dataset.id = String(role.id);

  const details = document.createElement("details");
  if (open) details.open = true;
  const summary = document.createElement("summary");
  const swatch = document.createElement("span");
  swatch.className = "role-swatch";
  swatch.hidden = true;
  const title = document.createElement("span");
  title.className = "role-title";
  const meta = document.createElement("span");
  meta.className = "role-meta";
  meta.hidden = true;
  const badge = document.createElement("span");
  badge.className = "role-badge";
  badge.hidden = true;
  summary.append(swatch, title, meta, badge);

  const body = document.createElement("div");
  body.className = "role-body";
  body.append(roleFields(role));
  details.append(summary, body);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "secondary remove";
  remove.textContent = "Remove";
  remove.addEventListener("click", () => removeRole(card));

  card.append(details, remove);
  body.addEventListener("input", () => paintSummary(card));
  body.addEventListener("change", () => paintSummary(card));
  paintSummary(card);
  return card;
}

function paintSummary(card) {
  const show = card.querySelector(".show-light").checked;
  const color = card.querySelector(".color").value;
  const display = card.querySelector(".display").value.trim();
  const name = card.querySelector(".name").value.trim();
  const swatch = card.querySelector(".role-swatch");
  const title = card.querySelector(".role-title");
  const meta = card.querySelector(".role-meta");
  const badge = card.querySelector(".role-badge");
  title.textContent = display || name || card.dataset.emptyTitle || (card.classList.contains("profile") ? "New port profile" : "New role");
  const switchName = name && display && name !== display ? name : "";
  meta.textContent = switchName;
  meta.hidden = !switchName;
  swatch.hidden = !(show && color);
  if (show && color) swatch.style.background = color;
  let special = "";
  card.querySelectorAll('input[type="radio"]').forEach((input) => {
    if (input.checked) special = input.value;
  });
  badge.textContent = specialLabels[special] || "";
  badge.hidden = !badge.textContent;
}

function roleFields(role) {
  const wrap = document.createElement("div");
  const top = document.createElement("div");
  top.className = "role-top";
  top.append(colorField(role.port_color || ""));
  top.append(textField("Name", "name", role.name || "", "Switch role name"));
  top.append(textField("Label", "display", role.display_name || "", "Legend label"));
  wrap.append(top);

  const description = document.createElement("label");
  description.className = "grow";
  description.append(document.createTextNode("Permissions"));
  const area = document.createElement("textarea");
  area.className = "description";
  area.value = role.description || "";
  description.append(area);
  wrap.append(description);

  const meta = document.createElement("div");
  meta.className = "role-top";
  const order = document.createElement("label");
  order.append(document.createTextNode("Legend order"));
  const orderInput = document.createElement("input");
  orderInput.type = "number";
  orderInput.min = "0";
  orderInput.max = "99";
  orderInput.className = "legend-order";
  orderInput.value = String(role.legend_order ?? 0);
  order.append(orderInput);
  meta.append(order);
  meta.append(check("Suppress automatic popover", "no-popover", Boolean(role.no_popover)));
  wrap.append(meta);

  const specials = document.createElement("div");
  specials.className = "role-specials";
  specials.append(radio("Port up", "up", role.special === "up"));
  specials.append(radio("Port down", "down", role.special === "down"));
  specials.append(radio("Multiple roles", "multi", role.special === "multi"));
  wrap.append(specials);
  return wrap;
}

function colorField(color) {
  const label = document.createElement("label");
  label.className = "color-field";
  label.append(document.createTextNode("Color"));
  const row = document.createElement("span");
  row.className = "check color-well";
  const show = document.createElement("input");
  show.type = "checkbox";
  show.className = "show-light";
  show.checked = Boolean(color);
  const picker = document.createElement("input");
  picker.type = "color";
  picker.className = "color";
  picker.value = color || "#888888";
  picker.disabled = !show.checked;
  show.addEventListener("change", () => {
    picker.disabled = !show.checked;
  });
  row.append(show, document.createTextNode(" Show a light"), picker);
  label.append(row);
  return label;
}

function textField(title, className, value, placeholder) {
  const label = document.createElement("label");
  label.append(document.createTextNode(title));
  const input = document.createElement("input");
  input.type = "text";
  input.className = className;
  input.value = value;
  input.placeholder = placeholder;
  label.append(input);
  return label;
}

function check(title, className, checked) {
  const label = document.createElement("label");
  label.className = "check";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.className = className;
  input.checked = checked;
  label.append(input, document.createTextNode(" " + title));
  return label;
}

function radio(title, kind, checked) {
  const label = document.createElement("label");
  label.className = "check";
  const input = document.createElement("input");
  input.type = "radio";
  input.name = "special-" + kind;
  input.value = kind;
  input.checked = checked;
  const hints = {
    up: "Required legend slot. It does not light a port that has no authenticated client.",
    down: "Color for a port with nothing connected.",
    multi: "Color when two or more different roles share the port.",
  };
  if (hints[kind]) label.title = hints[kind];
  input.addEventListener("change", () => {
    if (!input.checked) return;
    const card = input.closest(".role");
    card.querySelectorAll('input[type="radio"]').forEach((other) => {
      if (other !== input) other.checked = false;
    });
  });
  label.append(input, document.createTextNode(" " + title));
  return label;
}

function removeRole(card) {
  const selected = [...card.querySelectorAll('input[type="radio"]')].filter((input) => input.checked);
  if (selected.length) {
    setMessage("Pick another role for " + selected[0].value + " before removing this one.", false);
    return;
  }
  card.remove();
}

function renderProfiles(profiles) {
  const open = openKeys(profilesRoot);
  profilesRoot.replaceChildren();
  const ordered = [...profiles].sort((a, b) => (a.legend_order - b.legend_order) || ((a.id || 0) - (b.id || 0)));
  for (const profile of ordered) {
    const name = (profile.name || "").trim();
    const wasOpen = (profile.id && open.has("id:" + profile.id)) || (name && open.has("name:" + name));
    profilesRoot.append(namedCard(profile, wasOpen, "profile", "New port profile"));
  }
}

function namedCard(profile, open, extraClass, emptyTitle) {
  const card = document.createElement("article");
  card.className = "role " + extraClass;
  card.dataset.emptyTitle = emptyTitle;
  if (profile.id) card.dataset.id = String(profile.id);

  const details = document.createElement("details");
  if (open) details.open = true;
  const summary = document.createElement("summary");
  const swatch = document.createElement("span");
  swatch.className = "role-swatch";
  swatch.hidden = true;
  const title = document.createElement("span");
  title.className = "role-title";
  const meta = document.createElement("span");
  meta.className = "role-meta";
  meta.hidden = true;
  const badge = document.createElement("span");
  badge.className = "role-badge";
  badge.hidden = true;
  summary.append(swatch, title, meta, badge);

  const body = document.createElement("div");
  body.className = "role-body";
  body.append(profileFields(profile, extraClass === "mist-role" ? "EMPLOYEE" : "dot1x-only"));
  details.append(summary, body);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "secondary remove";
  remove.textContent = "Remove";
  remove.addEventListener("click", () => card.remove());

  card.append(details, remove);
  body.addEventListener("input", () => paintSummary(card));
  body.addEventListener("change", () => paintSummary(card));
  paintSummary(card);
  return card;
}

function profileFields(profile, namePlaceholder) {
  const wrap = document.createElement("div");
  const top = document.createElement("div");
  top.className = "role-top";
  top.append(colorField(profile.port_color || ""));
  top.append(textField("Name", "name", profile.name || "", namePlaceholder || "dot1x-only"));
  top.append(textField("Label", "display", profile.display_name || "", "Legend label"));
  wrap.append(top);

  const description = document.createElement("label");
  description.className = "grow";
  description.append(document.createTextNode("Notes"));
  const area = document.createElement("textarea");
  area.className = "description";
  area.value = profile.description || "";
  description.append(area);
  wrap.append(description);

  const meta = document.createElement("div");
  meta.className = "role-top";
  const order = document.createElement("label");
  order.append(document.createTextNode("Legend order"));
  const orderInput = document.createElement("input");
  orderInput.type = "number";
  orderInput.min = "0";
  orderInput.max = "99";
  orderInput.className = "legend-order";
  orderInput.value = String(profile.legend_order ?? 1);
  order.append(orderInput);
  meta.append(order);
  meta.append(check("Suppress automatic popover", "no-popover", Boolean(profile.no_popover)));
  wrap.append(meta);
  return wrap;
}

function renderMistRoles(roles) {
  const open = openKeys(mistRolesRoot);
  mistRolesRoot.replaceChildren();
  const ordered = [...roles].sort((a, b) => (a.legend_order - b.legend_order) || ((a.id || 0) - (b.id || 0)));
  for (const role of ordered) {
    const name = (role.name || "").trim();
    const wasOpen = (role.id && open.has("id:" + role.id)) || (name && open.has("name:" + name));
    mistRolesRoot.append(namedCard(role, wasOpen, "mist-role", "New Mist role"));
  }
}

function addMistRole() {
  const orders = [...mistRolesRoot.querySelectorAll(".legend-order")].map((input) => Number(input.value) || 0);
  const next = orders.length ? Math.max(...orders) + 1 : 1;
  const card = namedCard({
    name: "",
    display_name: "",
    description: "",
    port_color: "#FF8300",
    legend_order: next,
    no_popover: false,
  }, true, "mist-role", "New Mist role");
  mistRolesRoot.append(card);
  openSection("mist-roles");
  const name = card.querySelector(".name");
  if (name) name.focus();
}

function collectMistRoles() {
  return collectNamed(mistRolesRoot);
}

function addProfile() {
  const orders = [...profilesRoot.querySelectorAll(".legend-order")].map((input) => Number(input.value) || 0);
  const next = orders.length ? Math.max(...orders) + 1 : 1;
  const card = namedCard({
    name: "",
    display_name: "",
    description: "",
    port_color: "#888888",
    legend_order: next,
    no_popover: false,
  }, true, "profile", "New port profile");
  profilesRoot.append(card);
  openSection("profiles");
  const name = card.querySelector(".name");
  if (name) name.focus();
}

function collectNamed(root) {
  return [...root.querySelectorAll(".role")].map((card) => {
    const show = card.querySelector(".show-light").checked;
    return {
      id: card.dataset.id ? Number(card.dataset.id) : null,
      name: card.querySelector(".name").value,
      display_name: card.querySelector(".display").value,
      description: card.querySelector(".description").value,
      port_color: show ? card.querySelector(".color").value : "",
      legend_order: Number(card.querySelector(".legend-order").value || 0),
      no_popover: card.querySelector(".no-popover").checked,
    };
  });
}

function collectProfiles() {
  return collectNamed(profilesRoot);
}

function addRole() {
  const orders = [...rolesRoot.querySelectorAll(".legend-order")].map((input) => Number(input.value) || 0);
  const next = orders.length ? Math.max(...orders) + 1 : 1;
  const card = roleCard({
    name: "",
    display_name: "",
    description: "",
    port_color: "#888888",
    legend_order: next,
    no_popover: false,
    special: "",
  }, true);
  rolesRoot.append(card);
  openSection("roles");
  const name = card.querySelector(".name");
  if (name) name.focus();
}

function openSection(name) {
  const section = document.querySelector(`details[data-section="${name}"]`);
  if (!section) return;
  let node = section;
  while (node) {
    if (node.tagName === "DETAILS") node.open = true;
    node = node.parentElement;
  }
}

function rememberSections() {
  document.querySelectorAll(".card > details").forEach((details) => {
    const key = "admin-card:" + (details.dataset.section || "");
    try {
      details.open = sessionStorage.getItem(key) === "1";
    } catch (err) {
      details.open = false;
    }
    details.addEventListener("toggle", () => {
      try {
        sessionStorage.setItem(key, details.open ? "1" : "0");
      } catch (err) {
        /* Private mode can reject storage. The card still toggles. */
      }
    });
  });
}

function collectRoles() {
  return [...rolesRoot.querySelectorAll(".role")].map((card) => {
    let special = "";
    card.querySelectorAll('input[type="radio"]').forEach((input) => {
      if (input.checked) special = input.value;
    });
    const show = card.querySelector(".show-light").checked;
    return {
      id: card.dataset.id ? Number(card.dataset.id) : null,
      name: card.querySelector(".name").value,
      display_name: card.querySelector(".display").value,
      description: card.querySelector(".description").value,
      port_color: show ? card.querySelector(".color").value : "",
      legend_order: Number(card.querySelector(".legend-order").value || 0),
      no_popover: card.querySelector(".no-popover").checked,
      special,
    };
  });
}

function payload() {
  return {
    switch_host: byId(ids.switchHost).value,
    switch_port: Number(byId(ids.switchPort).value || 443),
    switch_username: byId(ids.switchUsername).value,
    switch_password: byId(ids.switchPassword).value,
    api_version: byId(ids.apiVersion).value,
    switch_verify_tls: byId(ids.switchVerify).checked,
    vsf_member: Number(byId(ids.vsfMember).value || 1),
    clearpass_host: byId(ids.clearpassHost).value,
    clearpass_client_id: byId(ids.clearpassClientId).value,
    clearpass_client_secret: byId(ids.clearpassSecret).value,
    clearpass_verify_tls: byId(ids.clearpassVerify).checked,
    mist_host: byId(ids.mistHost).value,
    mist_api_token: byId(ids.mistToken).value,
    mist_verify_tls: byId(ids.mistVerify).checked,
    ex_site_id: byId(ids.exSite).value,
    ex_switch_mac: byId(ids.exMac).value,
    junos_host: byId(ids.junosHost).value,
    junos_port: Number(byId(ids.junosPort).value || 3443),
    junos_username: byId(ids.junosUsername).value,
    junos_password: byId(ids.junosPassword).value,
    junos_verify_tls: byId(ids.junosVerify).checked,
    ex_source_choice: byId(ids.exSourceJunos).checked ? "junos" : "mist",
    poll_interval_sec: Number(byId(ids.pollInterval).value),
    screen_interval_sec: Number(byId(ids.screenInterval).value),
    visualize_unknown: false,
    hide_previous_popovers: byId(ids.hidePrevious).checked,
    show_device_name_on_mac: byId(ids.showDevice).checked,
    roles: collectRoles(),
    profiles: collectProfiles(),
    mist_roles: collectMistRoles(),
  };
}

function setMessage(text, ok) {
  formMsg.textContent = text;
  formMsg.className = "form-msg " + (ok ? "ok" : "bad");
}

async function load() {
  const response = await fetch("/api/admin/config", { cache: "no-store" });
  if (!response.ok) {
    setMessage("Could not load settings", false);
    return;
  }
  fill(await response.json());
  fields.disabled = false;
}

async function save(event) {
  event.preventDefault();
  setMessage("Saving…", true);
  const response = await fetch("/api/admin/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload()),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    setMessage(errorText(data), false);
    return;
  }
  fill(data);
  setMessage("Saved", true);
}

function showTest(id, ok, text) {
  const node = byId(id);
  node.textContent = text;
  node.className = "test-result " + (ok ? "ok" : "bad");
}

async function postTest(url, body, resultId, successText) {
  showTest(resultId, true, "Contacting…");
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    showTest(resultId, false, errorText(data));
    return;
  }
  if (!data.ok) {
    showTest(resultId, false, data.error || "Failed");
    return;
  }
  showTest(resultId, true, successText(data));
}

form.addEventListener("submit", save);
byId("reload").addEventListener("click", () => {
  setMessage("", true);
  fields.disabled = true;
  load();
});
byId("add-role").addEventListener("click", addRole);
byId("add-profile").addEventListener("click", addProfile);
byId("add-mist-role").addEventListener("click", addMistRole);
byId("open-faq").addEventListener("click", () => {
  document.getElementById("faq").showModal();
});
byId("load-junos-roles").addEventListener("click", () => {
  const body = payload();
  postLoad("/api/admin/roles/junos", body, (data) => loadSummary(data, "Junos"));
});
byId("load-mist-roles").addEventListener("click", () => {
  const body = payload();
  postLoad("/api/admin/roles/mist-template", body, (data) => {
    const from = data.template ? "Mist template " + data.template : "Mist template";
    return loadSummary(data, from);
  });
});
byId("test-switch").addEventListener("click", () => {
  const body = payload();
  postTest("/api/admin/test/switch", body, "test-switch-result", (data) => {
    const host = data.hostname || "Switch";
    const ver = data.software_version ? " · " + data.software_version : "";
    return host + ver + " · " + data.ports_up + " of 12 ports up · " + data.clients + " clients";
  });
});
byId("test-clearpass").addEventListener("click", () => {
  postTest("/api/admin/test/clearpass", payload(), "test-clearpass-result", (data) => data.message);
});
byId("test-mist").addEventListener("click", () => {
  postTest("/api/admin/test/mist", payload(), "test-mist-result", (data) => {
    return data.name ? "Token accepted for " + data.name : data.message;
  });
});
byId("test-ex").addEventListener("click", () => {
  postTest("/api/admin/test/ex", payload(), "test-ex-result", (data) => {
    const host = data.hostname || "EX";
    const ver = data.software_version ? " · " + data.software_version : "";
    return host + ver + " · " + data.ports_up + " of 12 ports up · " + data.clients + " clients";
  });
});
byId("test-junos").addEventListener("click", () => {
  postTest("/api/admin/test/junos", payload(), "test-junos-result", (data) => {
    const host = data.hostname || "Junos";
    const ver = data.software_version ? " · " + data.software_version : "";
    return host + ver + " · " + data.ports_up + " of 12 ports up · " + data.clients + " clients";
  });
});

function loadSummary(data, source) {
  const added = data.added || [];
  const present = data.present || [];
  const parts = [];
  if (added.length) parts.push("Added " + added.join(", "));
  if (present.length) parts.push(present.join(", ") + " already on the list");
  if (!parts.length) parts.push("No roles returned");
  return source + ". " + parts.join(". ") + ". Save to keep them.";
}

async function postLoad(url, body, successText) {
  showTest("load-roles-result", true, "Contacting…");
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    showTest("load-roles-result", false, errorText(data));
    return;
  }
  if (!data.ok) {
    showTest("load-roles-result", false, data.error || "Failed");
    return;
  }
  renderMistRoles(data.roles || []);
  openSection("mist-roles");
  showTest("load-roles-result", true, successText(data));
}

window.setInterval(async () => {
  if (fields.disabled) return;
  const response = await fetch("/api/admin/config", { cache: "no-store" });
  if (!response.ok) return;
  const data = await response.json();
  renderPoll(data.poll || {});
}, 4000);

rememberSections();
load();
