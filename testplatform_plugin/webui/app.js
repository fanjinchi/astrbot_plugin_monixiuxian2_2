/* 修仙插件网页测试平台 - 前端逻辑（原生 JS，无构建链，无 CDN） */
"use strict";

const state = {
  conversations: [],
  players: [],
  currentConv: null,
  openedConv: null,          // 已拉取全量消息的会话 id
  messages: new Map(),       // convId -> [{id, direction, sender, text, created_at, annotation}]
  annotationTarget: null,    // 批注弹层对应的消息
  cases: [],
  currentCase: null,
  currentRun: null,
  ws: null,
};

const $ = (sel) => document.querySelector(sel);

/* ---------------- 工具 ---------------- */

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

/* ---------------- WebSocket ---------------- */

function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  state.ws = ws;
  ws.onopen = () => { $("#conn-status").textContent = "已连接"; $("#conn-status").className = "on"; };
  ws.onclose = () => {
    $("#conn-status").textContent = "已断开，重连中…";
    $("#conn-status").className = "off";
    setTimeout(connectWS, 3000);
  };
  ws.onmessage = (ev) => {
    let payload;
    try { payload = JSON.parse(ev.data); } catch { return; }
    handleWS(payload);
  };
}

function handleWS(payload) {
  switch (payload.type) {
    case "snapshot":
      state.conversations = payload.conversations || [];
      state.players = payload.players || [];
      renderConversations();
      break;
    case "conversations":
      refreshConversations();
      break;
    case "message":
      appendMessage(payload.conversation_id, payload.message, true);
      break;
    case "annotation":
      refreshAnnotation(payload.message_id);
      break;
    case "case_runs":
      refreshCaseRuns(payload.case_name);
      break;
  }
}

async function refreshConversations() {
  const data = await api("/api/conversations");
  state.conversations = data.conversations || [];
  renderConversations();
}

async function refreshAnnotation(messageId) {
  if (!state.currentConv) return;
  let ann = null;
  try { ann = (await api(`/api/messages/${messageId}/annotation`)).annotation; } catch { ann = null; }
  const list = state.messages.get(state.currentConv.id) || [];
  const msg = list.find((m) => m.id === messageId);
  if (msg) {
    msg.annotation = ann;
    renderMessages();
  }
}

/* ---------------- 会话 ---------------- */

function renderConversations() {
  const ul = $("#conversations");
  ul.innerHTML = "";
  const convs = [...state.conversations].sort((a, b) => (a.archived === b.archived ? 0 : a.archived ? 1 : -1));
  for (const conv of convs) {
    const li = el("li", "conv-item" + (state.currentConv && state.currentConv.id === conv.id ? " active" : ""));
    li.appendChild(el("div", "", conv.name || "(未命名)"));
    const sub = el("div", "sub");
    const kindText = conv.kind === "group" ? `群聊 ${conv.group_id}` : "私聊";
    sub.textContent = `${kindText} · ${conv.message_count} 条消息` + (conv.archived ? " · 已归档" : "");
    li.appendChild(sub);
    li.onclick = () => openConversation(conv);
    ul.appendChild(li);
  }
}

async function openConversation(conv) {
  state.currentConv = conv;
  document.querySelectorAll(".conv-item").forEach((n) => n.classList.remove("active"));
  $("#chat-header").textContent = `${conv.name}（${conv.kind === "group" ? "群聊 " + conv.group_id : "私聊"}${conv.archived ? " · 已归档" : ""}）`;
  if (!state.messages.has(conv.id) || state.openedConv !== conv.id) {
    const data = await api(`/api/conversations/${conv.id}/messages?limit=10000`);
    state.messages.set(conv.id, data.messages || []);
    state.openedConv = conv.id;
  }
  renderMessages();
  renderSenderSelect();
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify({ type: "open", conversation_id: conv.id }));
  }
}

function renderSenderSelect() {
  const sel = $("#sender-select");
  sel.innerHTML = "";
  const conv = state.currentConv;
  if (!conv) return;
  const players = state.players.filter((p) => p.conversation_id === conv.id);
  if (!players.length) {
    const opt = el("option", "", "(无玩家)");
    opt.value = "";
    sel.appendChild(opt);
    return;
  }
  for (const p of players) {
    const opt = el("option", "", `${p.nickname} (${p.user_id})`);
    opt.value = p.user_id;
    sel.appendChild(opt);
  }
}

