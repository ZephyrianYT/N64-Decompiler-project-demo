// n64lab web UI: talks to the JSON API in n64lab/webui/server.py.
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));
const state = { project: null, info: null, tools: null, functions: [], current: null, step: 1 };

// ---------------------------------------------------------------- helpers

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const data = await res.json().catch(() => ({ error: res.statusText }));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });

function esc(text) {
  return String(text).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

let toastTimer;
function toast(message, error = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (error ? " error" : "");
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.hidden = true), error ? 8000 : 3000);
}

async function busy(button, label, work) {
  const original = button.innerHTML;
  button.disabled = true;
  button.innerHTML = `<span class="spinner"></span>${label}`;
  try {
    return await work();
  } catch (e) {
    toast(e.message, true);
  } finally {
    button.disabled = false;
    button.innerHTML = original;
  }
}

// Poll a background job (example builds, recompiles) until it finishes.
async function waitForJob(job, logEl) {
  while (true) {
    const j = await api(`/api/jobs/${job.id}`);
    if (logEl) {
      logEl.hidden = false;
      logEl.textContent = j.log.join("\n") + (j.state === "running" ? "\n…" : "");
      logEl.scrollTop = logEl.scrollHeight;
    }
    if (j.state === "done") return j.result;
    if (j.state === "failed") throw new Error(j.log[j.log.length - 1] || "failed");
    await new Promise((r) => setTimeout(r, 700));
  }
}

// ---------------------------------------------------------------- navigation

function showTab(name) {
  $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $$(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "projects") loadProjects();
  if (name === "explorer") loadExplorer();
  try { localStorage.setItem("n64lab.tab", name); } catch (e) { /* storage may be blocked */ }
}

function goStep(n) {
  if (n > 1 && !state.project) return toast("Choose a ROM first.");
  state.step = n;
  $$("#stepper li").forEach((li) => {
    const s = Number(li.dataset.step);
    li.classList.toggle("active", s === n);
    li.classList.toggle("done", s < n);
    li.classList.toggle("locked", s > 1 && !state.project);
  });
  $$(".step").forEach((el) => el.classList.toggle("active", el.id === `step-${n}`));
  if (n === 3) loadAnalysis();
  if (n === 5) updateDownloads();
  window.scrollTo(0, 0);
}

async function openProject(id, step = 2) {
  state.project = id;
  state.functions = [];
  state.current = null;
  state.info = await api(`/api/projects/${id}`);
  try { localStorage.setItem("n64lab.project", id); } catch (e) { /* ignore */ }
  const p = state.info.project;
  $("#current-project").innerHTML = `<strong>${esc(p.name)}</strong> <span class="muted">${esc(state.info.title || "")}</span>`;
  renderInfo();
  $("#to-run").disabled = !Object.keys(state.info.built || {}).length;
  showTab("wizard");
  goStep(step);
}

// ---------------------------------------------------------------- step 1

async function loadTools() {
  state.tools = await api("/api/tools");
  const box = $("#examples");
  if (!state.tools.homebrew) {
    $("#examples-note").innerHTML = "Building examples needs <code>clang</code> and <code>ld.lld</code> " +
      "(LLVM). Install them, or use the Docker image, which has everything.";
  }
  box.innerHTML = "";
  for (const ex of state.tools.examples) {
    const b = document.createElement("button");
    b.className = "example";
    b.disabled = !state.tools.homebrew;
    const blurb = ex.description.charAt(0).toUpperCase() + ex.description.slice(1);
    b.innerHTML = `<strong>${esc(ex.name)}</strong><span class="muted small">${esc(blurb)}</span>`;
    b.onclick = () => busy(b, "Building with clang…", async () => {
      const job = await post("/api/examples", { name: ex.name });
      const result = await waitForJob(job);
      toast(`Built ${ex.name}.z64`);
      await openProject(result.project);
    });
    box.appendChild(b);
  }
  const native = state.tools.native_compiler, win = state.tools.windows_compiler;
  $("#compiler-note").innerHTML =
    `C compiler for this computer: <code>${esc(native || "none found")}</code>. ` +
    `For Windows: <code>${esc(win || (state.tools.platform === "win32" ? native || "none" : "none found (needs MinGW)"))}</code>.`;
  if (state.tools.platform === "win32") {
    $("#build-target option[value=windows]").remove();
    $("#build-target option[value=native]").textContent = "Windows .exe (this computer)";
  }
}

