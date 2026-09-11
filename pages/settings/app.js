const bridge = window.AstrBotPluginPage;

const elements = {
  alertBox: document.getElementById("alertBox"),
  connectBaseUrl: document.getElementById("connectBaseUrl"),
  mapNameUrl: document.getElementById("mapNameUrl"),
  hhBotId: document.getElementById("hhBotId"),
  hhBotToken: document.getElementById("hhBotToken"),
  safeMode: document.getElementById("safeMode"),
  groupCount: document.getElementById("groupCount"),
  serverCount: document.getElementById("serverCount"),
  safeModeState: document.getElementById("safeModeState"),
  saveState: document.getElementById("saveState"),
  saveButton: document.getElementById("saveButton"),
  reloadButton: document.getElementById("reloadButton"),
  addGroupButton: document.getElementById("addGroupButton"),
  emptyAddGroupButton: document.getElementById("emptyAddGroupButton"),
  groupsContainer: document.getElementById("groupsContainer"),
  emptyGroups: document.getElementById("emptyGroups"),
  loadingLayer: document.getElementById("loadingLayer"),
  confirmLayer: document.getElementById("confirmLayer"),
  confirmMessage: document.getElementById("confirmMessage"),
  confirmCancel: document.getElementById("confirmCancel"),
  confirmAccept: document.getElementById("confirmAccept"),
  toast: document.getElementById("toast"),
};

let state = createEmptyConfig();
let revision = "";
let baseline = "";
let busy = true;
let loaded = false;
let openGroups = new Set();
let toastTimer = null;
let confirmResolver = null;

function createEmptyConfig() {
  return {
    connectBaseUrl: "",
    mapNameUrl: "",
    safeMode: false,
    hh_bot_id: "",
    hh_bot_token: "",
    group_configs: [],
  };
}

function createEmptyGroup() {
  return {
    group_id: "",
    group_name: "",
    hh_room_id: "",
    admin_users: [],
    servers: [createEmptyServer()],
  };
}

function createEmptyServer() {
  return {
    name: "",
    address: "",
    hh_channel_id: "",
    rcon_password: "",
  };
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function asText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string" || typeof value === "number") return String(value);
  return "";
}

function normalizeConfig(rawConfig) {
  const source = isPlainObject(rawConfig) ? rawConfig : {};
  const groups = Array.isArray(source.group_configs) ? source.group_configs : [];

  return {
    ...source,
    connectBaseUrl: asText(source.connectBaseUrl),
    mapNameUrl: asText(source.mapNameUrl),
    safeMode: source.safeMode === true,
    hh_bot_id: asText(source.hh_bot_id),
    hh_bot_token: asText(source.hh_bot_token),
    group_configs: groups.filter(isPlainObject).map((group) => ({
      ...group,
      group_id: asText(group.group_id),
      group_name: asText(group.group_name),
      hh_room_id: asText(group.hh_room_id),
      admin_users: Array.isArray(group.admin_users)
        ? [...new Set(group.admin_users.map(asText).filter(Boolean))]
        : [],
      servers: Array.isArray(group.servers)
        ? group.servers.filter(isPlainObject).map((server) => ({
            ...server,
            name: asText(server.name),
            address: asText(server.address),
            hh_channel_id: asText(server.hh_channel_id),
            rcon_password: asText(server.rcon_password),
          }))
        : [],
    })),
  };
}

function snapshot(value) {
  return JSON.stringify(value);
}

function isDirty() {
  return snapshot(state) !== baseline;
}

function setTheme(context) {
  document.documentElement.dataset.theme = context?.isDark ? "dark" : "light";
  document.documentElement.lang = context?.locale || "zh-CN";
}

function setBusy(nextBusy, message = "正在读取配置…") {
  busy = nextBusy;
  elements.loadingLayer.hidden = !nextBusy;
  const messageNode = elements.loadingLayer.querySelector("span");
  if (messageNode) messageNode.textContent = message;
  elements.reloadButton.disabled = nextBusy;
  elements.saveButton.disabled = nextBusy || !loaded || !isDirty();
  elements.addGroupButton.disabled = nextBusy;
  elements.emptyAddGroupButton.disabled = nextBusy;
}