function renderMessages() {
  const box = $("#messages");
  const conv = state.currentConv;
  if (!conv) { box.innerHTML = ""; return; }
  const msgs = state.messages.get(conv.id) || [];
  box.innerHTML = "";
  for (const m of msgs) {
    box.appendChild(buildMessageNode(conv, m));
  }
  box.scrollTop = box.scrollHeight;
}

function buildMessageNode(conv, m) {
  const wrap = el("div", "msg " + (m.direction === "in" ? "in" : "out"));
  const sender = el("div", "sender", (m.direction === "in" ? "玩家 " : "机器人 ") + (m.sender || "?"));
  wrap.appendChild(sender);
  const body = el("div", "", m.text || "");
  wrap.appendChild(body);
  wrap.appendChild(el("div", "time", fmtTime(m.created_at)));
  const btn = el("button", "annotate-btn", "批注");
  btn.onclick = () => openAnnotationModal(conv, m);
  wrap.appendChild(btn);
  if (m.annotation) {
    const ann = el("div", "annotation", m.annotation.text);
    const del = el("button", "ann-del", "✕");
    del.onclick = async () => {
      try { await api(`/api/messages/${m.id}/annotation`, { method: "DELETE" }); m.annotation = null; renderMessages(); }
      catch (e) { alert(e.message); }
    };
    ann.prepend(del);
    wrap.appendChild(ann);
  }
  return wrap;
}

function appendMessage(convId, msg, scroll) {
  if (!state.messages.has(convId)) state.messages.set(convId, []);
  const list = state.messages.get(convId);
  if (list.some((m) => m.id === msg.id)) return;
  list.push(msg);
  if (state.currentConv && state.currentConv.id === convId) {
    const node = buildMessageNode(state.currentConv, msg);
    $("#messages").appendChild(node);
    if (scroll) $("#messages").scrollTop = $("#messages").scrollHeight;
  }
  if (state.openedConv === convId) {
    refreshConversations(); // 更新计数
  }
}

/* ---------------- 批注 ---------------- */

function openAnnotationModal(conv, m) {
  state.annotationTarget = { conv, m };
  $("#annotation-msg-ref").textContent = `#${m.id} · ${m.direction === "in" ? "玩家" : "机器人"} ${m.sender || ""}：${(m.text || "").slice(0, 80)}`;
  $("#annotation-input").value = (m.annotation && m.annotation.text) || "";
  $("#annotation-modal").hidden = false;
  $("#annotation-input").focus();
}

async function saveAnnotation() {
  const target = state.annotationTarget;
  if (!target) return;
  const text = $("#annotation-input").value.trim();
  if (!text) { alert("批注不能为空"); return; }
  try {
    await api(`/api/messages/${target.m.id}/annotation`, { method: "POST", body: JSON.stringify({ text }) });
    $("#annotation-modal").hidden = true;
    const data = await api(`/api/messages/${target.m.id}/annotation`);
    target.m.annotation = data.annotation;
    renderMessages();
  } catch (e) { alert(e.message); }
}

/* ---------------- 用例 ---------------- */

async function refreshCases() {
  const data = await api("/api/cases");
  state.cases = data.cases || [];
  renderCases();
}

function renderCases() {
  const ul = $("#cases");
  ul.innerHTML = "";
  const filter = $("#case-filter").value.trim();
  for (const c of state.cases) {
    if (filter && !(c.tags || []).some((t) => t.includes(filter))) continue;
    const li = el("li", "case-item" + (state.currentCase && state.currentCase.name === c.name ? " active" : ""));
    li.appendChild(el("div", "", c.name));
    const sub = el("div", "sub", c.description || "");
    li.appendChild(sub);
    const tagRow = el("div", "tag-row");
    for (const t of (c.tags || [])) tagRow.appendChild(el("span", "badge tag", t));
    li.appendChild(tagRow);
    li.onclick = () => openCase(c);
    ul.appendChild(li);
  }
}

