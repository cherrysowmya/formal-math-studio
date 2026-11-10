"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const source = $("source-code");
  const output = $("output-code");
  const roleLabels = {
    formal_initial: "Formal prover",
    formal_reviser: "Formal reviser",
    informal_generator: "Informal generator",
    informal_reviewer: "Informal reviewer",
    discussion: "Discussion partner",
    fresh_formal: "Fresh formal prover",
    verification: "Lean verification",
    retrieval: "LeanExplore",
    system: "Workspace",
  };
  const roleOrder = ["formal_initial", "formal_reviser", "informal_generator", "informal_reviewer", "discussion", "fresh_formal"];
  const terminalStatuses = new Set(["verified", "unverified", "failed", "cancelled"]);
  const state = { config: null, overrides: {}, activeId: null, polling: false, pollingFailures: 0, currentRun: null, eventKeys: new Set(), startedAt: null, downloadUrl: null, toastTimer: null, focusBeforeSettings: null };

  function escapeText(value) { return String(value ?? ""); }
  function countLines(value) { return value ? value.split("\n").length : 0; }
  function updateLines(editor, gutter) {
    const lines = Math.max(1, countLines(editor.value));
    gutter.textContent = Array.from({ length: lines }, (_, i) => i + 1).join("\n");
    gutter.scrollTop = editor.scrollTop;
  }
  function updateSource() {
    updateLines(source, $("source-lines"));
    $("source-meta").textContent = `${countLines(source.value).toLocaleString()} lines · ${source.value.length.toLocaleString()} characters`;
    $("run-agent").disabled = !state.config || !!state.activeId || !source.value.trim();
  }
  function updateOutput(code) {
    output.value = typeof code === "string" ? code : "";
    const present = !!output.value;
    $("output-empty").hidden = present;
    $("result-editor").hidden = !present;
    $("copy-output").disabled = !present;
    $("use-output").disabled = !present || !!state.activeId;
    $("output-meta").textContent = present ? `${countLines(output.value).toLocaleString()} lines · ${output.value.length.toLocaleString()} characters` : "No result yet";
    updateLines(output, $("output-lines"));
  }
  function showToast(message) {
    $("toast").textContent = message;
    $("toast").hidden = false;
    window.clearTimeout(state.toastTimer);
    state.toastTimer = window.setTimeout(() => { $("toast").hidden = true; }, 3500);
  }
  function showRunError(message) { $("run-error").textContent = message; $("run-error").hidden = !message; }
  function getFilename() {
    let name = $("filename").value.trim().replace(/[\\/]/g, "_") || "theorem.lean";
    if (!name.toLowerCase().endsWith(".lean")) name += ".lean";
    return name;
  }
  function outputFilename(name) { return name.replace(/\.lean$/i, "") + ".proved.lean"; }

  async function api(path, options = {}) {
    const sendsJSON = ["POST", "PUT", "PATCH"].includes(options.method);
    const response = await fetch(path, { cache: "no-store", ...options, ...(sendsJSON && !options.body ? { body: "{}" } : {}), headers: { ...(sendsJSON ? { "Content-Type": "application/json" } : {}), ...options.headers } });
    let data;
    try { data = await response.json(); } catch { throw new Error(`The local server returned an unreadable response (${response.status}).`); }
    if (!response.ok) {
      const detail = data.detail || data.error || data.message;
      const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((item) => item.msg || String(item)).join("; ") : `Request failed (${response.status}).`;
      throw new Error(message);
    }
    return data;
  }

  function setStatus(status, detail) {
    const labels = { ready: "Ready when you are", queued: "Run queued", running: "Agents are working", verified: "Proof verified by Lean", unverified: "Candidate produced · not verified", failed: "Run could not complete", cancelled: "Run stopped", loading: "Loading configuration" };
    $("status-label").textContent = labels[status] || status;
    $("status-detail").textContent = detail || "";
    $("status-dot").className = `status-dot ${status}`;
    if (status !== "ready" && status !== "loading") {
      $("output-badge").className = `result-badge ${status}`;
      $("output-badge").textContent = { queued: "QUEUED", running: "IN PROGRESS", verified: "LEAN VERIFIED", unverified: "UNVERIFIED", failed: "RUN FAILED", cancelled: "STOPPED" }[status] || status.toUpperCase();
    }
  }

  function setBusy(busy) {
    $("run-button-label").textContent = busy ? "Running…" : "Run agent";
    $("cancel-run").hidden = !busy;
    $("cancel-run").disabled = false;
    $("source-code").readOnly = busy;
    $("filename").disabled = busy;
    $("upload-button").disabled = busy;
    $("use-output").disabled = busy || !output.value;
    $("elapsed-time").hidden = !state.startedAt;
    updateSource();
  }

  function formatTime(value) {
    const dateValue = typeof value === "number" && value < 1e12 ? value * 1000 : value;
    const date = dateValue ? new Date(dateValue) : new Date();
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  }
  function renderEvents(events) {
    if (!Array.isArray(events)) return;
    const feed = $("activity-feed");
    const nearBottom = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 60;
    let added = false;
    events.forEach((event) => {
      const key = event.seq != null ? String(event.seq) : JSON.stringify([event.time, event.role, event.message, event.kind]);
      if (state.eventKeys.has(key)) return;
      state.eventKeys.add(key);
      const row = document.createElement("li");
      const safeKind = ["error", "success", "info", "warning"].includes(event.kind) ? event.kind : "info";
      row.className = `activity-event kind-${safeKind}`;
      const time = document.createElement("time"); time.className = "event-time"; time.textContent = formatTime(event.time); if (event.time) time.dateTime = String(event.time);
      const role = document.createElement("span"); role.className = "event-role"; role.textContent = roleLabels[event.role] || escapeText(event.role || "Workspace").replace(/_/g, " ");
      const message = document.createElement("p"); message.className = "event-message"; message.textContent = escapeText(event.message);
      row.append(time, role, message); feed.append(row); added = true;
    });
    $("event-count").textContent = state.eventKeys.size.toLocaleString();
    $("activity-empty").hidden = state.eventKeys.size > 0;
    if (added && nearBottom) feed.scrollTop = feed.scrollHeight;
  }

  function renderRun(run) {
    state.currentRun = run;
    renderEvents(run.events);
    if (typeof run.code === "string" && run.code !== output.value) updateOutput(run.code);
    const verified = run.status === "verified" && run.verified === true;
    const displayStatus = run.status === "verified" && !verified ? "unverified" : run.status;
    let detail = "The selected models are working with local Lean verification.";
    if (verified) detail = "The configured Lean checker accepted this result.";
    else if (run.status === "unverified") detail = "Search ended without an accepted proof. Inspect the candidate and diagnostics.";
    else if (run.status === "failed") detail = "Review the error and agent activity before trying again.";
    else if (run.status === "cancelled") detail = "The run was stopped. Any available candidate remains unverified.";
    else if (run.status === "queued") detail = "Waiting for the local harness to start this run.";
    setStatus(displayStatus, detail);
    if (run.filename) $("output-filename").textContent = run.filename;
    state.downloadUrl = typeof run.download_url === "string" && run.download_url.startsWith("/api/runs/") ? run.download_url : null;
    $("download-output").disabled = !state.downloadUrl || !output.value || !terminalStatuses.has(run.status);
    showRunError(run.error || "");
    if (terminalStatuses.has(run.status)) {
      state.activeId = null;
      setBusy(false);
      $("run-button-label").textContent = "Run again";
    }
  }

  async function pollRun() {
    if (!state.activeId || state.polling) return;
    state.polling = true;
    const id = state.activeId;
    try {
      const run = await api(`/api/runs/${encodeURIComponent(id)}`);
      if (state.activeId !== id) return;
      state.pollingFailures = 0;
      renderRun(run);
    } catch (error) {
      state.pollingFailures += 1;
      if (state.pollingFailures >= 3) showRunError(`Connection to the local harness was interrupted. Retrying automatically. ${error.message}`);
    } finally {
      state.polling = false;
      if (state.activeId) window.setTimeout(pollRun, Math.min(1000 * Math.max(1, state.pollingFailures), 5000));
    }
  }

  async function startRun() {
    if (state.activeId || !state.config || !source.value.trim()) return;
    const filename = getFilename(); $("filename").value = filename;
    showRunError("");
    state.activeId = "starting";
    state.startedAt = Date.now();
    state.eventKeys.clear(); $("activity-feed").replaceChildren(); $("event-count").textContent = "0"; $("activity-empty").hidden = false;
    state.downloadUrl = null; $("download-output").disabled = true;
    updateOutput(""); $("output-filename").textContent = outputFilename(filename);
    setBusy(true); setStatus("queued", "Sending your Lean file to the local harness…");
    try {
      const run = await api("/api/runs", { method: "POST", body: JSON.stringify({ code: source.value, filename, role_overrides: state.overrides }) });
      if (!run.id) throw new Error("The local server did not return a run identifier.");
      state.activeId = run.id;
      renderRun(run);
      if (state.activeId) pollRun();
    } catch (error) {
      state.activeId = null; setBusy(false); setStatus("failed", "The run could not be started."); showRunError(error.message);
    }
  }

  function readOverrides() {
    try {
      const value = JSON.parse(localStorage.getItem("formal-math-role-overrides") || "{}");
      return value && typeof value === "object" && !Array.isArray(value) ? value : {};
    } catch { return {}; }
  }
  function validOverrides(saved) {
    const result = {};
    for (const [name, override] of Object.entries(saved)) {
      if (!state.config.roles[name] || !override || typeof override !== "object") continue;
      const provider = typeof override.provider === "string" ? override.provider : state.config.roles[name].provider;
      const model = typeof override.model === "string" ? override.model.trim() : "";
      if (state.config.providers[provider] && model) result[name] = { provider, model };
    }
    return result;
  }
  function renderSettings() {
    if (!state.config) return;
    const roles = state.config.roles || {};
    const providers = state.config.providers || {};
    const root = $("role-settings"); root.replaceChildren();
    const names = [...roleOrder.filter((role) => roles[role]), ...Object.keys(roles).filter((role) => !roleOrder.includes(role))];
    names.forEach((name) => {
      const settings = roles[name]; const override = state.overrides[name] || {};
      const card = document.createElement("article"); card.className = "role-card"; card.dataset.role = name;
      const title = document.createElement("h3"); title.textContent = roleLabels[name] || name.replace(/_/g, " ");
      const fields = document.createElement("div"); fields.className = "role-inputs";
      const providerLabel = document.createElement("label"); providerLabel.textContent = "Provider";
      const select = document.createElement("select"); select.dataset.field = "provider"; select.setAttribute("aria-label", `${title.textContent} provider`);
      Object.keys(providers).forEach((provider) => { const option = document.createElement("option"); option.value = provider; option.textContent = provider; select.append(option); });
      select.value = override.provider || settings.provider;
      providerLabel.append(select);
      const modelLabel = document.createElement("label"); modelLabel.textContent = "Model";
      const input = document.createElement("input"); input.type = "text"; input.dataset.field = "model"; input.value = override.model || settings.model || ""; input.spellcheck = false; input.autocomplete = "off"; input.maxLength = 200; input.setAttribute("aria-label", `${title.textContent} model`);
      modelLabel.append(input); fields.append(providerLabel, modelLabel);
      const limits = document.createElement("div"); limits.className = "token-limits";
      [["Input", settings.input_tokens], ["Output", settings.output_tokens], ["Context", settings.context_tokens]].forEach(([label, number]) => { const item = document.createElement("span"); item.textContent = label; const strong = document.createElement("strong"); strong.textContent = typeof number === "number" ? number.toLocaleString() : "Server default"; item.append(strong); limits.append(item); });
      card.append(title, fields, limits); root.append(card);
    });
    const connections = $("provider-connections"); connections.replaceChildren();
    Object.entries(providers).forEach(([name, provider]) => {
      const row = document.createElement("div"); row.className = "provider-connection";
      const labels = document.createElement("div"); const title = document.createElement("strong"); title.textContent = name; const endpoint = document.createElement("code"); endpoint.textContent = provider.base_url || provider.kind || "Configured by server"; labels.append(title, endpoint);
      const badge = document.createElement("span"); badge.className = "credential-badge";
      const needsKey = ["openai", "anthropic"].includes(provider.kind);
      badge.textContent = provider.key_configured ? "KEY CONFIGURED" : needsKey ? "KEY NOT CONFIGURED" : "SERVER CONFIGURED";
      if (needsKey && !provider.key_configured) badge.classList.add("missing");
      row.append(labels, badge); connections.append(row);
    });
    const attempts = state.config.limits?.max_formal_attempts;
    $("settings-summary").textContent = attempts ? `Up to ${attempts} formal attempts per run. Lean acceptance ends the search immediately.` : "The local server controls search limits and tool connections.";
  }

  function openSettings() {
    state.focusBeforeSettings = document.activeElement;
    renderSettings(); $("settings-backdrop").hidden = false; $("settings-panel").hidden = false;
    document.body.style.overflow = "hidden"; $("close-settings").focus();
  }
  function closeSettings() {
    $("settings-backdrop").hidden = true; $("settings-panel").hidden = true;
    document.body.style.overflow = ""; state.focusBeforeSettings?.focus();
  }
  function saveSettings() {
    if (!state.config) { closeSettings(); return; }
    const overrides = {};
    for (const card of $("role-settings").querySelectorAll(".role-card")) {
      const name = card.dataset.role; const provider = card.querySelector("select").value; const model = card.querySelector("input").value.trim();
      if (!model) { card.querySelector("input").focus(); showToast("Enter a model name for every role."); return; }
      const defaults = state.config.roles[name];
      if (provider !== defaults.provider || model !== defaults.model) overrides[name] = { provider, model };
    }
    state.overrides = overrides;
    try { localStorage.setItem("formal-math-role-overrides", JSON.stringify(overrides)); } catch { /* Storage can be unavailable in private windows. */ }
    closeSettings(); showToast(state.activeId ? "Settings saved for the next run." : "Model settings applied.");
  }

  async function loadConfig() {
    try {
      const config = await api("/api/config");
      if (!config.roles || !config.providers) throw new Error("The server configuration is missing role or provider settings.");
      state.config = config; state.overrides = validOverrides(readOverrides());
      $("connection-error").hidden = true;
      if (!state.activeId && !state.currentRun) setStatus("ready", "Add a Lean file to start a locally managed proof run.");
      renderSettings(); updateSource();
    } catch (error) {
      $("connection-error-message").textContent = `Cannot load the local harness configuration. ${error.message}`;
      $("connection-error").hidden = false;
      if (!state.activeId) setStatus("failed", "Check that the local server is running.");
    }
  }

  source.addEventListener("input", updateSource);
  source.addEventListener("scroll", () => { $("source-lines").scrollTop = source.scrollTop; });
  output.addEventListener("scroll", () => { $("output-lines").scrollTop = output.scrollTop; });
  source.addEventListener("keydown", (event) => {
    if (event.key === "Tab" && !source.readOnly) { event.preventDefault(); const start = source.selectionStart; const end = source.selectionEnd; source.setRangeText("  ", start, end, "end"); updateSource(); }
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") { event.preventDefault(); startRun(); }
  });
  $("upload-button").addEventListener("click", () => $("file-upload").click());
  $("file-upload").addEventListener("change", async (event) => {
    const file = event.target.files?.[0]; if (!file) return;
    try {
      if (!file.name.toLowerCase().endsWith(".lean")) throw new Error("Choose a Lean source file with the .lean extension.");
      const maxBytes = state.config?.limits?.max_input_bytes || 262144;
      if (file.size > maxBytes) throw new Error(`Choose a Lean file no larger than ${Math.floor(maxBytes / 1024).toLocaleString()} KB.`);
      const text = await file.text();
      if (text.includes("\u0000")) throw new Error("The selected file contains binary data. Choose a UTF-8 Lean source file.");
      source.value = text; $("filename").value = file.name; updateSource(); showRunError(""); showToast(`Loaded ${file.name}`); source.focus();
    } catch (error) { showRunError(error.message); }
    event.target.value = "";
  });
  $("run-agent").addEventListener("click", startRun);
  $("cancel-run").addEventListener("click", async () => {
    if (!state.activeId || state.activeId === "starting") return;
    $("cancel-run").disabled = true; $("cancel-run").textContent = "Stopping…";
    try { const run = await api(`/api/runs/${encodeURIComponent(state.activeId)}/cancel`, { method: "POST" }); if (run.id && run.status) renderRun(run); }
    catch (error) { showRunError(error.message); $("cancel-run").disabled = false; }
    finally { $("cancel-run").textContent = "Stop run"; }
  });
  $("copy-output").addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(output.value); showToast("Lean code copied."); }
    catch { output.focus(); output.select(); showToast("Select the result and copy it with your keyboard."); }
  });
  $("use-output").addEventListener("click", () => { if (state.activeId || !output.value) return; source.value = output.value; updateSource(); source.focus(); showToast("Result moved to the source editor."); });
  $("download-output").addEventListener("click", () => { if (!state.downloadUrl) return; const link = document.createElement("a"); link.href = state.downloadUrl; link.download = $("output-filename").textContent || "result.lean"; document.body.append(link); link.click(); link.remove(); });
  $("open-settings").addEventListener("click", openSettings);
  $("close-settings").addEventListener("click", closeSettings);
  $("settings-backdrop").addEventListener("click", closeSettings);
  $("save-settings").addEventListener("click", saveSettings);
  $("reset-settings").addEventListener("click", () => { state.overrides = {}; try { localStorage.removeItem("formal-math-role-overrides"); } catch {} renderSettings(); showToast("Server defaults restored."); });
  $("retry-config").addEventListener("click", loadConfig);
  document.addEventListener("keydown", (event) => {
    if ($("settings-panel").hidden) return;
    if (event.key === "Escape") { closeSettings(); return; }
    if (event.key === "Tab") {
      const focusable = [...$("settings-panel").querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled), a[href]")];
      const first = focusable[0]; const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    }
  });
  window.setInterval(() => {
    if (!state.startedAt || !state.activeId) return;
    const seconds = Math.floor((Date.now() - state.startedAt) / 1000);
    $("elapsed-time").textContent = `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
  }, 1000);
  updateSource(); updateOutput(""); loadConfig();
})();
