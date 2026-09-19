const $ = (id) => document.getElementById(id);

function text(id, value) {
  $(id).textContent = String(value ?? "—");
}

function eventNode(item) {
  const row = document.createElement("div");
  row.className = "event";

  const status = document.createElement("div");
  status.className = "status";
  status.textContent = item.status || "—";

  const center = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = item.action || "Activity";
  const summary = document.createElement("p");
  summary.textContent = item.summary || "";
  const meta = document.createElement("small");
  meta.textContent = `${item.source || "XP"} → ${item.processor || "XP"}`;
  center.append(title, summary, meta);

  const source = document.createElement("div");
  source.className = "badge";
  source.textContent = item.live ? "LIVE" : "LOCAL";

  row.append(status, center, source);
  return row;
}

async function refreshStatus() {
  const button = $("refresh");
  button.disabled = true;
  button.textContent = "Memuat…";
  try {
    const response = await fetch("/api/status", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();

    text("project", data.project);
    text("checkpoint", `Checkpoint ${data.checkpoint}`);
    text("mode", data.mode);
    text("finalStatus", `Status ${data.final_status}`);
    text("provider", data.provider);
    text("model", data.model);
    text("cost", data.cost_state);
    text("worker", data.worker);
    text("recovery", data.recovery_status);
    text("permission", data.permission);
    text("approval", data.approval);
    text("verification", data.verification);
    text("rollback", data.rollback);
    text("sourceBadge", data.live ? "LIVE" : "LOCAL/OFFLINE");

    const list = $("activityList");
    list.replaceChildren();
    const activities = Array.isArray(data.activities) ? data.activities : [];
    text("activityCount", `${activities.length} events`);
    if (!activities.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "Belum ada aktivitas pada snapshot ini.";
      list.append(empty);
    } else {
      activities.slice().reverse().forEach((item) => {
        list.append(eventNode(item));
      });
    }
  } catch (error) {
    text("finalStatus", "Status PERLU_PERHATIAN");
    const list = $("activityList");
    list.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = `Status lokal gagal dimuat: ${error.message}`;
    list.append(empty);
  } finally {
    button.disabled = false;
    button.textContent = "Refresh Status";
  }
}

$("refresh").addEventListener("click", refreshStatus);
document.querySelector('[data-target="activity"]').addEventListener("click", () => {
  $("activity").scrollIntoView({behavior: "smooth"});
});
refreshStatus();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