async function openCase(c) {
  state.currentCase = c;
  document.querySelectorAll(".case-item").forEach((n) => n.classList.remove("active"));
  $("#case-detail-empty").hidden = true;
  $("#case-detail").hidden = false;
  $("#case-name").textContent = c.name;
  $("#case-desc").textContent = c.description || "";
  const meta = [`场景: ${c.scenario || "-"}`, `会话: ${c.conversation && c.conversation.kind === "group" ? "群聊 " + (c.conversation.group_id || "") : "私聊"}`, `${(c.steps || []).length} 步`, c.conversation && c.conversation.pin_players ? "固定玩家" : "独立玩家"];
  $("#case-meta").textContent = meta.join(" · ");
  await refreshCaseRuns(c.name);
}

async function refreshCaseRuns(caseName) {
  if (!state.currentCase || state.currentCase.name !== caseName) return;
  const data = await api(`/api/cases/${caseName}/runs`);
  const ul = $("#runs-list");
  ul.innerHTML = "";
  for (const r of (data.runs || [])) {
    const li = el("li", "run-item" + (state.currentRun && state.currentRun.id === r.id ? " active" : ""));
    li.appendChild(el("span", "status status-" + r.status, `#${r.run_index} ${r.status === "passed" ? "通过" : r.status === "running" ? "运行中" : r.status === "failed" ? "失败" : "错误"}`));
    li.appendChild(el("span", "sub", ` ${fmtTime(r.created_at)} · ${r.duration_ms}ms`));
    li.onclick = () => openRun(r.id);
    ul.appendChild(li);
  }
}

async function openRun(runId) {
  state.currentRun = { id: runId };
  document.querySelectorAll(".run-item").forEach((n) => n.classList.remove("active"));
  const run = await api(`/api/runs/${runId}`);
  const detail = $("#run-detail");
  detail.innerHTML = "";
  detail.appendChild(el("h3", "", `运行 #${run.run_index} · ${run.status === "passed" ? "通过" : run.status === "failed" ? "失败" : run.status === "error" ? "错误" : "运行中"}`));
  for (let i = 0; i < (run.steps_result || []).length; i++) {
    const s = run.steps_result[i];
    const step = el("div", "step");
    const head = el("div", "head");
    const ok = s.ok ? el("span", "status-passed", "✓") : el("span", "status-failed", "✗");
    head.appendChild(ok);
    head.appendChild(el("span", "", `步骤 ${i + 1}: ${s.type}`));
    head.appendChild(el("span", "sub", ` ${s.duration_ms || 0}ms`));
    step.appendChild(head);
    if (s.note) step.appendChild(el("div", "note", `说明: ${s.note}`));
    if (s.actual !== undefined) step.appendChild(el("div", "actual", `实际回复: ${s.actual}`));
    if (!s.ok) step.appendChild(el("div", "actual", `期望: ${s.expected}`));
    detail.appendChild(step);
  }
  if (run.conversation_id) {
    const openBtn = el("button", "primary", "打开该次运行的会话");
    openBtn.onclick = async () => {
      $("#tabs .tab[data-tab=chat]").click();
      const data = await api("/api/conversations");
      const conv = (data.conversations || []).find((c) => c.id === run.conversation_id);
      if (conv) await openConversation(conv);
    };
    detail.appendChild(openBtn);
  }
  const tl = el("div", "timeline");
  tl.appendChild(el("div", "sub", `轨迹快照（${(run.run_messages || []).length} 条消息）`));
  for (const m of (run.run_messages || [])) {
    const line = el("div", "tl-msg", "");
    const who = el("span", "who", m.direction === "in" ? `[玩家 ${m.sender}] ` : "[机器人] ");
    line.appendChild(who);
    line.appendChild(document.createTextNode(m.text || ""));
    tl.appendChild(line);
  }
  detail.appendChild(tl);
  state.currentRun = { id: runId };
  refreshCaseRuns(run.case_name || state.currentCase.name);
}

/* ---------------- 用例 JSON 编辑器 ---------------- */

function openCaseEditor(caseObj, isNew) {
  $("#case-editor-title").textContent = isNew ? "新建用例" : `编辑 ${caseObj.name}`;
  $("#case-editor-input").value = JSON.stringify(caseObj, null, 2);
  $("#case-editor-modal").hidden = false;
  state.editingCase = { caseObj, isNew };
}