async function uploadRom(file) {
  if (!file) return;
  const symFile = $("#sym-file").files[0];
  const drop = $("#drop");
  drop.classList.add("over");
  try {
    const info = await api("/api/upload", {
      method: "POST", body: file, headers: { "X-Filename": encodeURIComponent(file.name) },
    });
    if (symFile) {
      await api(`/api/projects/${info.project.id}/config`, {
        method: "PUT", body: JSON.stringify({ config: {}, symbols: await symFile.text() }),
      });
    }
    toast(`Opened ${file.name}`);
    await openProject(info.project.id);
  } catch (e) {
    toast(e.message, true);
  } finally {
    drop.classList.remove("over");
    $("#rom-file").value = "";
  }
}

function projectRow(p, withDelete) {
  const row = document.createElement("div");
  row.className = "project-row";
  const when = new Date(p.created * 1000).toLocaleString();
  row.innerHTML = `<div class="grow"><strong>${esc(p.name)}</strong> <span class="muted">${esc(p.title || "")}</span>
    <div class="muted small">${esc(when)}${p.builds ? " · built: " + esc(Object.keys(p.builds).join(", ")) : ""}</div></div>`;
  const open = document.createElement("button");
  open.className = "secondary";
  open.textContent = "Open";
  open.onclick = () => openProject(p.id);
  row.appendChild(open);
  if (withDelete) {
    const del = document.createElement("button");
    del.className = "link";
    del.textContent = "Delete";
    del.onclick = async () => {
      if (!confirm(`Delete ${p.name} and everything generated from it?`)) return;
      await api(`/api/projects/${p.id}`, { method: "DELETE" });
      if (state.project === p.id) location.reload();
      loadProjects();
    };
    row.appendChild(del);
  }
  return row;
}

async function loadRecent() {
  const { projects } = await api("/api/projects");
  $("#recent-card").hidden = !projects.length;
  const box = $("#recent");
  box.innerHTML = "";
  projects.slice(0, 5).forEach((p) => box.appendChild(projectRow(p, false)));
}

async function loadProjects() {
  const { projects } = await api("/api/projects");
  const box = $("#project-list");
  box.innerHTML = projects.length ? "" : '<p class="muted">No projects yet. Use the Wizard to open a ROM.</p>';
  projects.forEach((p) => box.appendChild(projectRow(p, true)));
}

// ---------------------------------------------------------------- step 2

function renderInfo() {
  const i = state.info;
  const entryNote = i.entry !== i.header_entry
    ? `The header says ${i.header_entry}, but CIC-${i.cic} loads the game lower.` : "Where the game's code begins.";
  const rows = [
    ["Title", esc(i.title || "(blank)"), "Up to 20 characters, stored at 0x20 in the header."],
    ["Game code", `<code>${esc(i.game_code)}</code>`, "Media type, two-letter game ID, region: NSME = cartridge, Super Mario 64, USA."],
    ["Entry point", `<code>${i.entry}</code>`, entryNote],
    ["Boot chip (CIC)", esc(i.cic), i.cic === "unknown"
      ? "The boot code doesn't match a known CIC. Normal for homebrew built here, which has an empty boot block."
      : "The lockout chip this cartridge was made for, identified from its boot code."],
    ["Checksum", i.checksum_ok ? '<span class="ok">OK</span>' : '<span class="bad">mismatch</span>',
      "The console checks these two header words at boot; a mismatch means a modified ROM."],
    ["File", `${(i.size / 1048576).toFixed(1)} MiB, .${esc(i.format)}`, i.format === "z64"
      ? "Big-endian, the console's own byte order." : "Converted to big-endian (.z64) when it was opened."],
    ["Symbols", i.has_symbols ? "yes" : "no", "With a symbol file, functions get their real names."],
  ];
  $("#info-table").innerHTML = rows.map(([k, v, note]) =>
    `<tr><th>${k}</th><td>${v}<span class="muted">${esc(note)}</span></td></tr>`).join("");
}

// ---------------------------------------------------------------- step 3

async function loadAnalysis(data) {
  try {
    data = data || await api(`/api/projects/${state.project}/functions`);
  } catch (e) {
    $("#analysis-summary").textContent = e.message;
    return;
  }
  state.functions = data.functions;
  $("#analysis-summary").textContent = "Found " + data.summary;
  const warned = data.functions.filter((f) => f.warnings.length);
  const notes = data.notes.map((n) => `<div class="warning">${esc(n)}</div>`);
  const warnings = warned.slice(0, 8).map((f) =>
    `<div class="warning"><strong>${esc(f.name)}</strong>: ${esc(f.warnings[0])}</div>`);
  if (warned.length > 8) warnings.push(`<div class="muted small">…and ${warned.length - 8} more in the Explorer.</div>`);
  $("#analysis-warnings").innerHTML = notes.concat(warnings).join("") ||
    '<p class="ok">No warnings: every jump was resolved.</p>';
  $("#config-text").value = JSON.stringify(data.config, null, 2);
  $("#symbols-text").value = data.symbols;
}