function refreshStatus(mode = null) {
  const dirty = isDirty();
  elements.saveState.classList.remove("is-saved", "is-dirty", "is-error");

  if (mode === "error") {
    elements.saveState.classList.add("is-error");
    elements.saveState.querySelector(".status-label").textContent = "需要处理";
  } else if (dirty) {
    elements.saveState.classList.add("is-dirty");
    elements.saveState.querySelector(".status-label").textContent = "有未保存修改";
  } else {
    elements.saveState.classList.add("is-saved");
    elements.saveState.querySelector(".status-label").textContent = "已同步";
  }

  elements.saveButton.disabled = busy || !loaded || !dirty;
  renderStats();
}

function markDirty() {
  hideAlert();
  refreshStatus();
}

function renderStats() {
  const groups = state.group_configs || [];
  const servers = groups.reduce(
    (total, group) => total + (Array.isArray(group.servers) ? group.servers.length : 0),
    0,
  );
  elements.groupCount.textContent = String(groups.length);
  elements.serverCount.textContent = String(servers);
  elements.safeModeState.textContent = state.safeMode ? "开启" : "关闭";
  const switchText = elements.safeMode.closest(".switch")?.querySelector(".switch-text");
  if (switchText) switchText.textContent = state.safeMode ? "开启" : "关闭";
}

function showAlert(messages) {
  const list = Array.isArray(messages) ? messages : [messages];
  elements.alertBox.replaceChildren();

  if (list.length === 1) {
    elements.alertBox.textContent = list[0];
  } else {
    const title = document.createElement("strong");
    title.textContent = `保存前请处理以下 ${list.length} 个问题：`;
    const ul = document.createElement("ul");
    for (const message of list) {
      const li = document.createElement("li");
      li.textContent = message;
      ul.append(li);
    }
    elements.alertBox.append(title, ul);
  }

  elements.alertBox.hidden = false;
  elements.alertBox.scrollIntoView({ behavior: "smooth", block: "center" });
}

function hideAlert() {
  elements.alertBox.hidden = true;
  elements.alertBox.replaceChildren();
  document.querySelectorAll('[aria-invalid="true"]').forEach((input) => {
    input.removeAttribute("aria-invalid");
  });
}

function showToast(message, type = "success") {
  window.clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.classList.toggle("is-error", type === "error");
  elements.toast.classList.add("is-visible");
  toastTimer = window.setTimeout(() => {
    elements.toast.classList.remove("is-visible");
  }, 3200);
}

function bindGlobalControls() {
  const textBindings = [
    [elements.connectBaseUrl, "connectBaseUrl"],
    [elements.mapNameUrl, "mapNameUrl"],
    [elements.hhBotId, "hh_bot_id"],
    [elements.hhBotToken, "hh_bot_token"],
  ];

  for (const [input, key] of textBindings) {
    input.addEventListener("input", () => {
      state[key] = input.value;
      markDirty();
    });
  }

  elements.safeMode.addEventListener("change", () => {
    state.safeMode = elements.safeMode.checked;
    markDirty();
  });

  document.querySelectorAll("[data-secret-target]").forEach((button) => {
    button.addEventListener("click", () => toggleSecret(button));
  });

  elements.addGroupButton.addEventListener("click", addGroup);
  elements.emptyAddGroupButton.addEventListener("click", addGroup);
  elements.saveButton.addEventListener("click", saveConfig);
  elements.reloadButton.addEventListener("click", () => loadConfig(false));
  elements.confirmCancel.addEventListener("click", () => closeConfirmation(false));
  elements.confirmAccept.addEventListener("click", () => closeConfirmation(true));
  elements.confirmLayer.addEventListener("click", (event) => {
    if (event.target === elements.confirmLayer) closeConfirmation(false);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !elements.confirmLayer.hidden) {
      closeConfirmation(false);
    }
  });
}

function renderGlobalControls() {
  elements.connectBaseUrl.value = state.connectBaseUrl;
  elements.mapNameUrl.value = state.mapNameUrl;
  elements.hhBotId.value = state.hh_bot_id;
  elements.hhBotToken.value = state.hh_bot_token;
  elements.safeMode.checked = state.safeMode;
  renderStats();
}

function toggleSecret(button) {
  const input = document.getElementById(button.dataset.secretTarget);
  if (!input) return;
  const showing = input.type === "text";
  input.type = showing ? "password" : "text";
  button.textContent = showing ? "显示" : "隐藏";
}

