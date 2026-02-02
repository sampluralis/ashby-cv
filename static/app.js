// Elements
const jobSelect = document.getElementById("jobSelect");
const jobStatus = document.getElementById("jobStatus");

const searchBox = document.getElementById("searchBox");
const searchStatus = document.getElementById("searchStatus");
const countBadge = document.getElementById("countBadge");

const candidateSelect = document.getElementById("candidateSelect");
const summarizeBtn = document.getElementById("summarizeBtn");
const detailedToggle = document.getElementById("detailedToggle");

const summaryOut = document.getElementById("summaryOut");
const errorOut = document.getElementById("errorOut");
const loading = document.getElementById("loading");
const candidateMeta = document.getElementById("candidateMeta");

const refreshBtn = document.getElementById("refreshBtn");
const cacheInfo = document.getElementById("cacheInfo");
const copyBtn = document.getElementById("copyBtn");

// Helpers
function setLoading(on) {
  if (on) loading.classList.remove("d-none");
  else loading.classList.add("d-none");
  summarizeBtn.disabled = on;
  refreshBtn.disabled = on;
}

function clearError() {
  errorOut.textContent = "";
}

function showError(msg) {
  errorOut.textContent = msg || "";
}

function getSelectedJobId() {
  return jobSelect.value || "";
}

function getSelectedCandidateId() {
  return candidateSelect.value || "";
}

function renderJobs(jobs) {
  jobSelect.innerHTML = "";

  // "All jobs" option
  const optAll = document.createElement("option");
  optAll.value = "";
  optAll.textContent = "All jobs";
  jobSelect.appendChild(optAll);

  for (const j of jobs) {
    if (!j.id) continue;
    const opt = document.createElement("option");
    opt.value = j.id;
    opt.textContent = `${j.title || "Untitled"} (${j.status || "Unknown"}) — ${j.id}`;
    jobSelect.appendChild(opt);
  }

  jobStatus.textContent = `Loaded ${jobs.length} jobs.`;
}

function renderCandidates(items) {
  candidateSelect.innerHTML = "";

  for (const c of items) {
    const opt = document.createElement("option");
    opt.value = c.id;
    opt.textContent = `${c.name || "Unknown"} — ${c.id}`;
    candidateSelect.appendChild(opt);
  }

  countBadge.textContent = `${items.length} shown`;
  searchStatus.textContent = items.length
    ? `Showing ${items.length} candidates.`
    : "No candidates found for this filter.";
}

// API calls
async function fetchJobs() {
  const res = await fetch("/api/jobs");
  const data = await res.json();
  if (!data.success) throw new Error("Failed to load jobs");
  return data.results || [];
}

async function fetchCandidates(query = "") {
  const url = new URL("/api/candidates", window.location.origin);

  const job_id = getSelectedJobId();
  if (job_id) url.searchParams.set("job_id", job_id);
  if (query) url.searchParams.set("q", query);

  const res = await fetch(url.toString());
  const data = await res.json();
  if (!data.success) throw new Error("Failed to load candidates");
  return data.results || [];
}

async function refreshCandidates() {
  setLoading(true);
  clearError();
  try {
    const url = new URL("/api/refresh", window.location.origin);
    const job_id = getSelectedJobId();
    if (job_id) url.searchParams.set("job_id", job_id);

    const res = await fetch(url.toString(), { method: "POST" });
    const data = await res.json();

    cacheInfo.textContent = `cache refreshed (${data.count})`;
    const items = await fetchCandidates(searchBox.value.trim());
    renderCandidates(items);
  } catch (e) {
    showError(`Refresh failed: ${e.message}`);
  } finally {
    setLoading(false);
  }
}

// Debounced search
let searchTimer = null;
searchBox.addEventListener("input", () => {
  const q = searchBox.value.trim();
  if (searchTimer) clearTimeout(searchTimer);

  searchTimer = setTimeout(async () => {
    clearError();
    try {
      const items = await fetchCandidates(q);
      renderCandidates(items);
    } catch (e) {
      showError(`Search failed: ${e.message}`);
    }
  }, 200);
});

// Job change => reload candidates
jobSelect.addEventListener("change", async () => {
  clearError();
  cacheInfo.textContent = "cache ok";
  candidateMeta.textContent = "";
  summaryOut.textContent = "Select a candidate and click “Generate summary”.";
  searchBox.value = "";

  try {
    const items = await fetchCandidates("");
    renderCandidates(items);
  } catch (e) {
    showError(`Failed to load candidates for job: ${e.message}`);
  }
});

// Summarize
summarizeBtn.addEventListener("click", async () => {
  const candidate_id = getSelectedCandidateId();
  if (!candidate_id) {
    showError("Select a candidate first.");
    return;
  }

  setLoading(true);
  clearError();
  candidateMeta.textContent = "";
  summaryOut.textContent = "";

  try {
    const res = await fetch("/api/summary", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        candidate_id,
        detailed: detailedToggle.checked
      })
    });

    const data = await res.json();

    if (!data.success) {
      showError(data.error || "Failed to generate summary");
      if (data.candidate) {
        candidateMeta.textContent = `${data.candidate.name} (${data.candidate.id})`;
      }
      return;
    }

    candidateMeta.textContent =
      `${data.candidate.name} • ${data.candidate.email} • resume chars: ${data.resume_length}`;

    summaryOut.textContent = data.summary || "";
  } catch (e) {
    showError(`Summarize failed: ${e.message}`);
  } finally {
    setLoading(false);
  }
});

// Refresh button
refreshBtn.addEventListener("click", refreshCandidates);

// Copy button
copyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(summaryOut.textContent || "");
    copyBtn.textContent = "Copied!";
    setTimeout(() => (copyBtn.textContent = "Copy"), 900);
  } catch {
    showError("Could not copy to clipboard.");
  }
});

// Init
(async function init() {
  try {
    clearError();
    const jobs = await fetchJobs();
    renderJobs(jobs);

    const items = await fetchCandidates("");
    renderCandidates(items);

    cacheInfo.textContent = "cache ok";
  } catch (e) {
    showError(`Init failed: ${e.message}`);
    jobStatus.textContent = "Failed to load jobs.";
  }
})();