async function saveConfig() {
  let config;
  try {
    config = JSON.parse($("#config-text").value || "{}");
  } catch (e) {
    return toast("The config isn't valid JSON: " + e.message, true);
  }
  await busy($("#save-config"), "Analyzing…", async () => {
    const data = await api(`/api/projects/${state.project}/config`, {
      method: "PUT", body: JSON.stringify({ config, symbols: $("#symbols-text").value }),
    });
    await loadAnalysis(data);
    $("#config-status").textContent = "Saved.";
  });
}

// ---------------------------------------------------------------- step 4

async function build() {
  const log = $("#build-log");
  log.textContent = "";
  await busy($("#build-btn"), "Building…", async () => {
    const job = await post(`/api/projects/${state.project}/build`, {
      target: $("#build-target").value, opt: $("#build-opt").value, debug_calls: $("#build-debug").checked,
    });
    await waitForJob(job, log);
    state.info = await api(`/api/projects/${state.project}`);
    $("#to-run").disabled = false;
    toast("Build finished");
  });
}

// ---------------------------------------------------------------- step 5

function updateDownloads() {
  const built = (state.info && state.info.built) || {};
  const exe = $("#dl-exe");
  const name = built.windows || built.native;
  exe.textContent = name ? `Download ${name}` : "Program (build first)";
  exe.classList.toggle("disabled", !name);
  exe.href = `/api/projects/${state.project}/download/exe`;
  $("#dl-project").href = `/api/projects/${state.project}/download/project`;
  $("#dl-project").classList.toggle("disabled", !name);
  $("#run-btn").disabled = !built.native;
  $("#run-note").textContent = built.native ? "" :
    "Build for \"this computer\" in step 4 to run it here.";
}

async function run() {
  await busy($("#run-btn"), "Running…", async () => {
    const r = await post(`/api/projects/${state.project}/run`, { seconds: Number($("#run-seconds").value) });
    $("#run-result").hidden = false;
    $("#run-stdout").textContent = r.stdout || "(nothing printed)";
    $("#run-log").textContent = r.log;
    $("#run-shot").innerHTML = r.screenshot
      ? `<img alt="Last frame" src="data:image/png;base64,${r.screenshot}">`
      : '<span class="muted">The program never set up a framebuffer.</span>';
  });
}

// ---------------------------------------------------------------- explorer

async function loadExplorer() {
  $("#explorer-empty").hidden = !!state.project;
  $("#explorer").hidden = !state.project;
  if (!state.project) return;
  if (!state.functions.length) {
    const data = await api(`/api/projects/${state.project}/functions`).catch((e) => toast(e.message, true));
    if (!data) return;
    state.functions = data.functions;
  }
  renderFunctionList();
  if (!state.current && state.functions.length) showFunction(state.functions[0].start);
}

function renderFunctionList() {
  const filter = $("#func-filter").value.toLowerCase();
  const list = $("#func-list");
  const shown = state.functions.filter((f) => !filter || f.name.toLowerCase().includes(filter) ||
    f.start.toLowerCase().includes(filter));
  $("#func-count").textContent = `${shown.length} of ${state.functions.length} functions`;
  list.innerHTML = "";
  for (const f of shown.slice(0, 2000)) {
    const li = document.createElement("li");
    li.dataset.addr = f.start;
    li.className = f.start === state.current ? "active" : "";
    li.title = `${f.insns} instructions. Found because: ${f.reason}`;
    li.innerHTML = `${esc(f.name)}${f.warnings.length ? ' <span class="w">⚠</span>' : ""}${f.stub ? " (stub)" : ""}
      <div class="addr">${f.start} · ${f.insns} insns</div>`;
    li.onclick = () => showFunction(f.start);
    list.appendChild(li);
  }
}

const C_KEYWORDS = /\b(if|goto|return|switch|case|void|int|uint32_t|static)\b/g;

function highlightC(line, names) {
  const comment = line.indexOf("//");
  let code = comment >= 0 ? line.slice(0, comment) : line;
  const rest = comment >= 0 ? line.slice(comment) : "";
  code = esc(code)
    .replace(C_KEYWORDS, '<span class="kw">$1</span>')
    .replace(/\b(L_[0-9A-F]{8})\b/g, '<span class="lb">$1</span>')
    .replace(/\b((?:fn_\w+|func_[0-9A-F]{8}))(?=\(cpu\))/g, (m) =>
      names[m] ? `<span class="fn" data-goto="${names[m]}">${m}</span>` : m);
  return code + (rest ? `<span class="cm">${esc(rest)}</span>` : "");
}

