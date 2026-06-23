"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
let ready = false;

const api = () => window.pywebview.api;

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove("show"), 1800);
}

function llmLabel(status) {
  return { idle: "대기", downloading: "준비 중…", ready: "준비됨", error: "오류" }[status] || status;
}

// ---- 상태 폴링 -------------------------------------------------------
async function refresh() {
  if (!ready) return;
  let s;
  try { s = await api().get_status(); } catch (e) { return; }

  const pill = $("#status-pill"), dot = $("#dot");
  let label, cls;
  if (s.paused) { label = "일시정지"; cls = "paused"; }
  else if (s.recording && s.within_schedule) { label = "녹음 중"; cls = "rec"; }
  else if (s.recording) { label = "대기 (시간대 밖)"; cls = "idle"; }
  else { label = "정지"; cls = "off"; }
  pill.textContent = label; pill.className = "pill " + cls;
  dot.className = "dot " + (cls === "off" ? "" : cls);

  $("#schedule").textContent = s.within_schedule ? "허용 시간대" : "허용 시간대 아님";
  let llm = "LLM: " + llmLabel(s.llm_status);
  if (s.llm_status === "error" && s.llm_error) llm += " (" + s.llm_error.slice(0, 40) + "…)";
  $("#llm").textContent = llm;

  const p = s.progress || {};
  const active = (p.total > 0) || (p.phase && p.phase !== "idle");
  $("#progress-wrap").style.display = active ? "flex" : "none";
  if (active) {
    $("#progress-phase").textContent = p.phase || "";
    let pct = p.total ? Math.round((p.done / p.total) * 100) : 0;
    if (p.phase && (p.phase.startsWith("완료") || p.phase.startsWith("오류"))) pct = 100;
    $("#progress-bar").style.width = pct + "%";
  }

  $("#btn-start").disabled = s.recording;
  $("#btn-stop").disabled = !s.recording;
  $("#btn-process").disabled = s.batch_running;
}

// ---- 리포트 ----------------------------------------------------------
async function loadReports() {
  const dates = await api().list_reports();
  const ul = $("#report-list");
  ul.innerHTML = "";
  if (!dates.length) { ul.innerHTML = '<li class="muted">리포트 없음</li>'; return; }
  dates.forEach((d) => {
    const li = document.createElement("li");
    li.textContent = d;
    li.onclick = () => viewReport(d, li);
    ul.appendChild(li);
  });
}

async function viewReport(date, li) {
  $$("#report-list li").forEach((x) => x.classList.remove("active"));
  if (li) li.classList.add("active");
  const md = await api().get_report(date);
  $("#report-view").innerHTML = md ? renderMarkdown(md) : '<p class="muted">내용이 없습니다.</p>';
}

function escapeHtml(t) {
  return t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function inlineMd(t) {
  return t.replace(/`([^`]+)`/g, "<code>$1</code>");
}
function renderMarkdown(md) {
  const lines = md.split("\n");
  let html = "", inList = false;
  const closeList = () => { if (inList) { html += "</ul>"; inList = false; } };
  for (const raw of lines) {
    const line = raw.replace(/\s+$/, "");
    if (/^### /.test(line)) { closeList(); html += "<h3>" + escapeHtml(line.slice(4)) + "</h3>"; }
    else if (/^## /.test(line)) { closeList(); html += "<h2>" + escapeHtml(line.slice(3)) + "</h2>"; }
    else if (/^# /.test(line)) { closeList(); html += "<h1>" + escapeHtml(line.slice(2)) + "</h1>"; }
    else if (/^> /.test(line)) { closeList(); html += "<blockquote>" + inlineMd(escapeHtml(line.slice(2))) + "</blockquote>"; }
    else if (/^- /.test(line)) { if (!inList) { html += "<ul>"; inList = true; } html += "<li>" + inlineMd(escapeHtml(line.slice(2))) + "</li>"; }
    else if (line.trim() === "") { closeList(); }
    else { closeList(); html += "<p>" + inlineMd(escapeHtml(line)) + "</p>"; }
  }
  closeList();
  return html;
}

// ---- 설정 ------------------------------------------------------------
async function loadConfig() {
  $("#config-text").value = await api().get_config_text();
}
async function saveConfig() {
  const res = await api().save_config_text($("#config-text").value);
  if (res && res.ok) { toast("설정을 저장했습니다."); $("#config-msg").textContent = ""; }
  else { $("#config-msg").textContent = "저장 실패: " + (res && res.msg ? res.msg : ""); }
}

// ---- 탭 --------------------------------------------------------------
function switchTab(name) {
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
  $$(".panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + name));
}

// ---- 바인딩 ----------------------------------------------------------
function bind() {
  $("#btn-start").onclick = () => api().start_recording().then(refresh);
  $("#btn-stop").onclick = () => api().stop_recording().then(refresh);
  $("#btn-resume").onclick = () => api().resume().then(() => { toast("일시정지 해제"); refresh(); });
  $$("[data-pause]").forEach((b) =>
    b.onclick = () => api().pause(+b.dataset.pause).then(() => { toast(b.dataset.pause + "분 일시정지"); refresh(); })
  );
  $("#btn-process").onclick = () => api().process_now().then(() => { toast("일괄 처리 시작"); refresh(); });
  $("#btn-preload").onclick = () => api().preload_llm().then(() => toast("모델을 백그라운드에서 준비합니다."));
  $("#btn-save-config").onclick = saveConfig;
  $$(".tab").forEach((t) => t.onclick = () => switchTab(t.dataset.tab));
}

// 일괄 처리가 끝나면 리포트 목록 갱신
let lastBatchRunning = false;
async function watchBatch() {
  if (!ready) return;
  try {
    const s = await api().get_status();
    if (lastBatchRunning && !s.batch_running) { loadReports(); }
    lastBatchRunning = s.batch_running;
  } catch (e) {}
}

window.addEventListener("pywebviewready", async () => {
  ready = true;
  bind();
  await refresh();
  await loadReports();
  await loadConfig();
  setInterval(refresh, 1500);
  setInterval(watchBatch, 2000);
});