function addGroup() {
  state.group_configs.push(createEmptyGroup());
  const newIndex = state.group_configs.length - 1;
  openGroups.add(newIndex);
  renderGroups();
  markDirty();
  requestAnimationFrame(() => {
    document.querySelector(`[data-group-index="${newIndex}"] input[data-field="group_id"]`)?.focus();
  });
}

async function removeGroup(groupIndex) {
  const group = state.group_configs[groupIndex];
  const label = group.group_name || group.group_id || `#${groupIndex + 1}`;
  const confirmed = await requestConfirmation(
    `确定删除群组 ${label} 及其全部服务器配置吗？`,
    "确认删除群组",
  );
  if (!confirmed) return;
  state.group_configs.splice(groupIndex, 1);
  openGroups = new Set([...openGroups].filter((index) => index !== groupIndex).map(
    (index) => (index > groupIndex ? index - 1 : index),
  ));
  renderGroups();
  markDirty();
}

function addServer(groupIndex) {
  const group = state.group_configs[groupIndex];
  group.servers.push(createEmptyServer());
  openGroups.add(groupIndex);
  renderGroups();
  markDirty();
  const newServerIndex = group.servers.length - 1;
  requestAnimationFrame(() => {
    document.querySelector(
      `[data-group-index="${groupIndex}"] [data-server-index="${newServerIndex}"] input[data-field="name"]`,
    )?.focus();
  });
}

async function removeServer(groupIndex, serverIndex) {
  const server = state.group_configs[groupIndex].servers[serverIndex];
  const label = server.name || `#${serverIndex + 1}`;
  const confirmed = await requestConfirmation(
    `确定删除服务器 ${label} 吗？此操作会在保存配置后生效。`,
    "确认删除服务器",
  );
  if (!confirmed) return;
  state.group_configs[groupIndex].servers.splice(serverIndex, 1);
  renderGroups();
  markDirty();
}

function renderGroups() {
  elements.groupsContainer.replaceChildren();
  const groups = state.group_configs || [];
  elements.emptyGroups.hidden = groups.length !== 0;
  elements.groupsContainer.hidden = groups.length === 0;

  groups.forEach((group, groupIndex) => {
    elements.groupsContainer.append(createGroupCard(group, groupIndex));
  });
  renderStats();
}