async function showFunction(addr) {
  state.current = addr;
  $$("#func-list li").forEach((li) => li.classList.toggle("active", li.dataset.addr === addr));
  let f;
  try {
    f = await api(`/api/projects/${state.project}/functions/${addr}`);
  } catch (e) {
    return toast(e.message, true);
  }
  // Map C function names back to addresses so calls can be clicked.
  const names = {};
  for (const fn of state.functions) {
    names["func_" + fn.start.slice(2).toUpperCase()] = fn.start;
    names["fn_" + fn.name.replace(/[^A-Za-z0-9_]/g, "_")] = fn.start;
  }
  $("#func-head").innerHTML = `<h3>${esc(f.name)} <span class="muted small">${f.start}–${f.end}</span></h3>
    <div class="muted small">Found because: ${esc(f.reason)}</div>` +
    f.warnings.map((w) => `<div class="warning">${esc(w)}</div>`).join("");

  $("#asm").innerHTML = f.asm.map((a) => {
    const label = a.label ? `<div class="ln label">.L${a.addr}:</div>` : "";
    return `${label}<div class="ln${a.delay ? " delay" : ""}" data-a="${a.addr}"><span class="a">${a.addr}</span>  ${esc(a.text)}</div>`;
  }).join("");

  $("#csrc").innerHTML = f.c.split("\n").map((line) => {
    const m = line.match(/\/\/ ([0-9A-F]{8}):/);
    return `<div class="ln"${m ? ` data-a="${m[1]}"` : ""}>${highlightC(line, names) || " "}</div>`;
  }).join("");
}

function linkPanes(event) {
  const ln = event.target.closest(".ln[data-a]");
  $$(".code .ln.hl").forEach((el) => el.classList.remove("hl"));
  if (!ln) return;
  $$(`.code .ln[data-a="${ln.dataset.a}"]`).forEach((el) => el.classList.add("hl"));
}

function clickCode(event) {
  const target = event.target.closest("[data-goto]");
  if (target) return showFunction(target.dataset.goto);
  const ln = event.target.closest(".ln[data-a]");
  if (!ln) return;
  const other = ln.closest("#asm") ? "#csrc" : "#asm";
  const partner = document.querySelector(`${other} .ln[data-a="${ln.dataset.a}"]`);
  if (partner) partner.scrollIntoView({ block: "center", behavior: "smooth" });
}

async function trace() {
  await busy($("#trace-btn"), "Tracing…", async () => {
    const r = await post(`/api/projects/${state.project}/trace`, { steps: Number($("#trace-steps").value) });
    $("#trace-output").textContent = r.output ? "Program output:\n" + r.output : "(no output yet)";
    $("#trace-text").textContent = r.trace;
  });
}

// ---------------------------------------------------------------- wiring

function wire() {
  $$(".tabs button").forEach((b) => (b.onclick = () => showTab(b.dataset.tab)));
  $$("#stepper li").forEach((li) => (li.onclick = () => goStep(Number(li.dataset.step))));
  $$("[data-goto]").forEach((b) => { if (b.tagName === "BUTTON") b.onclick = () => goStep(Number(b.dataset.goto)); });
  $$(".subtabs button").forEach((b) => (b.onclick = () => {
    $$(".subtabs button").forEach((x) => x.classList.toggle("active", x === b));
    $("#view-code").hidden = b.dataset.view !== "code";
    $("#view-trace").hidden = b.dataset.view !== "trace";
  }));

  const drop = $("#drop");
  $("#rom-file").onchange = (e) => uploadRom(e.target.files[0]);
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); uploadRom(e.dataTransfer.files[0]); });

  $("#save-config").onclick = saveConfig;
  $("#open-explorer").onclick = () => showTab("explorer");
  $("#explore-btn").onclick = () => showTab("explorer");
  $("#build-btn").onclick = build;
  $("#run-btn").onclick = run;
  $("#trace-btn").onclick = trace;
  $("#func-filter").oninput = renderFunctionList;
  for (const pane of ["#asm", "#csrc"]) {
    $(pane).addEventListener("mouseover", linkPanes);
    $(pane).addEventListener("click", clickCode);
  }
}

async function start() {
  wire();
  goStep(1);
  try {
    await loadTools();
    await loadRecent();
  } catch (e) {
    toast("Can't reach the n64lab server: " + e.message, true);
  }
  let saved = null, tab = null;
  try {
    saved = localStorage.getItem("n64lab.project");
    tab = localStorage.getItem("n64lab.tab");
  } catch (e) { /* ignore */ }
  if (saved) {
    try {
      await openProject(saved, 2);
      if (tab && tab !== "wizard") showTab(tab);
    } catch (e) {
      try { localStorage.removeItem("n64lab.project"); } catch (e2) { /* ignore */ }
    }
  }
}

start();
