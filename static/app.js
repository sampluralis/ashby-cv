// Elements
const jobSelect = document.getElementById("jobSelect");
const jobStatus = document.getElementById("jobStatus");

const searchBox = document.getElementById("searchBox");
const searchStatus = document.getElementById("searchStatus");
const countBadge = document.getElementById("countBadge");

const candidateSelect = document.getElementById("candidateSelect");
const summarizeBtn = document.getElementById("summarizeBtn");
const detailedToggle = document.getElementById("detailedToggle");

const summaryContainer = document.getElementById("summaryContainer");
const summaryPlaceholder = document.getElementById("summaryPlaceholder");
const summaryContent = document.getElementById("summaryContent");
const frontierIndicator = document.getElementById("frontierIndicator");
const frontierValue = document.getElementById("frontierValue");
const summaryText = document.getElementById("summaryText");
const scorecard = document.getElementById("scorecard");
const highlightsList = document.getElementById("highlightsList");
const flagsList = document.getElementById("flagsList");

const errorOut = document.getElementById("errorOut");
const loading = document.getElementById("loading");
const candidateMeta = document.getElementById("candidateMeta");

const refreshBtn = document.getElementById("refreshBtn");
const generateCacheBtn = document.getElementById("generateCacheBtn");
const sendAllAlertsBtn = document.getElementById("sendAllAlertsBtn");
const cacheInfo = document.getElementById("cacheInfo");
const copyBtn = document.getElementById("copyBtn");
const slackBtn = document.getElementById("slackBtn");

// Threshold inputs
const threshExp = document.getElementById("threshExp");
const threshEdu = document.getElementById("threshEdu");
const threshPub = document.getElementById("threshPub");
const threshSkills = document.getElementById("threshSkills");
const threshComm = document.getElementById("threshComm");

function getThresholds() {
  return {
    past_experience: parseInt(threshExp.value) || 7,
    education: parseInt(threshEdu.value) || 7,
    publications_research: parseInt(threshPub.value) || 7,
    skills_tooling: parseInt(threshSkills.value) || 7,
    communication_clarity: parseInt(threshComm.value) || 7
  };
}

// Store current summary data for copying
let currentSummaryData = null;

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

function showPlaceholder(msg) {
  summaryPlaceholder.textContent = msg;
  summaryPlaceholder.classList.remove("d-none");
  summaryContent.classList.add("d-none");
}

function getScoreClass(score) {
  if (score <= 3) return "score-low";
  if (score <= 6) return "score-mid";
  return "score-high";
}

function formatScoreLabel(key) {
  const labels = {
    past_experience: "Past Experience",
    education: "Education",
    publications_research: "Publications & Research",
    skills_tooling: "Skills & Tooling",
    communication_clarity: "Communication Clarity"
  };
  return labels[key] || key.replace(/_/g, " ");
}

function renderScorecard(scorecardData) {
  scorecard.innerHTML = "";

  const order = ["past_experience", "education", "publications_research", "skills_tooling", "communication_clarity"];

  for (const key of order) {
    const item = scorecardData[key];
    if (!item) continue;

    const score = item.score || 0;
    const rationale = item.rationale || "";
    const scoreClass = getScoreClass(score);

    const div = document.createElement("div");
    div.className = `score-item ${scoreClass}`;
    div.innerHTML = `
      <div class="score-label">${formatScoreLabel(key)}</div>
      <div class="score-value">
        <span class="score-number">${score}</span>
        <div class="score-bar">
          <div class="score-bar-fill" style="width: ${score * 10}%"></div>
        </div>
      </div>
      <div class="score-rationale">${rationale}</div>
    `;
    scorecard.appendChild(div);
  }
}

function renderList(listEl, items) {
  listEl.innerHTML = "";
  for (const item of items || []) {
    const li = document.createElement("li");
    li.innerHTML = `<span>${item}</span>`;
    listEl.appendChild(li);
  }
}

function renderSummary(data) {
  currentSummaryData = data;

  // Show content, hide placeholder
  summaryPlaceholder.classList.add("d-none");
  summaryContent.classList.remove("d-none");

  // Frontier lab indicator
  if (data.is_frontier_lab) {
    frontierIndicator.classList.remove("not-frontier");
    frontierIndicator.classList.add("is-frontier");
    frontierValue.textContent = data.frontier_lab_name || "Yes";
  } else {
    frontierIndicator.classList.remove("is-frontier");
    frontierIndicator.classList.add("not-frontier");
    frontierValue.textContent = "No";
  }

  // Summary text
  summaryText.textContent = data.summary || "No summary available.";

  // Scorecard
  if (data.scorecard) {
    renderScorecard(data.scorecard);
  }

  // Key highlights
  renderList(highlightsList, data.key_highlights);

  // Red flags
  renderList(flagsList, data.red_flags);
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
  showPlaceholder('Select a candidate and click "Generate summary".');
  currentSummaryData = null;
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
  showPlaceholder("Generating summary...");

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
      showPlaceholder("Failed to generate summary.");
      if (data.candidate) {
        candidateMeta.textContent = `${data.candidate.name} (${data.candidate.id})`;
      }
      return;
    }

    const cacheIndicator = data.from_cache ? " • (from cache)" : "";
    candidateMeta.textContent =
      `${data.candidate.name} • ${data.candidate.email} • resume chars: ${data.resume_length}${cacheIndicator}`;

    // Parse the summary JSON and render UI
    try {
      const summaryData = JSON.parse(data.summary);
      renderSummary(summaryData);
    } catch (parseErr) {
      // Fallback: show raw text if not valid JSON
      summaryPlaceholder.classList.add("d-none");
      summaryContent.classList.remove("d-none");
      summaryText.textContent = data.summary || "";
      scorecard.innerHTML = "";
      highlightsList.innerHTML = "";
      flagsList.innerHTML = "";
      frontierIndicator.classList.remove("is-frontier");
      frontierIndicator.classList.add("not-frontier");
      frontierValue.textContent = "Unknown";
      currentSummaryData = null;
    }
  } catch (e) {
    showError(`Summarize failed: ${e.message}`);
    showPlaceholder("Failed to generate summary.");
  } finally {
    setLoading(false);
  }
});