async function saveCaseEditor() {
  const { caseObj, isNew } = state.editingCase || {};
  let data;
  try { data = JSON.parse($("#case-editor-input").value); }
  catch (e) { alert(`JSON 解析失败: ${e.message}`); return; }
  if (!data.name) { alert("name 必填"); return; }
  try {
    if (isNew) {
      await api("/api/cases", { method: "POST", body: JSON.stringify({ name: data.name, content: data }) });
    } else {
      await api(`/api/cases/${encodeURIComponent(caseObj.name)}`, { method: "PUT", body: JSON.stringify({ content: data }) });
    }
    $("#case-editor-modal").hidden = true;
    await refreshCases();
    await openCase(data);
  } catch (e) { alert(e.message); }
}

/* ---------------- 事件绑定 ---------------- */

function bindEvents() {
  $("#tabs").addEventListener("click", (ev) => {
    const tab = ev.target.closest(".tab");
    if (!tab) return;
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    $("#" + tab.dataset.tab + "-panel").classList.add("active");
    if (tab.dataset.tab === "cases") refreshCases();
  });

  $("#new-conv").onclick = async () => {
    const name = prompt("新会话名称（留空用默认）");
    if (name === null) return;
    try {
      await api("/api/conversations", { method: "POST", body: JSON.stringify({ kind: "private", name: name || undefined }) });
      await refreshConversations();
    } catch (e) { alert(e.message); }
  };

  $("#send-form").onsubmit = async (ev) => {
    ev.preventDefault();
    if (!state.currentConv) return;
    const sender = $("#sender-select").value;
    const text = $("#text-input").value.trim();
    if (!sender) { alert("先为该会话添加玩家（无玩家时无法发送）"); return; }
    if (!text) return;
    $("#text-input").value = "";
    try {
      const msg = await api(`/api/conversations/${state.currentConv.id}/messages`, {
        method: "POST", body: JSON.stringify({ sender, text }),
      });
      appendMessage(state.currentConv.id, msg, true);
    } catch (e) { alert(e.message); }
  };

  $("#annotation-save").onclick = saveAnnotation;
  $("#annotation-cancel").onclick = () => { $("#annotation-modal").hidden = true; };
  $("#annotation-modal").addEventListener("click", (ev) => { if (ev.target === $("#annotation-modal")) $("#annotation-modal").hidden = true; });

  $("#new-case").onclick = () => {
    const name = prompt("用例名称（英文 kebab-case，如 cultivate-basic-flow）");
    if (!name) return;
    openCaseEditor({ name, description: "", scenario: "", tags: [], conversation: { kind: "private" }, steps: [{ type: "send", player: "player1", text: "", note: "" }] }, true);
  };
  $("#case-edit-btn").onclick = () => state.currentCase && openCaseEditor(state.currentCase, false);
  $("#case-editor-save").onclick = saveCaseEditor;
  $("#case-editor-cancel").onclick = () => { $("#case-editor-modal").hidden = true; };
  $("#case-editor-modal").addEventListener("click", (ev) => { if (ev.target === $("#case-editor-modal")) $("#case-editor-modal").hidden = true; });

  $("#case-run-btn").onclick = async () => {
    if (!state.currentCase) return;
    $("#case-run-btn").disabled = true;
    try {
      const run = await api(`/api/cases/${encodeURIComponent(state.currentCase.name)}/runs`, { method: "POST" });
      alert(`运行完成: ${run.status === "passed" ? "通过 ✓" : run.status === "failed" ? "失败 ✗（见运行记录）" : "错误"}`);
      await refreshCaseRuns(state.currentCase.name);
      await openRun(run.id);
    } catch (e) { alert(e.message); }
    $("#case-run-btn").disabled = false;
  };

  $("#case-delete-btn").onclick = async () => {
    if (!state.currentCase) return;
    if (!confirm(`删除用例 ${state.currentCase.name}？`)) return;
    try {
      await api(`/api/cases/${encodeURIComponent(state.currentCase.name)}`, { method: "DELETE" });
      state.currentCase = null;
      $("#case-detail").hidden = true;
      $("#case-detail-empty").hidden = false;
      await refreshCases();
    } catch (e) { alert(e.message); }
  };

  $("#case-filter").oninput = renderCases;
}

/* ---------------- 启动 ---------------- */

async function init() {
  bindEvents();
  try {
    await refreshConversations();
    const players = await api("/api/players");
    state.players = players.players || [];
    renderSenderSelect();
    if (state.conversations.length) await openConversation(state.conversations[0]);
  } catch (e) {
    alert("初始化失败: " + e.message);
  }
  connectWS();
}

init();