function createGroupCard(group, groupIndex) {
  const details = document.createElement("details");
  details.className = "group-card";
  details.dataset.groupIndex = String(groupIndex);
  details.open = openGroups.has(groupIndex) || state.group_configs.length === 1;
  if (details.open) openGroups.add(groupIndex);

  details.innerHTML = `
    <summary class="group-summary">
      <div class="group-summary-main">
        <span class="disclosure" aria-hidden="true">›</span>
        <span class="group-order">${String(groupIndex + 1).padStart(2, "0")}</span>
        <span class="group-title-wrap">
          <span class="group-title"></span>
          <span class="group-meta"></span>
        </span>
      </div>
      <div class="group-summary-actions">
        <span class="server-count-pill"></span>
        <button class="icon-button remove-group" type="button" aria-label="删除群组" title="删除群组">×</button>
      </div>
    </summary>
    <div class="group-body">
      <div class="form-grid group-fields">
        <label class="field">
          <span class="field-label">群组名称</span>
          <span class="field-hint">仅用于配置页展示，方便识别群组，可留空</span>
          <input type="text" data-field="group_name" autocomplete="off" placeholder="例如 主群" />
        </label>
        <label class="field">
          <span class="field-label">群组 ID</span>
          <span class="field-hint">机器人收到事件时使用的 group_id</span>
          <input type="text" data-field="group_id" autocomplete="off" placeholder="例如 12345678" />
        </label>
        <label class="field">
          <span class="field-label">黑盒语音房间 ID</span>
          <span class="field-hint">该群组对应的语音房间，可留空</span>
          <input type="text" data-field="hh_room_id" autocomplete="off" placeholder="Room ID" />
        </label>
        <div class="admin-editor">
          <span class="field-label">管理员用户</span>
          <span class="field-hint">只有列表中的用户可以执行 RCON 和重启指令；支持回车或逗号批量添加。</span>
          <div class="tag-input-row">
            <input class="admin-input" type="text" autocomplete="off" placeholder="输入用户 ID" />
            <button class="button button-secondary button-small add-admin" type="button">添加</button>
          </div>
          <div class="tag-list" aria-label="管理员列表"></div>
        </div>
      </div>
      <div class="servers-block">
        <div class="server-list-heading">
          <div>
            <h3>服务器列表</h3>
            <p>服务器名用于查询指令匹配，地址支持 host 或 host:port。</p>
          </div>
          <button class="button button-secondary button-small add-server" type="button">＋ 添加服务器</button>
        </div>
        <div class="servers-list"></div>
      </div>
    </div>
  `;

  const title = details.querySelector(".group-title");
  const meta = details.querySelector(".group-meta");
  const serverCount = details.querySelector(".server-count-pill");
  const groupNameInput = details.querySelector('input[data-field="group_name"]');
  const groupIdInput = details.querySelector('input[data-field="group_id"]');
  const roomIdInput = details.querySelector('input[data-field="hh_room_id"]');
  const adminInput = details.querySelector(".admin-input");
  const tagList = details.querySelector(".tag-list");
  const serversList = details.querySelector(".servers-list");

  function updateGroupSummary() {
    title.textContent =
      group.group_name || (group.group_id ? `群组 ${group.group_id}` : "未命名群组");
    meta.textContent = group.hh_room_id ? `黑盒房间 ${group.hh_room_id}` : "未关联黑盒语音房间";
    serverCount.textContent = `${group.servers.length} 台服务器`;
  }

  groupNameInput.value = group.group_name;
  groupNameInput.dataset.path = `group_configs.${groupIndex}.group_name`;
  groupIdInput.value = group.group_id;
  groupIdInput.dataset.path = `group_configs.${groupIndex}.group_id`;
  roomIdInput.value = group.hh_room_id;
  roomIdInput.dataset.path = `group_configs.${groupIndex}.hh_room_id`;
  updateGroupSummary();

  groupNameInput.addEventListener("input", () => {
    group.group_name = groupNameInput.value;
    updateGroupSummary();
    markDirty();
  });
  groupIdInput.addEventListener("input", () => {
    group.group_id = groupIdInput.value;
    updateGroupSummary();
    markDirty();
  });
  roomIdInput.addEventListener("input", () => {
    group.hh_room_id = roomIdInput.value;
    updateGroupSummary();
    markDirty();
  });

  details.addEventListener("toggle", () => {
    if (details.open) openGroups.add(groupIndex);
    else openGroups.delete(groupIndex);
  });
  details.querySelector(".remove-group").addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    removeGroup(groupIndex);
  });
  details.querySelector(".add-server").addEventListener("click", () => addServer(groupIndex));

  function commitAdmins() {
    const values = adminInput.value
      .split(/[\s,，;；]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (values.length === 0) return;
    group.admin_users = [...new Set([...group.admin_users, ...values])];
    adminInput.value = "";
    renderAdminTags(tagList, group, groupIndex);
    markDirty();
  }

  details.querySelector(".add-admin").addEventListener("click", commitAdmins);
  adminInput.addEventListener("blur", commitAdmins);
  adminInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === "," || event.key === "，") {
      event.preventDefault();
      commitAdmins();
    }
  });

  renderAdminTags(tagList, group, groupIndex);
  if (group.servers.length === 0) {
    const empty = document.createElement("div");
    empty.className = "server-empty";
    empty.textContent = "当前群组还没有服务器，点击“添加服务器”开始配置。";
    serversList.append(empty);
  } else {
    group.servers.forEach((server, serverIndex) => {
      serversList.append(createServerCard(server, groupIndex, serverIndex));
    });
  }

  return details;
}

function renderAdminTags(container, group, groupIndex) {
  container.replaceChildren();
  if (group.admin_users.length === 0) {
    const empty = document.createElement("span");
    empty.className = "field-hint";
    empty.textContent = "暂无管理员";
    container.append(empty);
    return;
  }

  group.admin_users.forEach((userId, userIndex) => {
    const chip = document.createElement("span");
    chip.className = "tag-chip";
    const label = document.createElement("span");
    label.textContent = userId;
    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "chip-remove";
    removeButton.setAttribute("aria-label", `移除管理员 ${userId}`);
    removeButton.textContent = "×";
    removeButton.addEventListener("click", () => {
      group.admin_users.splice(userIndex, 1);
      renderAdminTags(container, group, groupIndex);
      markDirty();
    });
    chip.append(label, removeButton);
    container.append(chip);
  });
}