// Refresh button
refreshBtn.addEventListener("click", refreshCandidates);

// Generate cache button
generateCacheBtn.addEventListener("click", async () => {
  generateCacheBtn.disabled = true;
  generateCacheBtn.textContent = "Generating...";
  clearError();

  try {
    const job_id = getSelectedJobId();
    const url = new URL("/api/generate-cache", window.location.origin);
    if (job_id) url.searchParams.set("job_id", job_id);

    const res = await fetch(url.toString(), { method: "POST" });
    const data = await res.json();

    if (data.success) {
      cacheInfo.textContent = "generating...";
      // Poll cache status
      pollCacheStatus();
    } else {
      showError(data.error || "Failed to start cache generation");
    }
  } catch (e) {
    showError(`Cache generation failed: ${e.message}`);
  } finally {
    generateCacheBtn.disabled = false;
    generateCacheBtn.textContent = "Generate Cache";
  }
});

// Poll cache status
async function pollCacheStatus() {
  try {
    const res = await fetch("/api/cache-status");
    const data = await res.json();
    if (data.success) {
      cacheInfo.textContent = `${data.cached_count} cached`;
    }
  } catch (e) {
    // ignore
  }
}

// Check cache status on load
pollCacheStatus();

// Send to Slack button (individual candidate)
slackBtn.addEventListener("click", async () => {
  const candidate_id = getSelectedCandidateId();
  if (!candidate_id) {
    showError("Select a candidate first.");
    return;
  }

  slackBtn.disabled = true;
  slackBtn.textContent = "Sending...";
  clearError();

  try {
    const thresholds = getThresholds();
    const res = await fetch("/api/send-slack-alert", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ candidate_id, thresholds })
    });
    const data = await res.json();

    if (data.success && data.sent) {
      slackBtn.textContent = "Sent!";
      setTimeout(() => (slackBtn.textContent = "Send to Slack"), 2000);
    } else if (data.success && !data.sent) {
      showError(`Not sent: ${data.reason}`);
      slackBtn.textContent = "Send to Slack";
    } else {
      showError(data.error || "Failed to send alert");
      slackBtn.textContent = "Send to Slack";
    }
  } catch (e) {
    showError(`Slack alert failed: ${e.message}`);
    slackBtn.textContent = "Send to Slack";
  } finally {
    slackBtn.disabled = false;
  }
});

// Send All Alerts button
sendAllAlertsBtn.addEventListener("click", async () => {
  const thresholds = getThresholds();
  const threshStr = Object.entries(thresholds).map(([k, v]) => `${k.split('_')[0]}≥${v}`).join(', ');
  if (!confirm(`Send Slack alerts for ALL qualifying candidates?\n\nThresholds: ${threshStr}\n(or works at frontier lab)`)) {
    return;
  }

  sendAllAlertsBtn.disabled = true;
  sendAllAlertsBtn.textContent = "Sending...";
  clearError();

  try {
    const res = await fetch("/api/send-all-alerts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ thresholds })
    });
    const data = await res.json();

    if (data.success) {
      const msg = `Sent: ${data.sent_count}, Skipped: ${data.skipped_count}, Failed: ${data.failed_count}`;
      alert(msg);
      sendAllAlertsBtn.textContent = `Sent ${data.sent_count}!`;
      setTimeout(() => (sendAllAlertsBtn.textContent = "Alert All to Slack"), 3000);
    } else {
      showError(data.error || "Failed to send alerts");
      sendAllAlertsBtn.textContent = "Alert All to Slack";
    }
  } catch (e) {
    showError(`Bulk alert failed: ${e.message}`);
    sendAllAlertsBtn.textContent = "Alert All to Slack";
  } finally {
    sendAllAlertsBtn.disabled = false;
  }
});

// Copy button
copyBtn.addEventListener("click", async () => {
  try {
    let textToCopy = "";
    if (currentSummaryData) {
      // Format the data nicely for copying
      const d = currentSummaryData;
      const lines = [];

      if (d.is_frontier_lab && d.frontier_lab_name) {
        lines.push(`[${d.frontier_lab_name}]`);
        lines.push("");
      }

      lines.push("SUMMARY");
      lines.push(d.summary || "");
      lines.push("");

      lines.push("SCORECARD");
      if (d.scorecard) {
        for (const [key, val] of Object.entries(d.scorecard)) {
          lines.push(`  ${formatScoreLabel(key)}: ${val.score}/10 - ${val.rationale}`);
        }
      }
      lines.push("");

      if (d.key_highlights && d.key_highlights.length) {
        lines.push("KEY HIGHLIGHTS");
        for (const h of d.key_highlights) {
          lines.push(`  • ${h}`);
        }
        lines.push("");
      }

      if (d.red_flags && d.red_flags.length) {
        lines.push("RED FLAGS");
        for (const f of d.red_flags) {
          lines.push(`  • ${f}`);
        }
      }

      textToCopy = lines.join("\n");
    } else {
      // Fallback to raw content
      textToCopy = summaryText.textContent || summaryPlaceholder.textContent || "";
    }

    await navigator.clipboard.writeText(textToCopy);
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
