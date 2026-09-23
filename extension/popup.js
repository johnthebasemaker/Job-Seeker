/** Popup: import the pack, pick the job for this tab, or wipe the data. */
"use strict";

const statusEl = document.getElementById("status");
const jobsEl = document.getElementById("jobs");
const forgetEl = document.getElementById("forget");
const fileEl = document.getElementById("packfile");

function escapeHtml(value) {
  return (value || "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function ageText(iso) {
  if (!iso) return "";
  const hours = (Date.now() - new Date(iso).getTime()) / 3_600_000;
  if (Number.isNaN(hours)) return "";
  if (hours < 1) return "built just now";
  if (hours < 24) return `built ${Math.round(hours)} hour(s) ago`;
  return `built ${Math.round(hours / 24)} day(s) ago`;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function render() {
  const { pack, activeJobId } = await chrome.storage.local.get(["pack", "activeJobId"]);
  jobsEl.innerHTML = "";

  if (!pack) {
    statusEl.textContent =
      "No pack yet. In Job Seeker, open Apply, download the pack file, then import it here.";
    forgetEl.hidden = true;
    return;
  }

  const name = pack.profile?.full_name || "your profile";
  statusEl.innerHTML = `<strong>${escapeHtml(name)}</strong> · ${pack.jobs.length} job(s) ready · ${ageText(
    pack.generated_at
  )}`;
  forgetEl.hidden = false;

  for (const job of pack.jobs) {
    const item = document.createElement("li");
    item.className = "card";
    const chosen = job.id === activeJobId ? " · selected" : "";
    item.innerHTML = `
      <h2>${escapeHtml(job.title || "Untitled role")}</h2>
      <div class="muted">${escapeHtml(job.company || "")}${escapeHtml(chosen)}</div>
      <div class="row">
        <button data-open="${escapeHtml(job.id)}" class="primary">Open and use</button>
        <button data-use="${escapeHtml(job.id)}">Use on this tab</button>
      </div>`;
    jobsEl.appendChild(item);
  }
}

async function tellTab(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: "jobseeker:show" });
  } catch (error) {
    // No content script on this page (wrong site, or it needs a reload).
  }
}

jobsEl.addEventListener("click", async (event) => {
  const openId = event.target.getAttribute?.("data-open");
  const useId = event.target.getAttribute?.("data-use");
  const { pack } = await chrome.storage.local.get("pack");
  const job = pack?.jobs?.find((j) => j.id === (openId || useId));
  if (!job) return;

  await chrome.storage.local.set({ activeJobId: job.id });

  if (openId && job.apply_url) {
    const tab = await chrome.tabs.create({ url: job.apply_url });
    setTimeout(() => tellTab(tab.id), 2500);
  } else {
    const tab = await activeTab();
    if (tab?.id) await tellTab(tab.id);
  }
  await render();
});

fileEl.addEventListener("change", async () => {
  const file = fileEl.files?.[0];
  if (!file) return;
  try {
    const pack = JSON.parse(await file.text());
    if (!pack || !Array.isArray(pack.jobs)) throw new Error("that file is not an apply pack");
    if (pack.version !== 1) throw new Error(`unexpected pack version ${pack.version}`);
    await chrome.storage.local.set({ pack, activeJobId: null });
    await render();
  } catch (error) {
    statusEl.textContent = `Could not read that file: ${error.message}`;
  } finally {
    fileEl.value = "";
  }
});

forgetEl.addEventListener("click", async () => {
  await chrome.storage.local.clear();
  await render();
});

render();