function createServerCard(server, groupIndex, serverIndex) {
  const card = document.createElement("article");
  card.className = "server-card";
  card.dataset.serverIndex = String(serverIndex);
  card.innerHTML = `
    <div class="server-heading">
      <div class="server-title">
        <span class="server-index">${String(serverIndex + 1).padStart(2, "0")}</span>
        <span class="server-name-preview"></span>
      </div>
      <button class="button button-danger button-small remove-server" type="button">删除</button>
    </div>
    <div class="server-fields">
      <label class="field">
        <span class="field-label">服务器名称</span>
        <span class="field-hint">例如 主服务器、对抗服</span>
        <input type="text" data-field="name" autocomplete="off" placeholder="服务器名称" />
      </label>
      <label class="field">
        <span class="field-label">连接地址</span>
        <span class="field-hint">不填写端口时默认使用 27015</span>
        <input type="text" data-field="address" autocomplete="off" placeholder="127.0.0.1:27015" />
      </label>
      <label class="field">
        <span class="field-label">黑盒语音频道 ID</span>
        <span class="field-hint">服务器对应的语音频道，可留空</span>
        <input type="text" data-field="hh_channel_id" autocomplete="off" placeholder="Channel ID" />
      </label>
      <label class="field">
        <span class="field-label">RCON 密码</span>
        <span class="field-hint">用于设置和重启指令，可留空</span>
        <span class="secret-control">
          <input type="password" data-field="rcon_password" autocomplete="new-password" placeholder="RCON password" />
          <button class="secret-toggle server-secret-toggle" type="button" aria-label="显示或隐藏 RCON 密码">显示</button>
        </span>
      </label>
    </div>
  `;

  const preview = card.querySelector(".server-name-preview");
  const fieldNames = ["name", "address", "hh_channel_id", "rcon_password"];
  for (const fieldName of fieldNames) {
    const input = card.querySelector(`input[data-field="${fieldName}"]`);
    input.value = server[fieldName] || "";
    input.dataset.path = `group_configs.${groupIndex}.servers.${serverIndex}.${fieldName}`;
    input.addEventListener("input", () => {
      server[fieldName] = input.value;
      if (fieldName === "name") {
        preview.textContent = input.value || "未命名服务器";
      }
      markDirty();
    });
  }
  preview.textContent = server.name || "未命名服务器";

  card.querySelector(".server-secret-toggle").addEventListener("click", (event) => {
    const input = card.querySelector('input[data-field="rcon_password"]');
    const showing = input.type === "text";
    input.type = showing ? "password" : "text";
    event.currentTarget.textContent = showing ? "显示" : "隐藏";
  });
  card.querySelector(".remove-server").addEventListener("click", () => {
    removeServer(groupIndex, serverIndex);
  });
  return card;
}

function validateConfig() {
  const errors = [];
  const paths = [];

  function add(message, path = null) {
    errors.push(message);
    if (path) paths.push(path);
  }

  for (const [value, label, path] of [
    [state.connectBaseUrl, "一键连接基础 URL", "connectBaseUrl"],
    [state.mapNameUrl, "地图名称 API URL", "mapNameUrl"],
  ]) {
    if (!value.trim()) continue;
    try {
      const url = new URL(value);
      if (!['http:', 'https:'].includes(url.protocol)) throw new Error("protocol");
    } catch {
      add(`${label}必须是有效的 HTTP/HTTPS URL`, path);
    }
  }

  const groupIds = new Set();
  state.group_configs.forEach((group, groupIndex) => {
    const groupPath = `group_configs.${groupIndex}.group_id`;
    const groupId = group.group_id.trim();
    if (!groupId) {
      add(`第 ${groupIndex + 1} 个群组缺少群组 ID`, groupPath);
    } else if (/\s/.test(groupId)) {
      add(`群组 ID ${groupId} 不能包含空格`, groupPath);
    } else if (groupIds.has(groupId)) {
      add(`群组 ID ${groupId} 重复`, groupPath);
    }
    groupIds.add(groupId);

    const serverNames = new Set();
    group.servers.forEach((server, serverIndex) => {
      const prefix = `group_configs.${groupIndex}.servers.${serverIndex}`;
      const name = server.name.trim();
      const nameKey = name.replace(/\s+/g, "");
      if (!name) {
        add(`群组 ${groupId || groupIndex + 1} 的第 ${serverIndex + 1} 台服务器缺少名称`, `${prefix}.name`);
      } else if (serverNames.has(nameKey)) {
        add(`群组 ${groupId || groupIndex + 1} 中的服务器名称 ${name} 重复`, `${prefix}.name`);
      }
      serverNames.add(nameKey);

      const address = server.address.trim();
      if (!address) {
        add(`服务器 ${name || serverIndex + 1} 缺少连接地址`, `${prefix}.address`);
      } else if (!isValidServerAddress(address)) {
        add(`服务器 ${name || serverIndex + 1} 的地址格式应为 host 或 host:port`, `${prefix}.address`);
      }
    });
  });

  document.querySelectorAll("[data-path]").forEach((input) => {
    input.toggleAttribute("aria-invalid", paths.includes(input.dataset.path));
  });
  return errors;
}

