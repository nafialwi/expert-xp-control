const $ = (id) => document.getElementById(id);

const appState = {
  snapshot: null,
  projects: [],
  activities: [],
  session: null,
  currentView: "home",
  activityFilter: "all",
  projectFilter: "",
  loading: false,
  mutationBusy: false
};

class ApiError extends Error {
  constructor(status, message) {
    super(message || `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
  }
}

function text(id, value) {
  const node = $(id);
  if (node) node.textContent = String(value ?? "—");
}

function setGlobalStatus(message, tone = "neutral") {
  const node = $("globalStatus");
  if (!node) return;
  node.textContent = message;
  node.className = `notice notice-${tone}`;
}

function showToast(message) {
  const node = $("toast");
  if (!node) return;
  node.textContent = message;
  node.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    node.hidden = true;
  }, 3200);
}

function safeArray(value) {
  return Array.isArray(value) ? value : [];
}

function generateJobId() {
  const token = crypto.randomUUID().replaceAll("-", "");
  return `work-${token.slice(0, 12)}`;
}

async function apiGet(path) {
  const response = await fetch(path, {
    method: "GET",
    cache: "no-store",
    credentials: "same-origin"
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(response.status, data.error || `HTTP ${response.status}`);
  }
  return data;
}

async function apiPost(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    cache: "no-store",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify(payload)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new ApiError(response.status, data.error || `HTTP ${response.status}`);
  }
  return data;
}

function showView(name) {
  const allowed = new Set(["home", "work", "projects", "activity", "settings"]);
  const target = allowed.has(name) ? name : "home";
  appState.currentView = target;

  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    const active = panel.dataset.viewPanel === target;
    panel.hidden = !active;
    panel.classList.toggle("active", active);
  });

  document.querySelectorAll("[data-view]").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === target);
  });

  const titles = {
    home: "Home",
    work: "Work",
    projects: "Projects",
    activity: "Activity",
    settings: "Settings"
  };
  text("pageTitle", titles[target]);
}

function projectStatus(project) {
  if (!project || !project.git) return "Belum diperiksa";
  if (project.git.dirty === true) return "Perlu perhatian";
  if (project.git.inside_work_tree === true) return "Aman";
  return "Tidak siap";
}

function renderHome() {
  const snapshot = appState.snapshot || {};
  const project = snapshot.active_project || null;
  const latest = snapshot.latest_session || null;

  text(
    "activeProjectName",
    project ? `${project.name} · ${project.git?.branch || "branch —"}` : "Belum ada project aktif"
  );
  text("homeProjectName", project?.name || "Belum ada project aktif");
  text("homeProjectBranch", project?.git?.branch || "—");
  text("homeProjectState", projectStatus(project));
  text("homeProjectHead", project?.git?.head || "—");
  text("homeRecoveryCount", String(snapshot.recovery_count ?? 0));

  const capabilityValues = Object.values(snapshot.capabilities || {});
  const needsAttention = capabilityValues.filter((item) => item?.state !== "READY");
  text(
    "homeEngineStatus",
    capabilityValues.length === 0
      ? "Siap"
      : needsAttention.length === 0
        ? "Siap"
        : `${needsAttention.length} perlu perhatian`
  );

  if (latest) {
    if (!appState.session || appState.session.id === latest.id) {
      appState.session = latest;
    }
    text("homeLatestGoal", latest.goal || "Pekerjaan terakhir");
    text("homeLatestState", latest.state_label || latest.state || "—");
    text("homeSessionState", latest.state_label || latest.state || "—");
  } else {
    text("homeLatestGoal", "Belum ada pekerjaan");
    text("homeLatestState", "Session baru akan muncul setelah pekerjaan dimulai.");
    text("homeSessionState", "Belum ada");
  }

  const homeList = $("homeActivityList");
  if (homeList) renderActivityInto(homeList, appState.activities.slice(-5));
}

function projectNode(project) {
  const row = document.createElement("article");
  row.className = `project-row${project.active ? " active" : ""}`;
  row.dataset.projectId = String(project.id || "");

  const primary = document.createElement("div");
  const title = document.createElement("h3");
  title.textContent = project.name || project.id || "Project";
  const detail = document.createElement("p");
  detail.textContent = `${project.id || "—"} · ${project.source_kind || "—"}`;
  primary.append(title, detail);

  const git = document.createElement("div");
  const gitTitle = document.createElement("strong");
  gitTitle.textContent = project.git?.branch || "branch —";
  const gitDetail = document.createElement("p");
  gitDetail.textContent = `${projectStatus(project)} · ${project.git?.head || "HEAD —"}`;
  git.append(gitTitle, gitDetail);

  const action = document.createElement("button");
  action.type = "button";
  action.className = project.active ? "button button-secondary" : "button button-primary";
  action.dataset.projectSelect = String(project.id || "");
  action.textContent = project.active ? "Aktif" : "Pilih";
  action.disabled = Boolean(project.active || appState.mutationBusy);

  row.append(primary, git, action);
  return row;
}

function renderProjects() {
  const list = $("projectList");
  if (!list) return;
  list.replaceChildren();

  const query = appState.projectFilter.trim().toLowerCase();
  const projects = appState.projects.filter((project) => {
    if (!query) return true;
    const haystack = [
      project.id,
      project.name,
      project.git?.branch,
      project.git?.head
    ].join(" ").toLowerCase();
    return haystack.includes(query);
  });

  if (!projects.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = query ? "Project tidak ditemukan." : "Belum ada project terdaftar.";
    list.append(empty);
    return;
  }

  projects.forEach((project) => list.append(projectNode(project)));
}

function activityNode(item) {
  const row = document.createElement("article");
  row.className = "activity-event";

  const status = document.createElement("div");
  status.className = "activity-status";
  status.textContent = item.status || "—";

  const center = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = item.action || "Activity";
  const summary = document.createElement("p");
  summary.textContent = item.summary || "";
  const meta = document.createElement("small");
  meta.textContent = `${item.source || "XP"} → ${item.processor || "XP"}`;
  center.append(title, summary, meta);

  const right = document.createElement("small");
  right.textContent = item.live ? "LIVE" : "LOCAL";

  row.append(status, center, right);
  return row;
}

function renderActivityInto(container, items) {
  container.replaceChildren();
  const rows = safeArray(items);
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Belum ada aktivitas.";
    container.append(empty);
    return;
  }
  rows.slice().reverse().forEach((item) => container.append(activityNode(item)));
}

function renderActivity() {
  const list = $("activityList");
  if (!list) return;
  const filtered = appState.activityFilter === "all"
    ? appState.activities
    : appState.activities.filter((item) => item.status === appState.activityFilter);
  renderActivityInto(list, filtered);
}

function renderSettings() {
  const snapshot = appState.snapshot || {};
  const list = $("capabilityList");
  if (list) {
    list.replaceChildren();
    const entries = Object.entries(snapshot.capabilities || {});
    if (!entries.length) {
      const empty = document.createElement("div");
      empty.textContent = "Capability belum dilaporkan.";
      list.append(empty);
    } else {
      entries.forEach(([name, value]) => {
        const row = document.createElement("div");
        const key = document.createElement("span");
        key.textContent = name;
        const status = document.createElement("strong");
        status.textContent = `${value?.state || "UNKNOWN"}${value?.version ? ` · ${value.version}` : ""}`;
        row.append(key, status);
        list.append(row);
      });
    }
  }

  text("settingsRecoveryCount", String(snapshot.recovery_count ?? 0));
  text("settingsOrigin", window.location.origin);
  text("settingsPwa", "Aktif");
}

function markTimeline(stage, state) {
  const item = document.querySelector(`[data-stage="${stage}"]`);
  if (!item) return;
  item.classList.remove("done", "current");
  if (state === "done") item.classList.add("done");
  if (state === "current") item.classList.add("current");
}

function setActionEnabled(id, enabled) {
  const node = $(id);
  if (node) node.disabled = !enabled || appState.mutationBusy;
}

function renderWork() {
  const session = appState.session;
  const stages = ["prepare", "worker", "sandbox", "execute", "verify", "review"];
  stages.forEach((stage) => markTimeline(stage, "idle"));

  if (!session) {
    text("workState", "Belum ada session");
    text("workGoal", "Belum ada pekerjaan aktif");
    text("workProject", "Project —");
    text("workSessionMeta", "Session —");
    text("workerName", "Menunggu rekomendasi");
    text("workerReason", "Mulai pekerjaan dari Home untuk mendapatkan rekomendasi worker.");
    text("executionHint", "Worker hanya dapat berjalan setelah approval worker dan sandbox selesai.");
    text("reviewStatus", "Belum tersedia");
    text("reviewSummary", "Verification harus PASS sebelum Apply tersedia.");
    renderChangedFiles([]);
    text("diffPreview", "Belum ada diff untuk ditampilkan.");
    [
      "workerConfirmButton",
      "workerDeclineButton",
      "sandboxApproveButton",
      "sandboxDeclineButton",
      "executeButton",
      "applyButton",
      "discardButton"
    ].forEach((id) => setActionEnabled(id, false));
    return;
  }

  const allowed = new Set(safeArray(session.allowed_actions));
  const worker = session.worker || {};
  const confirmation = worker.confirmation || {};
  const sandbox = session.sandbox || {};
  const review = session.review || null;

  text("workState", session.state_label || session.state || "—");
  text("workGoal", session.goal || "Pekerjaan");
  text("workProject", session.project?.name || session.project?.id || "Project —");
  text("workSessionMeta", `Session ${session.id || "—"} · revision ${session.revision ?? "—"}`);
  text("workerName", worker.backend_id || "Menunggu rekomendasi");
  text("workerReason", worker.detail || confirmation.detail || "Worker ditentukan oleh policy XP.");
  text(
    "executionHint",
    sandbox.approved === true
      ? "Sandbox disetujui. Jalankan worker saat Anda siap."
      : "Source asli tetap aman sampai sandbox, verification, dan review selesai."
  );

  markTimeline("prepare", "done");

  if (confirmation.status === "CONFIRMED") {
    markTimeline("worker", "done");
  } else if (allowed.has("CONFIRM_WORKER")) {
    markTimeline("worker", "current");
  }

  if (sandbox.approved === true) {
    markTimeline("sandbox", "done");
  } else if (allowed.has("APPROVE_SANDBOX")) {
    markTimeline("sandbox", "current");
  }

  const executionStates = new Set([
    "RUNNING",
    "VERIFYING",
    "READY_TO_REVIEW",
    "APPLYING",
    "VERIFYING_APPLIED",
    "COMPLETED",
    "ROLLED_BACK"
  ]);
  if (allowed.has("EXECUTE")) {
    markTimeline("execute", "current");
  } else if (executionStates.has(session.state)) {
    markTimeline("execute", "done");
  }

  if (session.state === "VERIFYING") {
    markTimeline("verify", "current");
  } else if (review) {
    markTimeline("verify", "done");
  }

  if (session.state === "READY_TO_REVIEW") {
    markTimeline("review", "current");
  } else if (["COMPLETED", "CANCELLED", "ROLLED_BACK"].includes(session.state)) {
    markTimeline("review", "done");
  }

  setActionEnabled("workerConfirmButton", allowed.has("CONFIRM_WORKER"));
  setActionEnabled("workerDeclineButton", allowed.has("DECLINE_WORKER"));
  setActionEnabled("sandboxApproveButton", allowed.has("APPROVE_SANDBOX"));
  setActionEnabled("sandboxDeclineButton", allowed.has("DECLINE_SANDBOX"));
  setActionEnabled("executeButton", allowed.has("EXECUTE"));
  setActionEnabled("applyButton", allowed.has("APPLY"));
  setActionEnabled("discardButton", allowed.has("DISCARD"));

  if (review) {
    text("reviewStatus", review.status || "—");
    text("reviewSummary", review.summary || "Review tersedia.");
    renderChangedFiles(review.changed_files);
    text("diffPreview", review.bounded_diff || "Tidak ada preview diff.");
  } else {
    text("reviewStatus", "Belum tersedia");
    text("reviewSummary", session.state === "NEEDS_ATTENTION"
      ? "Pekerjaan perlu perhatian. Apply tidak tersedia."
      : "Verification harus PASS sebelum Apply tersedia.");
    renderChangedFiles([]);
    text("diffPreview", "Belum ada diff untuk ditampilkan.");
  }
}

function renderChangedFiles(files) {
  const list = $("changedFiles");
  if (!list) return;
  list.replaceChildren();
  const rows = safeArray(files);
  if (!rows.length) {
    const item = document.createElement("li");
    item.textContent = "Belum ada perubahan.";
    list.append(item);
    return;
  }
  rows.forEach((file) => {
    const item = document.createElement("li");
    item.textContent = String(file);
    list.append(item);
  });
}

function renderAll() {
  renderHome();
  renderProjects();
  renderActivity();
  renderSettings();
  renderWork();
}

function setMutationBusy(busy, message = "") {
  appState.mutationBusy = busy;
  if (message) setGlobalStatus(message, "neutral");
  renderProjects();
  renderWork();
}

function adoptSession(session) {
  appState.session = session;
  if (appState.snapshot) {
    appState.snapshot.latest_session = session;
  }
  renderAll();
}

async function loadAll() {
  if (appState.loading) return;
  appState.loading = true;
  const button = $("refreshAllButton");
  if (button) button.disabled = true;
  setGlobalStatus("Memuat status XP…", "neutral");

  try {
    const [snapshot, projectsPayload, activityPayload] = await Promise.all([
      apiGet("/api/v2/snapshot"),
      apiGet("/api/v2/projects"),
      apiGet("/api/v2/activity?limit=50")
    ]);
    appState.snapshot = snapshot;
    appState.projects = safeArray(projectsPayload.projects);
    appState.activities = safeArray(activityPayload.activities);
    if (!appState.session || !appState.session.id) {
      appState.session = snapshot.latest_session || null;
    } else if (snapshot.latest_session?.id === appState.session.id) {
      appState.session = snapshot.latest_session;
    }
    renderAll();
    setGlobalStatus("XP lokal siap. Semua aksi penting tetap membutuhkan keputusan Anda.", "safe");
    text("connectionBadge", "Local / Aman");
  } catch (error) {
    const message = error instanceof ApiError
      ? `XP lokal tidak dapat dimuat (HTTP ${error.status}).`
      : "XP lokal tidak dapat dihubungi.";
    setGlobalStatus(message, "danger");
    text("connectionBadge", "Perlu perhatian");
  } finally {
    appState.loading = false;
    if (button) button.disabled = false;
  }
}

async function handleMutationError(error) {
  if (error instanceof ApiError && error.status === 409) {
    setGlobalStatus(
      "Status pekerjaan berubah. XP memuat ulang state terbaru; periksa sebelum melanjutkan.",
      "warning"
    );
    await loadAll();
    showToast("State terbaru sudah dimuat. Tidak ada aksi yang diulang otomatis.");
    return;
  }
  if (error instanceof ApiError && error.status === 403) {
    setGlobalStatus("Session lokal tidak valid. Refresh halaman sebelum melanjutkan.", "danger");
    showToast("Aksi ditolak oleh guard session lokal.");
    return;
  }
  const message = error instanceof Error ? error.message : "Aksi gagal.";
  setGlobalStatus(`Perlu perhatian: ${message}`, "danger");
  showToast("Aksi tidak selesai. Source tidak dianggap berhasil diubah.");
}

async function selectProject(projectId) {
  if (!projectId || appState.mutationBusy) return;
  setMutationBusy(true, "Mengganti project aktif…");
  try {
    await apiPost("/api/v2/projects/select", {project_id: projectId});
    appState.session = null;
    await loadAll();
    showToast("Project aktif diperbarui.");
  } catch (error) {
    await handleMutationError(error);
  } finally {
    setMutationBusy(false);
  }
}

async function startWorkSession() {
  if (appState.mutationBusy) return;
  const goal = $("homeGoal")?.value.trim() || "";
  if (!goal) {
    showToast("Jelaskan pekerjaan yang ingin dilakukan.");
    $("homeGoal")?.focus();
    return;
  }

  const activeProject = appState.snapshot?.active_project || null;
  if (!activeProject && appState.projects.length > 1) {
    showToast("Pilih project terlebih dahulu.");
    showView("projects");
    return;
  }

  setMutationBusy(true, "Menyiapkan work session dan memeriksa project…");
  try {
    const session = await apiPost("/api/v2/work-sessions", {
      job_id: generateJobId(),
      project_id: activeProject?.id || null,
      goal
    });
    adoptSession(session);
    showView("work");
    await loadAll();
    showToast("Work session siap. Periksa rekomendasi worker.");
  } catch (error) {
    await handleMutationError(error);
  } finally {
    setMutationBusy(false);
  }
}

async function decideWorker(approved) {
  const session = appState.session;
  if (!session?.id || appState.mutationBusy) return;
  const backendId = session.worker?.backend_id;
  if (!backendId) {
    showToast("Worker belum tersedia.");
    return;
  }

  setMutationBusy(true, approved ? "Mengonfirmasi worker…" : "Membatalkan worker…");
  try {
    const result = await apiPost(
      `/api/v2/work-sessions/${encodeURIComponent(session.id)}/worker-decision`,
      {
        backend_id: backendId,
        approved: Boolean(approved),
        expected_revision: session.revision
      }
    );
    adoptSession(result);
    await loadAll();
    showToast(approved ? "Worker dikonfirmasi." : "Pekerjaan dibatalkan.");
  } catch (error) {
    await handleMutationError(error);
  } finally {
    setMutationBusy(false);
  }
}

async function decideSandbox(approved) {
  const session = appState.session;
  if (!session?.id || appState.mutationBusy) return;

  setMutationBusy(true, approved ? "Menyimpan persetujuan sandbox…" : "Membatalkan sandbox…");
  try {
    const result = await apiPost(
      `/api/v2/work-sessions/${encodeURIComponent(session.id)}/sandbox-decision`,
      {
        approved: Boolean(approved),
        expected_revision: session.revision
      }
    );
    adoptSession(result);
    await loadAll();
    showToast(approved ? "Sandbox disetujui." : "Pekerjaan dibatalkan.");
  } catch (error) {
    await handleMutationError(error);
  } finally {
    setMutationBusy(false);
  }
}

async function executeWork() {
  const session = appState.session;
  if (!session?.id || appState.mutationBusy) return;

  setMutationBusy(true, "XP sedang bekerja di sandbox dan akan memverifikasi hasil…");
  try {
    const result = await apiPost(
      `/api/v2/work-sessions/${encodeURIComponent(session.id)}/execute`,
      {expected_revision: session.revision}
    );
    adoptSession(result);
    await loadAll();
    if (result.state === "READY_TO_REVIEW") {
      showToast("Hasil siap direview. Source asli belum berubah.");
    } else if (result.state === "NEEDS_ATTENTION") {
      showToast("Verification memerlukan perhatian. Apply tidak tersedia.");
    }
  } catch (error) {
    await handleMutationError(error);
  } finally {
    setMutationBusy(false);
  }
}

async function decideReview(action) {
  const session = appState.session;
  if (!session?.id || appState.mutationBusy) return;
  const fingerprint = session.review?.change_fingerprint;
  if (!fingerprint) {
    showToast("Fingerprint review tidak tersedia.");
    return;
  }

  const applying = action === "APPLY";
  setMutationBusy(
    true,
    applying ? "Menerapkan hasil yang sudah direview…" : "Membuang hasil sandbox…"
  );
  try {
    const result = await apiPost(
      `/api/v2/work-sessions/${encodeURIComponent(session.id)}/review-decision`,
      {
        action,
        fingerprint,
        expected_revision: session.revision
      }
    );
    adoptSession(result);
    await loadAll();
    if (result.state === "COMPLETED") {
      showToast("Hasil diterapkan dan verification selesai.");
    } else if (result.state === "CANCELLED") {
      showToast("Hasil sandbox dibuang. Source asli tidak berubah.");
    } else {
      showToast("Keputusan review selesai dengan status perlu perhatian.");
    }
  } catch (error) {
    await handleMutationError(error);
  } finally {
    setMutationBusy(false);
  }
}

document.querySelectorAll("[data-view]").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.view));
});

document.querySelectorAll("[data-view-jump]").forEach((button) => {
  button.addEventListener("click", () => showView(button.dataset.viewJump));
});

$("refreshAllButton")?.addEventListener("click", loadAll);

$("projectSearch")?.addEventListener("input", (event) => {
  appState.projectFilter = event.target.value || "";
  renderProjects();
});

$("projectList")?.addEventListener("click", (event) => {
  const button = event.target.closest("[data-project-select]");
  if (!button) return;
  selectProject(button.dataset.projectSelect);
});

$("activityFilter")?.addEventListener("change", (event) => {
  appState.activityFilter = event.target.value || "all";
  renderActivity();
});

$("homeStartButton")?.addEventListener("click", startWorkSession);
$("workerConfirmButton")?.addEventListener("click", () => decideWorker(true));
$("workerDeclineButton")?.addEventListener("click", () => decideWorker(false));
$("sandboxApproveButton")?.addEventListener("click", () => decideSandbox(true));
$("sandboxDeclineButton")?.addEventListener("click", () => decideSandbox(false));
$("executeButton")?.addEventListener("click", executeWork);
$("applyButton")?.addEventListener("click", () => decideReview("APPLY"));
$("discardButton")?.addEventListener("click", () => decideReview("DISCARD"));

showView("home");
loadAll();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {
    setGlobalStatus("XP siap, tetapi service worker PWA perlu perhatian.", "warning");
  });
}
