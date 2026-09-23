const $ = (id) => document.getElementById(id);

const appState = {
  snapshot: null,
  projects: [],
  activities: [],
  session: null,
  currentView: "home",
  activityFilter: "all",
  projectFilter: "",
  loading: false
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

function shortValue(value, fallback = "—") {
  const normalized = String(value ?? "").trim();
  return normalized || fallback;
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
    appState.session = latest;
    text("homeLatestGoal", latest.goal || "Pekerjaan terakhir");
    text("homeLatestState", latest.state_label || latest.state || "—");
    text("homeSessionState", latest.state_label || latest.state || "—");
  } else {
    text("homeLatestGoal", "Belum ada pekerjaan");
    text("homeLatestState", "Session baru akan muncul setelah pekerjaan dimulai.");
    text("homeSessionState", "Belum ada");
  }

  const homeList = $("homeActivityList");
  if (homeList) {
    renderActivityInto(homeList, appState.activities.slice(-5));
  }
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
  action.disabled = Boolean(project.active);

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

function renderWorkSummary() {
  const session = appState.session;
  if (!session) {
    text("workState", "Belum ada session");
    text("workGoal", "Belum ada pekerjaan aktif");
    text("workProject", "Project —");
    text("workSessionMeta", "Session —");
    return;
  }

  text("workState", session.state_label || session.state || "—");
  text("workGoal", session.goal || "Pekerjaan");
  text("workProject", session.project?.name || session.project?.id || "Project —");
  text("workSessionMeta", `Session ${session.id || "—"} · revision ${session.revision ?? "—"}`);
}

function renderAll() {
  renderHome();
  renderProjects();
  renderActivity();
  renderSettings();
  renderWorkSummary();
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
    appState.session = snapshot.latest_session || appState.session;
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

$("activityFilter")?.addEventListener("change", (event) => {
  appState.activityFilter = event.target.value || "all";
  renderActivity();
});

$("homeStartButton")?.addEventListener("click", () => {
  const goal = $("homeGoal")?.value.trim() || "";
  if (!goal) {
    showToast("Jelaskan pekerjaan yang ingin dilakukan.");
    $("homeGoal")?.focus();
    return;
  }
  text("workGoal", goal);
  showView("work");
  showToast("Instruksi siap. Buat session pada langkah berikutnya.");
});

showView("home");
loadAll();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {
    setGlobalStatus("XP siap, tetapi service worker PWA perlu perhatian.", "warning");
  });
}