function isValidServerAddress(address) {
  if (/\s/.test(address) || (address.match(/:/g) || []).length > 1) return false;
  if (!address.includes(":")) return address.length > 0;
  const [host, portText] = address.split(":");
  if (!host || !/^\d+$/.test(portText)) return false;
  const port = Number(portText);
  return port >= 1 && port <= 65535;
}

function requestConfirmation(message, acceptLabel = "确认") {
  if (confirmResolver) closeConfirmation(false);
  elements.confirmMessage.textContent = message;
  elements.confirmAccept.textContent = acceptLabel;
  elements.confirmLayer.hidden = false;
  elements.confirmCancel.focus();
  return new Promise((resolve) => {
    confirmResolver = resolve;
  });
}

function closeConfirmation(accepted) {
  if (!confirmResolver) return;
  const resolve = confirmResolver;
  confirmResolver = null;
  elements.confirmLayer.hidden = true;
  resolve(accepted);
}

async function loadConfig(initialLoad) {
  if (!initialLoad && isDirty()) {
    const confirmed = await requestConfirmation(
      "重新载入会丢弃当前未保存的修改，是否继续？",
      "放弃修改并载入",
    );
    if (!confirmed) return;
  }

  setBusy(true, "正在读取 config.json…");
  hideAlert();
  let failed = false;
  try {
    const result = await bridge.apiGet("config");
    state = normalizeConfig(result.config);
    revision = result.revision || "";
    baseline = snapshot(state);
    loaded = true;
    openGroups = new Set(state.group_configs.length <= 2 ? state.group_configs.map((_, index) => index) : [0]);
    renderGlobalControls();
    renderGroups();
    refreshStatus();
    if (!initialLoad) showToast("已从 config.json 重新载入");
  } catch (error) {
    failed = true;
    loaded = false;
    showAlert(error?.message || "读取配置失败");
    showToast("读取配置失败", "error");
  } finally {
    setBusy(false);
    refreshStatus(failed ? "error" : null);
  }
}

async function saveConfig() {
  if (!loaded) return;
  hideAlert();
  const errors = validateConfig();
  if (errors.length > 0) {
    refreshStatus("error");
    showAlert(errors);
    showToast("配置中仍有需要处理的问题", "error");
    document.querySelector('[aria-invalid="true"]')?.focus();
    return;
  }

  setBusy(true, "正在保存 config.json…");
  let failed = false;
  try {
    const result = await bridge.apiPost("config", {
      config: state,
      revision,
    });
    state = normalizeConfig(result.config || state);
    revision = result.revision || revision;
    baseline = snapshot(state);
    renderGlobalControls();
    renderGroups();
    refreshStatus();
    showToast("配置已保存并立即生效");
  } catch (error) {
    failed = true;
    showAlert(error?.message || "保存配置失败");
    showToast("保存失败，请检查配置", "error");
  } finally {
    setBusy(false);
    refreshStatus(failed ? "error" : null);
  }
}

async function initialize() {
  bindGlobalControls();
  if (!bridge) {
    setBusy(false);
    refreshStatus("error");
    showAlert("未检测到 AstrBot Plugin Page Bridge，请从 AstrBot 插件详情页打开此页面。");
    return;
  }

  try {
    const context = await bridge.ready();
    setTheme(context);
    bridge.onContext(setTheme);
    await loadConfig(true);
  } catch (error) {
    setBusy(false);
    refreshStatus("error");
    showAlert(error?.message || "页面初始化失败");
  }
}

window.addEventListener("beforeunload", (event) => {
  if (!isDirty()) return;
  event.preventDefault();
  event.returnValue = "";
});

initialize();
