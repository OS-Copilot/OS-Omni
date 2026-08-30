const NAV_ITEMS = [
  { id: "overview", label: "Overview", caption: "platform dashboard", icon: "dashboard" },
  { id: "results", label: "Results", caption: "run ledger", icon: "table" },
  { id: "analysis", label: "Analysis", caption: "deep signals", icon: "chart" },
];

const REVIEW_STORAGE_KEY = "benchmark-workbench-reviews-v3";
const DEFAULT_PLATFORM = "ios";
const STEP_NODE_SAMPLE_LIMIT = 14;

const state = {
  workspace: null,
  route: parseRoute(),
  filters: {
    platform: DEFAULT_PLATFORM,
    model: "all",
    status: "all",
    category: "all",
    execution: "all",
    search: "",
  },
  sort: "recent",
  runDetails: new Map(),
  currentRun: null,
  currentFrameIndex: 0,
  isLoadingWorkspace: false,
  isLoadingRun: false,
  isRefreshing: false,
  error: "",
  playbackTimer: null,
  isPlaying: false,
  modal: null,
  disclosurePayloads: new Map(),
  disclosureSequence: 0,
  reviews: loadReviews(),
};

const app = document.getElementById("app");

bootstrap();
window.addEventListener("hashchange", handleRouteChange);
window.addEventListener("keydown", handleKeydown);
app.addEventListener("click", handleClick);
app.addEventListener("input", handleInput);
app.addEventListener("change", handleInput);
app.addEventListener("submit", handleSubmit);

async function bootstrap() {
  await loadWorkspace();
  normalizePlatformFilter();
  await maybeLoadRouteData();
  render();
}

async function handleRouteChange() {
  stopPlayback();
  state.route = parseRoute();
  state.currentFrameIndex = 0;
  state.modal = null;
  await maybeLoadRouteData();
  render();
}

async function loadWorkspace(forceRefresh = false) {
  state.isLoadingWorkspace = !state.workspace;
  state.isRefreshing = forceRefresh;
  state.error = "";
  render();
  try {
    const url = forceRefresh ? "/api/workspace?refresh=1" : "/api/workspace";
    const response = await fetch(url);
    if (!response.ok) {
      throw new Error(`Workspace request failed with ${response.status}`);
    }
    state.workspace = await response.json();
  } catch (error) {
    state.error = error.message || "Failed to load workspace";
  } finally {
    state.isLoadingWorkspace = false;
    state.isRefreshing = false;
  }
}

function normalizePlatformFilter() {
  const platforms = state.workspace?.facets?.platforms?.map((item) => item.value) || [];
  if (platforms.includes(DEFAULT_PLATFORM)) {
    state.filters.platform = DEFAULT_PLATFORM;
    return;
  }
  if (!platforms.includes(state.filters.platform)) {
    state.filters.platform = platforms[0] || "";
  }
}

async function maybeLoadRouteData() {
  state.currentRun = null;
  if (state.route.name !== "run") {
    return;
  }
  await ensureRunDetail(state.route.runId);
}

async function ensureRunDetail(runId) {
  if (!runId) {
    return;
  }
  if (state.runDetails.has(runId)) {
    state.currentRun = state.runDetails.get(runId);
    return;
  }

  state.isLoadingRun = true;
  state.error = "";
  render();
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}`);
    if (!response.ok) {
      throw new Error(`Run request failed with ${response.status}`);
    }
    const payload = await response.json();
    state.runDetails.set(runId, payload);
    state.currentRun = payload;
  } catch (error) {
    state.error = error.message || "Failed to load run";
  } finally {
    state.isLoadingRun = false;
  }
}

function handleInput(event) {
  const element = event.target;
  if (!element.name) {
    return;
  }

  if (element.name in state.filters) {
    state.filters[element.name] = element.value;
    render();
    return;
  }

  if (element.name === "sort") {
    state.sort = element.value;
    render();
  }
}

async function handleClick(event) {
  const action = event.target.closest("[data-action]");
  if (!action) {
    return;
  }

  const kind = action.dataset.action;

  if (kind === "open-disclosure") {
    const payload = state.disclosurePayloads.get(action.dataset.disclosureId || "");
    if (payload) {
      state.modal = payload;
      render();
    }
    return;
  }

  if (kind === "close-modal") {
    state.modal = null;
    render();
    return;
  }

  if (kind === "navigate") {
    window.location.hash = action.dataset.route || "#/overview";
    return;
  }

  if (kind === "open-run") {
    window.location.hash = `#/runs/${encodeURIComponent(action.dataset.runId || "")}`;
    return;
  }

  if (kind === "refresh") {
    stopPlayback();
    state.runDetails.clear();
    await loadWorkspace(true);
    normalizePlatformFilter();
    await maybeLoadRouteData();
    render();
    return;
  }

  if (kind === "reset-filters") {
    state.filters = {
      platform: DEFAULT_PLATFORM,
      model: "all",
      status: "all",
      category: "all",
      execution: "all",
      search: "",
    };
    normalizePlatformFilter();
    render();
    return;
  }

  if (kind === "set-filter") {
    const key = action.dataset.filterKey;
    if (key && key in state.filters) {
      state.filters[key] = action.dataset.filterValue || "all";
    }
    if (action.dataset.route) {
      window.location.hash = action.dataset.route;
      return;
    }
    render();
    return;
  }

  if (kind === "frame") {
    stopPlayback();
    state.currentFrameIndex = Number(action.dataset.frameIndex || 0);
    render();
    return;
  }

  if (kind === "playback") {
    const frames = getFrames(state.currentRun);
    if (!frames.length) {
      return;
    }
    const command = action.dataset.command;
    if (command === "prev") {
      stopPlayback();
      state.currentFrameIndex = Math.max(0, state.currentFrameIndex - 1);
      render();
      return;
    }
    if (command === "next") {
      stopPlayback();
      state.currentFrameIndex = Math.min(frames.length - 1, state.currentFrameIndex + 1);
      render();
      return;
    }
    if (command === "toggle") {
      togglePlayback();
    }
    return;
  }

  if (kind === "clear-review") {
    const runId = action.dataset.runId;
    if (runId) {
      deleteReviewRecord(runId);
      render();
    }
  }
}

function handleSubmit(event) {
  const form = event.target.closest("[data-form]");
  if (!form || form.dataset.form !== "save-review") {
    return;
  }

  event.preventDefault();
  const payload = new FormData(form);
  const runId = String(payload.get("runId") || "");
  const verdict = String(payload.get("verdict") || "").trim();
  const note = String(payload.get("note") || "").trim();
  const tags = String(payload.get("tags") || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);

  if (!runId || !verdict) {
    return;
  }

  upsertReviewRecord(runId, {
    verdict,
    note,
    tags,
    updatedAt: new Date().toISOString(),
  });
  render();
}

function handleKeydown(event) {
  if (state.modal) {
    if (event.key === "Escape") {
      state.modal = null;
      render();
    }
    return;
  }

  if (state.route.name !== "run") {
    return;
  }

  const frames = getFrames(state.currentRun);
  if (!frames.length) {
    return;
  }

  if (event.key === "ArrowRight") {
    stopPlayback();
    state.currentFrameIndex = Math.min(frames.length - 1, state.currentFrameIndex + 1);
    render();
  } else if (event.key === "ArrowLeft") {
    stopPlayback();
    state.currentFrameIndex = Math.max(0, state.currentFrameIndex - 1);
    render();
  } else if (event.key === " ") {
    const target = event.target;
    if (target && ["INPUT", "TEXTAREA", "SELECT", "BUTTON"].includes(target.tagName)) {
      return;
    }
    event.preventDefault();
    togglePlayback();
  }
}

function togglePlayback() {
  const frames = getFrames(state.currentRun);
  if (!frames.length) {
    return;
  }

  if (state.isPlaying) {
    stopPlayback();
    render();
    return;
  }

  state.isPlaying = true;
  state.playbackTimer = window.setInterval(() => {
    const lastIndex = frames.length - 1;
    if (state.currentFrameIndex >= lastIndex) {
      stopPlayback();
      render();
      return;
    }
    state.currentFrameIndex += 1;
    render();
  }, 1600);
  render();
}

function stopPlayback() {
  if (state.playbackTimer) {
    window.clearInterval(state.playbackTimer);
    state.playbackTimer = null;
  }
  state.isPlaying = false;
}

function render() {
  document.body.dataset.route = activeModuleId();
  state.disclosurePayloads.clear();
  state.disclosureSequence = 0;
  if (state.route.name === "run") {
    app.innerHTML = renderRunRoute();
    return;
  }
  app.innerHTML = renderModuleRoute();
}

function renderModuleRoute() {
  const moduleId = state.route.module || "overview";
  if (!state.workspace && state.isLoadingWorkspace) {
    return renderShell({
      moduleId,
      title: "Benchmark Workbench",
      kicker: "Loading",
      subtitle: "Scanning local benchmark artifacts.",
      content: renderLoadingState("Building the workspace from result.json, trajectory.jsonl, and screenshots."),
    });
  }

  if (!state.workspace) {
    return renderShell({
      moduleId,
      title: "Benchmark Workbench",
      kicker: "No data",
      subtitle: "Workspace data is unavailable.",
      content: state.error ? renderErrorState(state.error) : renderEmptyState("No result roots were indexed."),
    });
  }

  const content = moduleId === "results"
    ? renderResultsModule()
    : moduleId === "analysis"
      ? renderAnalysisModule()
      : renderOverviewModule();

  return renderShell({
    moduleId,
    title: moduleTitle(moduleId),
    kicker: moduleKicker(moduleId),
    content,
  });
}

function renderOverviewModule() {
  const runs = getFilteredRuns();
  const executions = getExecutionsInScope(runs);
  const stats = buildScopeStats(runs, executions);
  const modelStats = buildModelStats(runs);
  const appStats = buildAppStats(runs);
  const taskRisk = buildTaskRiskStats(runs);
  const recentRuns = runs.slice(0, 8);
  const pendingRuns = getPendingReviewRuns(runs).slice(0, 5);
  const latestExecution = executions[0];

  return `
    <section class="metric-grid">
      ${renderMetricCard("Success rate", percent(stats.successRate), `${stats.passCount} pass / ${stats.nonPassCount} non-pass`, "success")}
      ${renderMetricCard("Pending review", String(getPendingReviewRuns(runs).length), "Non-pass runs without a saved human verdict", "warning")}
      ${renderMetricCard("Average steps", formatNumber(stats.averageSteps), "Mean trajectory length", "neutral")}
      ${renderMetricCard("Average duration", formatSeconds(stats.averageLatencySeconds), "Across runs with latency data", "neutral")}
    </section>

    <section class="overview-columns">
      <div class="overview-stack">
        <article class="panel">
          <div class="panel-header">
            <div>
              <p class="section-label">Execution trend</p>
              <h3>Latest batches</h3>
            </div>
            ${latestExecution ? `<button class="ghost-button" data-action="set-filter" data-filter-key="execution" data-filter-value="${escapeAttribute(latestExecution.id)}" data-route="#/results">${icon("arrowRight")} Latest results</button>` : ""}
          </div>
          ${renderExecutionTrend(executions)}
        </article>

        <article class="panel">
          <div class="panel-header">
            <div>
              <p class="section-label">Area coverage</p>
              <h3>Task groups</h3>
            </div>
          </div>
          ${renderAreaCoverageList(appStats)}
        </article>

        <article class="panel">
          <div class="panel-header">
            <div>
              <p class="section-label">Recent ledger</p>
              <h3>Latest runs</h3>
            </div>
            <button class="ghost-button" data-action="navigate" data-route="#/results">${icon("table")} Open ledger</button>
          </div>
          <div class="overview-run-list">
            ${recentRuns.map(renderOverviewRunRow).join("") || renderInlineEmpty("No recent runs in scope.")}
          </div>
        </article>
      </div>

      <div class="overview-stack">
        <article class="panel">
          <div class="panel-header">
            <div>
              <p class="section-label">Model health</p>
              <h3>Top active models</h3>
            </div>
          </div>
          <div class="bar-list">
            ${modelStats.slice(0, 5).map((item) => renderBarRow(item.label, item.successRate, percent(item.successRate), `${item.total} runs | ${formatSeconds(item.avgLatencySeconds)} avg`)).join("") || renderInlineEmpty("No model signal available.")}
          </div>
        </article>

        <article class="panel">
          <div class="panel-header">
            <div>
              <p class="section-label">Needs attention</p>
              <h3>Review queue</h3>
            </div>
            <button class="ghost-button" data-action="set-filter" data-filter-key="status" data-filter-value="nonpass" data-route="#/results">${icon("filter")} View all</button>
          </div>
          <div class="run-stack">
            ${pendingRuns.map(renderCompactRunRow).join("") || renderInlineEmpty("No pending non-pass runs.")}
          </div>
        </article>

        <article class="panel">
          <div class="panel-header">
            <div>
              <p class="section-label">Task risk</p>
              <h3>Hotspots</h3>
            </div>
          </div>
          <div class="risk-list">
            ${taskRisk.slice(0, 5).map(renderRiskRow).join("") || renderInlineEmpty("No task risk signal yet.")}
          </div>
        </article>
      </div>
    </section>
  `;
}

function renderResultsModule() {
  const runs = getSortedRuns(getFilteredRuns());
  const executions = getExecutionsInScope(runs);
  const stats = buildScopeStats(runs, executions);
  const appStats = buildAppStats(runs);

  return `
    <section class="metric-grid compact">
      ${renderMetricCard("Runs", String(stats.runCount), `${stats.executionCount} execution batches`, "neutral")}
      ${renderMetricCard("Tasks", String(stats.taskCount), `${appStats.length} task areas`, "neutral")}
      ${renderMetricCard("Success", percent(stats.successRate), `${stats.passCount} pass`, "success")}
      ${renderMetricCard("Non-pass", String(stats.nonPassCount), `${stats.failCount} fail + ${stats.errorCount} error`, stats.nonPassCount ? "danger" : "neutral")}
    </section>

    <section class="panel">
      <div class="panel-header">
        <div>
          <p class="section-label">Classification</p>
          <h3>Browse by task area</h3>
        </div>
        <button class="ghost-button" data-action="reset-filters">${icon("rotate")} Reset filters</button>
      </div>
      <div class="cluster-strip">
        ${renderClusterButton("all", "All groups", runs.length, state.filters.category === "all")}
        ${appStats.map((item) => renderClusterButton(item.value, item.label, item.total, state.filters.category === item.value, item.successRate)).join("")}
      </div>
    </section>

    <section class="results-layout">
      <article class="panel result-ledger">
        <div class="panel-header">
          <div>
            <p class="section-label">Run ledger</p>
            <h3>Every benchmark run in the current scope</h3>
          </div>
          <label class="sort-control">
            <span>Sort</span>
            <select name="sort">
              <option value="recent" ${selected(state.sort, "recent")}>Newest first</option>
              <option value="risk" ${selected(state.sort, "risk")}>Non-pass first</option>
              <option value="steps" ${selected(state.sort, "steps")}>Most steps</option>
              <option value="duration" ${selected(state.sort, "duration")}>Longest duration</option>
            </select>
          </label>
        </div>
        ${renderRunLedger(runs)}
      </article>

      <aside class="side-stack">
        <article class="panel">
          <div class="panel-header">
            <div>
              <p class="section-label">Execution batches</p>
              <h3>Recent groups</h3>
            </div>
          </div>
          <div class="run-stack">
            ${executions.slice(0, 8).map(renderExecutionCard).join("") || renderInlineEmpty("No executions in scope.")}
          </div>
        </article>

        <article class="panel">
          <div class="panel-header">
            <div>
              <p class="section-label">Result mix</p>
              <h3>Status distribution</h3>
            </div>
          </div>
          ${renderStatusRing(stats, "small")}
          <div class="legend-grid">
            ${renderLegendItem("Pass", stats.passCount, "success")}
            ${renderLegendItem("Fail", stats.failCount, "danger")}
            ${renderLegendItem("Error", stats.errorCount, "warning")}
          </div>
        </article>
      </aside>
    </section>
  `;
}

function renderAnalysisModule() {
  const runs = getFilteredRuns();
  const executions = getExecutionsInScope(runs);
  const stats = buildScopeStats(runs, executions);
  const modelStats = buildModelStats(runs);
  const taskRisk = buildTaskRiskStats(runs);
  const appStats = buildAppStats(runs);
  const hist = buildStepHistogram(runs);
  const reviewStats = buildReviewStats(runs);

  return `
    <section class="metric-grid compact">
      ${renderMetricCard("Runs analyzed", String(stats.runCount), `${stats.taskCount} unique tasks`, "neutral")}
      ${renderMetricCard("Median steps", formatNumber(median(runs.map((run) => run.stepsTaken).filter(isFiniteNumber))), "Step-length midpoint", "neutral")}
      ${renderMetricCard("Review coverage", percent(reviewStats.coverage), `${reviewStats.reviewed} reviewed / ${reviewStats.queue} queued`, "warning")}
      ${renderMetricCard("Longest run", formatMs(Math.max(0, ...runs.map((run) => run.latencyMs || 0))), "Latency outlier", "neutral")}
    </section>

    <section class="analysis-grid">
      <article class="panel panel-large">
        <div class="panel-header">
          <div>
            <p class="section-label">Special chart</p>
            <h3>Model efficiency map</h3>
          </div>
        </div>
        ${renderModelBubbleChart(modelStats)}
      </article>

      <article class="panel">
        <div class="panel-header">
          <div>
            <p class="section-label">Step shape</p>
            <h3>Trajectory histogram</h3>
          </div>
        </div>
        ${renderHistogram(hist)}
      </article>

      <div class="analysis-detail-layout panel-wide">
        <div class="analysis-detail-main">
          <article class="panel">
            <div class="panel-header">
              <div>
                <p class="section-label">Risk heatmap</p>
                <h3>Tasks by failure pressure</h3>
              </div>
            </div>
            ${renderRiskHeatmap(taskRisk)}
          </article>

          <article class="panel">
            <div class="panel-header">
              <div>
                <p class="section-label">Execution scorecards</p>
                <h3>Batch-level comparison</h3>
              </div>
            </div>
            ${renderExecutionScorecards(executions)}
          </article>
        </div>

        <aside class="analysis-detail-side">
          <article class="panel">
            <div class="panel-header">
              <div>
                <p class="section-label">Task areas</p>
                <h3>Coverage and pass rate</h3>
              </div>
            </div>
            <div class="bar-list">
              ${appStats.map((item) => renderBarRow(item.label, item.successRate, percent(item.successRate), `${item.total} runs`)).join("") || renderInlineEmpty("No task-area coverage data.")}
            </div>
          </article>
        </aside>
      </div>
    </section>
  `;
}

function renderRunRoute() {
  const run = state.currentRun;
  const summary = state.workspace?.runs?.find((item) => item.id === state.route.runId);
  if (!run && state.isLoadingRun) {
    return renderShell({
      moduleId: "results",
      title: summary?.taskLabel || "Run detail",
      kicker: "Loading run",
      subtitle: "Fetching replay frames and artifacts.",
      content: renderLoadingState("Loading trajectory, screenshots, observations, and review state."),
    });
  }

  if (!run) {
    return renderShell({
      moduleId: "results",
      title: summary?.taskLabel || "Run detail",
      kicker: "Missing run",
      subtitle: "The selected run could not be loaded.",
      content: state.error ? renderErrorState(state.error) : renderEmptyState("Run detail was not found."),
    });
  }

  const frames = getFrames(run);
  const frame = frames[state.currentFrameIndex] || frames[0] || null;
  const observation = frame?.observation || null;
  const review = getReviewRecord(run.id);
  const appName = getRunCategory(run);
  const taskInstruction = instructionText(run);
  const taskDescription = run.description && run.description !== taskInstruction ? run.description : "";
  const taskMeta = [
    run.taskId,
    run.modelName || run.modelId || "Unknown model",
    run.execution?.name || "local execution",
  ].filter(Boolean).join(" · ");

  return renderShell({
    moduleId: "results",
    title: friendlyTaskName(run),
    kicker: `${escapeHtml(appName)} / ${escapeHtml(labelPlatform(run.platform || "unknown"))}`,
    subtitle: taskMeta,
    content: `
      <section class="detail-toolbar">
        <button class="ghost-button" data-action="navigate" data-route="#/results">${icon("arrowLeft")} Back to results</button>
        <div class="detail-path">${escapeHtml(run.paths?.runDir || "")}</div>
      </section>

      <section class="detail-hero">
        <article class="panel detail-summary-panel">
          <div class="detail-summary-top">
            <div class="meta-chip-list">
              ${run.taskId ? `<span class="meta-chip mono">${escapeHtml(run.taskId)}</span>` : ""}
              ${run.execution?.name ? `<span class="meta-chip">${escapeHtml(run.execution.name)}</span>` : ""}
              ${run.modelName || run.modelId ? `<span class="meta-chip">${escapeHtml(run.modelName || run.modelId)}</span>` : ""}
            </div>
          </div>
          ${taskDescription ? `<p class="detail-summary-copy">${escapeHtml(taskDescription)}</p>` : ""}
          ${taskInstruction ? renderDisclosure("Full instruction", taskInstruction) : ""}
        </article>
      </section>

      <section class="metric-grid compact">
        ${renderMetricCard("Status", normalizeStatusLabel(run.status), run.failureMessage || run.result?.evaluation?.message || "Evaluator outcome", toneForStatus(run.status))}
        ${renderMetricCard("Review", review ? reviewVerdictLabel(review.verdict) : reviewStateLabel(run), review ? formatDateTime(review.updatedAt) : "No human verdict saved", review ? toneForVerdict(review.verdict) : "warning")}
        ${renderMetricCard("Steps", String(run.stepsTaken || frames.length || 0), `${frames.length} replay frames`, "neutral")}
        ${renderMetricCard("Duration", formatMs(run.latencyMs), formatDateTime(run.startedAt), "neutral")}
      </section>

      <section class="run-detail-layout">
        <div class="run-detail-main">
          <article class="panel replay-panel">
            <div class="panel-header">
              <div>
                <p class="section-label">Step review</p>
                <h3>${escapeHtml(frame?.label || "No frame selected")}</h3>
              </div>
              <div class="playback-controls">
                <button class="icon-button" aria-label="Previous frame" data-action="playback" data-command="prev">${icon("chevronLeft")}</button>
                <button class="play-button" data-action="playback" data-command="toggle">${state.isPlaying ? icon("pause") : icon("play")}${state.isPlaying ? " Pause" : " Play"}</button>
                <button class="icon-button" aria-label="Next frame" data-action="playback" data-command="next">${icon("chevronRight")}</button>
              </div>
            </div>
            <div class="replay-stage-layout">
              <div class="replay-stage-column">
                ${frame ? renderFrameStage(run, frame, observation) : renderInlineEmpty("No replayable frames were found.")}
                <div class="frame-rail" aria-label="Replay frames">
                  ${frames.map((item, index) => renderFramePill(item, index, index === state.currentFrameIndex)).join("")}
                </div>
              </div>

              <div class="replay-detail-column">
                <div class="subsection-header">
                  <p class="section-label">Frame details</p>
                  <h3>${escapeHtml(frame?.kind === "final" ? "Terminal state" : frame?.action?.type || "Action trace")}</h3>
                </div>
                ${frame ? renderFrameAnalysis(run, frame) : renderInlineEmpty("Select a frame to inspect action details.")}
              </div>
            </div>
          </article>

          <div class="detail-panel-grid">
            <article class="panel">
              <div class="panel-header">
                <div>
                  <p class="section-label">Observation</p>
                  <h3>UI capture</h3>
                </div>
              </div>
              ${renderObservationPanel(observation || run.finalObservation)}
            </article>

            <article class="panel">
              <div class="panel-header">
                <div>
                  <p class="section-label">Evaluation</p>
                  <h3>Outcome payload</h3>
                </div>
              </div>
              ${renderOutcomePanel(run)}
            </article>
          </div>

          <article class="panel">
            <div class="panel-header">
              <div>
                <p class="section-label">Artifacts</p>
                <h3>Raw files</h3>
              </div>
            </div>
            <div class="artifact-grid">
              ${renderArtifactLink("args.json", run.artifacts?.files?.args)}
              ${renderArtifactLink("result.json", run.artifacts?.files?.result)}
              ${renderArtifactLink("trajectory.jsonl", run.artifacts?.files?.trajectory)}
              ${renderArtifactLink("runner.log", run.artifacts?.files?.runnerLog)}
            </div>
          </article>

          ${run.runnerLog?.preview ? `
            <article class="panel panel-wide">
              <div class="panel-header">
                <div>
                  <p class="section-label">Runner log</p>
                  <h3>Tail preview</h3>
                </div>
              </div>
              <pre>${escapeHtml(run.runnerLog.preview)}</pre>
            </article>
          ` : ""}
        </div>

        <aside class="run-detail-side">
          <div class="side-stack">
            <article class="panel">
              <div class="panel-header">
                <div>
                  <p class="section-label">Decision</p>
                  <h3>Manual review</h3>
                </div>
                ${review ? renderVerdictBadge(review.verdict) : renderReviewBadge(run)}
              </div>
              ${renderReviewForm(run)}
            </article>

            <article class="panel">
              <div class="panel-header">
                <div>
                  <p class="section-label">Run context</p>
                  <h3>Identity</h3>
                </div>
              </div>
              <dl class="key-grid detail-side-grid">
                ${renderKeyValue("Task id", run.taskId, true)}
                ${renderKeyValue("Area", appName)}
                ${renderKeyValue("Model", run.modelName || run.modelId, true)}
                ${renderKeyValue("Execution", run.execution?.name, true)}
                ${renderKeyValue("Action mode", run.actionMode || "--")}
              ${renderKeyValue("Observation", run.observationMode || "--")}
              </dl>
            </article>
          </div>
        </aside>
      </section>
    `,
  });
}

function renderShell({ moduleId, title, kicker, subtitle, content }) {
  const stats = state.workspace?.stats || {};
  return `
    <a class="skip-link" href="#main">Skip to content</a>
    <div class="app-shell">
      <aside class="sidebar">
        <div class="brand-block">
          <div class="brand-mark">${icon("bolt")}</div>
          <div>
            <strong>OS-Omni</strong>
            <span>Benchmark Workbench</span>
          </div>
        </div>
        <nav class="nav-list" aria-label="Primary navigation">
          ${NAV_ITEMS.map((item) => renderNavItem(item, moduleId)).join("")}
        </nav>
        <div class="sidebar-card">
          <span>Workspace</span>
          <strong>${stats.runCount || 0} runs</strong>
          <small>${percent(stats.successRate)} success across ${stats.executionCount || 0} batches</small>
        </div>
      </aside>

      <div class="main-shell">
        <header class="topbar">
          <div>
            <p class="page-kicker">${escapeHtml(kicker)}</p>
            <h1>${escapeHtml(title)}</h1>
            ${subtitle ? `<p>${escapeHtml(subtitle)}</p>` : ""}
          </div>
          ${state.route.name !== "run" ? `
            <div class="topbar-actions">
              ${renderPlatformSelector()}
              <button class="primary-button" data-action="refresh">${icon("refresh")} ${state.isRefreshing ? "Rescanning" : "Rescan"}</button>
            </div>
          ` : ""}
        </header>

        <main id="main" class="content">
          ${state.workspace && state.route.name !== "run" ? renderScopeBar() : ""}
          ${state.error && state.workspace ? `<div class="notice danger">${escapeHtml(state.error)}</div>` : ""}
          ${content}
        </main>
      </div>
    </div>
    ${renderModal()}
  `;
}

function renderNavItem(item, activeModuleId) {
  const active = item.id === activeModuleId;
  return `
    <button class="nav-item ${active ? "active" : ""}" data-action="navigate" data-route="#/${item.id}">
      ${icon(item.icon)}
      <span>
        <strong>${escapeHtml(item.label)}</strong>
        <small>${escapeHtml(item.caption)}</small>
      </span>
    </button>
  `;
}

function renderPlatformSelector() {
  const platforms = state.workspace?.facets?.platforms || [];
  if (!platforms.length) {
    return `
      <div class="platform-control platform-switcher">
        <span>Platform</span>
        <strong>No data</strong>
        <small>No indexed platforms yet</small>
      </div>
    `;
  }
  return `
    <label class="platform-control platform-switcher">
      <span>Platform</span>
      <select name="platform">
        ${platforms.map((item) => `<option value="${escapeAttribute(item.value)}" ${selected(state.filters.platform, item.value)}>${escapeHtml(labelPlatform(item.value))}</option>`).join("")}
      </select>
    </label>
  `;
}

function renderScopeBar() {
  const runs = getFilteredRuns();
  return `
    <section class="scope-bar">
      <label class="search-field">
        ${icon("search")}
        <span class="sr-only">Search runs</span>
        <input name="search" type="search" value="${escapeAttribute(state.filters.search)}" placeholder="Search task, model, execution..." />
      </label>
      ${renderSelectField("Model", "model", getModelOptions(), state.filters.model)}
      ${renderSelectField("Status", "status", getStatusOptions(), state.filters.status)}
      ${renderSelectField("Area", "category", getCategoryOptions(), state.filters.category)}
      ${renderSelectField("Execution", "execution", getExecutionOptions(), state.filters.execution)}
      <div class="scope-count">${escapeHtml(`${runs.length} visible`)}</div>
    </section>
  `;
}

function renderSelectField(label, name, options, value) {
  return `
    <label class="select-field">
      <span>${escapeHtml(label)}</span>
      <select name="${escapeAttribute(name)}">
        ${options.map((option) => `<option value="${escapeAttribute(option.value)}" ${selected(value, option.value)}>${escapeHtml(option.label)}</option>`).join("")}
      </select>
    </label>
  `;
}

function renderMetricCard(label, value, helper, tone = "neutral") {
  return `
    <article class="metric-card tone-${tone}">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(value)}</strong>
      <small>${escapeHtml(helper)}</small>
    </article>
  `;
}

function renderStatusRing(stats, size = "normal") {
  const pass = clamp(stats.successRate || 0, 0, 1);
  const fail = stats.runCount ? (stats.failCount || 0) / stats.runCount : 0;
  const error = stats.runCount ? (stats.errorCount || 0) / stats.runCount : 0;
  const passDeg = pass * 360;
  const failDeg = fail * 360;
  const style = `--pass:${passDeg}deg;--fail:${failDeg}deg;--error:${error * 360}deg`;
  return `
    <div class="status-ring ${size === "small" ? "status-ring-small" : ""}" style="${style}" aria-label="Status mix">
      <div>
        <strong>${escapeHtml(percent(pass))}</strong>
        <span>pass rate</span>
      </div>
    </div>
  `;
}

function renderExecutionTrend(executions) {
  const items = executions.slice(0, 10).reverse();
  if (!items.length) {
    return renderInlineEmpty("No execution trend can be drawn yet.");
  }

  const width = 720;
  const height = 230;
  const padX = 34;
  const padY = 28;
  const points = items.map((item, index) => {
    const x = items.length === 1 ? width / 2 : padX + (index / (items.length - 1)) * (width - padX * 2);
    const y = height - padY - clamp(item.successRate || 0, 0, 1) * (height - padY * 2);
    return {
      x,
      y,
      item,
      left: `${((x / width) * 100).toFixed(3)}%`,
      top: `${((y / height) * 100).toFixed(3)}%`,
    };
  });
  const line = points.map((point) => `${point.x},${point.y}`).join(" ");
  const area = `${padX},${height - padY} ${line} ${width - padX},${height - padY}`;

  return `
    <div class="trend-chart">
      <div class="trend-plot">
        <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="Execution success trend">
          <defs>
            <linearGradient id="trendFill" x1="0" x2="0" y1="0" y2="1">
              <stop offset="0%" stop-color="#2563eb" stop-opacity="0.22" />
              <stop offset="100%" stop-color="#14b8a6" stop-opacity="0.02" />
            </linearGradient>
          </defs>
          <line x1="${padX}" y1="${height - padY}" x2="${width - padX}" y2="${height - padY}" class="axis-line" />
          <line x1="${padX}" y1="${padY}" x2="${padX}" y2="${height - padY}" class="axis-line" />
          <polygon points="${area}" fill="url(#trendFill)" />
          <polyline points="${line}" class="trend-line" />
        </svg>
        <div class="trend-points" aria-hidden="true">
          ${points.map((point) => `<span class="trend-point" style="--point-x:${point.left};--point-y:${point.top}" title="${escapeAttribute(point.item.name || "execution")} - ${escapeAttribute(percent(point.item.successRate))}"></span>`).join("")}
        </div>
      </div>
      <div class="trend-labels">
        ${points.map((point) => `<span style="--label-x:${point.left}" title="${escapeAttribute(point.item.name || "")}">${escapeHtml(percent(point.item.successRate))}</span>`).join("")}
      </div>
    </div>
  `;
}

function renderBarRow(label, ratio, value, helper) {
  return `
    <div class="bar-row">
      <div class="bar-top">
        <strong title="${escapeAttribute(label)}">${escapeHtml(truncate(label, 44))}</strong>
        <span>${escapeHtml(value)}</span>
      </div>
      <div class="bar-track"><i style="width:${percentUnit(ratio || 0)}"></i></div>
      <small>${escapeHtml(helper)}</small>
    </div>
  `;
}

function renderAppTile(item) {
  return `
    <button class="app-tile" data-action="set-filter" data-filter-key="category" data-filter-value="${escapeAttribute(item.value)}" data-route="#/results">
      <span>${escapeHtml(item.label.slice(0, 2).toUpperCase())}</span>
      <strong>${escapeHtml(item.label)}</strong>
      <small>${escapeHtml(`${item.total} runs | ${percent(item.successRate)}`)}</small>
    </button>
  `;
}

function renderAreaCoverageList(items) {
  const rows = items.slice(0, 8);
  if (!rows.length) {
    return renderInlineEmpty("No task areas in scope.");
  }
  return `
    <div class="area-list">
      ${rows.map((item) => `
        <button class="area-row" data-action="set-filter" data-filter-key="category" data-filter-value="${escapeAttribute(item.value)}" data-route="#/results">
          <span class="area-main">
            <strong>${escapeHtml(item.label)}</strong>
            <small>${escapeHtml(`${item.total} runs`)}</small>
          </span>
          <span class="area-rate">${escapeHtml(percent(item.successRate))}</span>
          <i class="area-bar"><b style="width:${percentUnit(item.successRate)}"></b></i>
        </button>
      `).join("")}
    </div>
  `;
}

function renderCompactRunRow(run) {
  return `
    <button class="run-card" data-action="open-run" data-run-id="${escapeAttribute(run.id)}">
      <div>
        <strong title="${escapeAttribute(friendlyTaskName(run))}">${escapeHtml(truncate(friendlyTaskName(run), 56))}</strong>
        <small>${escapeHtml(`${getRunCategory(run)} / ${run.modelName || run.modelId || "unknown"}`)}</small>
      </div>
      ${renderStatusBadge(run.status)}
    </button>
  `;
}

function renderOverviewRunRow(run) {
  return `
    <button class="overview-run-row" data-action="open-run" data-run-id="${escapeAttribute(run.id)}">
      <span class="overview-run-main">
        <strong title="${escapeAttribute(friendlyTaskName(run))}">${escapeHtml(truncate(friendlyTaskName(run), 64))}</strong>
        <small>${escapeHtml(`${getRunCategory(run)} / ${run.modelName || run.modelId || "unknown"}`)}</small>
      </span>
      <span class="overview-run-meta">
        ${renderStatusBadge(run.status)}
        <small>${escapeHtml(`${run.stepsTaken || 0} steps / ${formatMs(run.latencyMs)}`)}</small>
      </span>
    </button>
  `;
}

function renderExecutionCard(execution) {
  return `
    <button class="run-card" data-action="set-filter" data-filter-key="execution" data-filter-value="${escapeAttribute(execution.id)}">
      <div>
        <strong title="${escapeAttribute(execution.name || "")}">${escapeHtml(truncate(execution.name || "Execution", 50))}</strong>
        <small>${escapeHtml(`${execution.runCount || 0} runs / ${execution.taskCount || 0} tasks`)}</small>
      </div>
      <span class="score-pill">${escapeHtml(percent(execution.successRate))}</span>
    </button>
  `;
}

function renderRiskRow(task) {
  return `
    <button class="risk-row" data-action="set-filter" data-filter-key="search" data-filter-value="${escapeAttribute(task.key)}" data-route="#/results">
      <div>
        <strong title="${escapeAttribute(task.label)}">${escapeHtml(truncate(task.label, 48))}</strong>
        <small>${escapeHtml(`${task.nonPassCount} non-pass / ${task.runCount} runs`)}</small>
      </div>
      <span class="risk-meter" style="--risk:${percentUnit(task.risk)}"></span>
    </button>
  `;
}

function renderClusterButton(value, label, total, active, successRate = null) {
  const attrs = `data-action="set-filter" data-filter-key="category" data-filter-value="${escapeAttribute(value)}"`;
  return `
    <button class="cluster-button ${active ? "active" : ""}" ${attrs}>
      <strong>${escapeHtml(label)}</strong>
      <span>${escapeHtml(successRate == null ? `${total} runs` : `${total} runs / ${percent(successRate)}`)}</span>
    </button>
  `;
}

function renderRunLedger(runs, options = {}) {
  if (!runs.length) {
    return renderInlineEmpty("No runs match the current scope.");
  }

  const rows = runs.map((run) => `
    <tr>
      <td>
        <button class="task-link" data-action="open-run" data-run-id="${escapeAttribute(run.id)}">
          <strong title="${escapeAttribute(friendlyTaskName(run))}">${escapeHtml(truncate(friendlyTaskName(run), options.compact ? 52 : 70))}</strong>
          <span>${escapeHtml(run.taskId || "")}</span>
        </button>
      </td>
      <td>${renderCategoryChip(getRunCategory(run))}</td>
      <td><span class="mono">${escapeHtml(truncate(run.modelName || run.modelId || "unknown", 28))}</span></td>
      <td>${renderStatusBadge(run.status)}</td>
      <td>${renderReviewBadge(run)}</td>
      <td>${escapeHtml(String(run.stepsTaken || 0))}</td>
      <td>${escapeHtml(formatMs(run.latencyMs))}</td>
      <td><span title="${escapeAttribute(run.execution?.name || "")}">${escapeHtml(truncate(run.execution?.name || "--", 42))}</span></td>
      <td>${escapeHtml(formatDateTime(run.startedAt))}</td>
    </tr>
  `).join("");

  return `
    <div class="table-wrap">
      <table class="run-table">
        <thead>
          <tr>
            <th>Task</th>
            <th>Area</th>
            <th>Model</th>
            <th>Status</th>
            <th>Review</th>
            <th>Steps</th>
            <th>Duration</th>
            <th>Execution</th>
            <th>Started</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderCategoryChip(label) {
  return `<span class="category-chip">${escapeHtml(label)}</span>`;
}

function renderStatusBadge(status) {
  const normalized = String(status || "UNKNOWN").toUpperCase();
  return `<span class="status-badge status-${normalized.toLowerCase()}"><i></i>${escapeHtml(normalizeStatusLabel(normalized))}</span>`;
}

function renderReviewBadge(run) {
  const review = getReviewRecord(run.id);
  if (review) {
    return renderVerdictBadge(review.verdict);
  }
  if (!run.success) {
    return `<span class="review-badge pending">Pending</span>`;
  }
  return `<span class="review-badge muted">Not needed</span>`;
}

function renderVerdictBadge(verdict) {
  return `<span class="review-badge ${escapeAttribute(toneForVerdict(verdict))}">${escapeHtml(reviewVerdictLabel(verdict))}</span>`;
}

function renderLegendItem(label, value, tone) {
  return `
    <div class="legend-item ${tone}">
      <i></i>
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(String(value || 0))}</strong>
    </div>
  `;
}

function renderFrameStage(run, frame, observation) {
  const width = observation?.width || 440;
  const height = observation?.height || 956;
  const aspect = `${Math.max(width, 1)} / ${Math.max(height, 1)}`;
  const shot = frame.screenshot?.url
    ? `<img src="${escapeAttribute(frame.screenshot.url)}" alt="${escapeAttribute(frame.label)}" />`
    : `<div class="stage-empty">No screenshot</div>`;

  return `
    <div class="phone-frame">
      <div class="phone-top"></div>
      <div class="phone-screen" style="aspect-ratio:${aspect}">
        ${shot}
      </div>
    </div>
  `;
}

function renderFramePill(frame, index, active) {
  return `
    <button class="frame-pill ${active ? "active" : ""}" data-action="frame" data-frame-index="${index}">
      <strong>${escapeHtml(frame.badge)}</strong>
      <span>${escapeHtml(frame.shortLabel)}</span>
    </button>
  `;
}

function renderFrameAnalysis(run, frame) {
  if (frame.kind === "final") {
    return `
      <div class="detail-stack">
        <dl class="key-grid">
          ${renderKeyValue("Outcome", normalizeStatusLabel(run.status))}
          ${renderKeyValue("Episode", run.result?.episode_result?.status || "--")}
          ${renderKeyValue("Evaluation", run.result?.evaluation?.status || "--")}
          ${renderKeyValue("Ended", formatDateTime(run.endedAt))}
        </dl>
        ${run.result?.episode_result?.message ? `<div class="note-block">${escapeHtml(run.result.episode_result.message)}</div>` : ""}
        ${run.result?.evaluation?.message ? `<div class="note-block">${escapeHtml(run.result.evaluation.message)}</div>` : ""}
        ${renderJsonDisclosure("Evaluation metadata", run.result?.evaluation?.metadata)}
      </div>
    `;
  }

  return `
    <div class="detail-stack">
      <dl class="key-grid">
        ${renderKeyValue("Action", frame.action?.type || "--")}
        ${renderKeyValue("Parse", frame.action?.parseStatus || "--")}
        ${renderKeyValue("Execution", frame.outcome?.executionStatus || "--")}
        ${renderKeyValue("Latency", formatMs(frame.latencies?.stepMs))}
        ${renderKeyValue("Foreground", frame.observation?.foregroundBundleId || frame.observation?.foregroundApp || "--", true)}
        ${renderKeyValue("Nodes", String(frame.observation?.nodeCount || 0))}
      </dl>
      ${frame.outcome?.message ? `<div class="note-block">${escapeHtml(frame.outcome.message)}</div>` : ""}
      ${frame.action?.payload ? renderJsonDisclosure("Action payload", frame.action.payload) : ""}
      ${frame.action?.execution ? renderJsonDisclosure("Execution payload", frame.action.execution) : ""}
      ${frame.llmResponse ? renderDisclosure("Model output", frame.llmResponse) : ""}
    </div>
  `;
}

function renderObservationPanel(observation) {
  const nodes = observation?.sampleNodes || [];
  return `
    <div class="detail-stack">
      <dl class="key-grid">
        ${renderKeyValue("Foreground", observation?.foregroundApp || observation?.foregroundBundleId || "--", true)}
        ${renderKeyValue("Resolution", observation ? `${observation.width || "--"} x ${observation.height || "--"}` : "--")}
        ${renderKeyValue("Nodes", observation?.nodeCount ?? "--")}
        ${renderKeyValue("Keyboard", observation?.isKeyboardShown === true ? "Shown" : observation?.isKeyboardShown === false ? "Hidden" : "--")}
      </dl>
      ${nodes.length ? `
        <div class="node-list">
          ${nodes.slice(0, STEP_NODE_SAMPLE_LIMIT).map((node) => `
            <div class="node-row">
              <span>${escapeHtml(node.type || "--")}</span>
              <strong title="${escapeAttribute(node.label || node.text || "")}">${escapeHtml(truncate(node.label || node.text || "--", 64))}</strong>
            </div>
          `).join("")}
        </div>
      ` : renderInlineEmpty("No accessibility nodes captured for this frame.")}
      ${renderJsonDisclosure("Addition info", observation?.additionInfo)}
    </div>
  `;
}

function renderOutcomePanel(run) {
  const messages = uniqueText(
    run.failureMessage,
    run.result?.episode_result?.message,
    run.result?.evaluation?.message,
  );
  return `
    <div class="detail-stack">
      ${messages.map((message, index) => `<div class="${index === 0 ? "notice danger" : "note-block"}">${escapeHtml(message)}</div>`).join("")}
      <dl class="key-grid">
        ${renderKeyValue("Episode", run.result?.episode_result?.status || "--")}
        ${renderKeyValue("Evaluation", run.result?.evaluation?.status || "--")}
        ${renderKeyValue("Initializer", run.result?.initializer?.status || "--")}
        ${renderKeyValue("Result file", run.paths?.result, true)}
      </dl>
      ${renderJsonDisclosure("Evaluation", run.result?.evaluation)}
    </div>
  `;
}

function renderReviewForm(run) {
  const review = getReviewRecord(run.id);
  return `
    <form class="review-form" data-form="save-review">
      <input type="hidden" name="runId" value="${escapeAttribute(run.id)}" />
      <label>
        <span>Verdict</span>
        <select name="verdict" required>
          <option value="" ${selected(review?.verdict || "", "")}>Choose verdict</option>
          <option value="confirmed-pass" ${selected(review?.verdict || "", "confirmed-pass")}>Confirmed pass</option>
          <option value="confirmed-fail" ${selected(review?.verdict || "", "confirmed-fail")}>Confirmed fail</option>
          <option value="needs-rerun" ${selected(review?.verdict || "", "needs-rerun")}>Needs rerun</option>
          <option value="flaky" ${selected(review?.verdict || "", "flaky")}>Flaky</option>
          <option value="bad-evaluation" ${selected(review?.verdict || "", "bad-evaluation")}>Bad evaluation</option>
        </select>
      </label>
      <label>
        <span>Tags</span>
        <input name="tags" value="${escapeAttribute((review?.tags || []).join(", "))}" placeholder="env, flaky, evaluator" />
      </label>
      <label>
        <span>Note</span>
        <textarea name="note" rows="5" placeholder="Review notes for this run">${escapeHtml(review?.note || "")}</textarea>
      </label>
      <div class="form-actions">
        <button class="primary-button" type="submit">${icon("save")} Save</button>
        ${review ? `<button class="ghost-button" type="button" data-action="clear-review" data-run-id="${escapeAttribute(run.id)}">${icon("x")} Clear</button>` : ""}
      </div>
    </form>
  `;
}

function renderArtifactLink(label, artifact) {
  const path = artifact?.path || "Not available";
  const action = artifact?.asset?.url
    ? `<a href="${escapeAttribute(artifact.asset.url)}" target="_blank" rel="noreferrer">${icon("external")} Open</a>`
    : `<span>Unavailable</span>`;
  return `
    <div class="artifact-link">
      <strong>${escapeHtml(label)}</strong>
      <small title="${escapeAttribute(path)}">${escapeHtml(truncate(path, 64))}</small>
      ${action}
    </div>
  `;
}

function renderModelBubbleChart(items) {
  const data = items.slice(0, 8);
  if (!data.length) {
    return renderInlineEmpty("No model efficiency data available.");
  }
  const width = 760;
  const height = 300;
  const pad = 42;
  const maxLatency = Math.max(...data.map((item) => item.avgLatencySeconds || 0), 1);
  const maxTotal = Math.max(...data.map((item) => item.total || 1), 1);

  return `
    <div class="bubble-chart">
      <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Model success rate versus latency">
        <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" class="axis-line" />
        <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" class="axis-line" />
        <text x="${pad}" y="22" class="chart-label">success</text>
        <text x="${width - 145}" y="${height - 12}" class="chart-label">avg duration</text>
        ${data.map((item, index) => {
          const x = pad + ((item.avgLatencySeconds || 0) / maxLatency) * (width - pad * 2);
          const y = height - pad - clamp(item.successRate || 0, 0, 1) * (height - pad * 2);
          const radius = 10 + ((item.total || 1) / maxTotal) * 20;
          const hue = 210 + index * 18;
          return `
            <g>
              <circle cx="${x}" cy="${y}" r="${radius}" fill="hsl(${hue} 78% 50% / 0.22)" stroke="hsl(${hue} 78% 42%)" stroke-width="2">
                <title>${escapeAttribute(item.label)} - ${percent(item.successRate)} / ${formatSeconds(item.avgLatencySeconds)}</title>
              </circle>
              <text x="${x + radius + 6}" y="${y + 4}" class="bubble-label">${escapeHtml(truncate(item.label, 18))}</text>
            </g>
          `;
        }).join("")}
      </svg>
    </div>
  `;
}

function renderHistogram(bins) {
  if (!bins.length) {
    return renderInlineEmpty("No step histogram data available.");
  }
  const max = Math.max(...bins.map((bin) => bin.count), 1);
  return `
    <div class="histogram">
      ${bins.map((bin) => `
        <div class="histogram-bin">
          <i style="height:${percentUnit(bin.count / max)}"></i>
          <span>${escapeHtml(bin.label)}</span>
          <strong>${escapeHtml(String(bin.count))}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function renderRiskHeatmap(tasks) {
  const items = tasks.slice(0, 18);
  if (!items.length) {
    return renderInlineEmpty("No risk heatmap data available.");
  }
  return `
    <div class="heatmap-grid">
      ${items.map((item) => {
        const risk = clamp(item.risk, 0, 1);
        const style = `--risk:${risk};--risk-border:${0.10 + risk * 0.34};--risk-bg:${0.04 + risk * 0.16};--risk-bg2:${0.03 + risk * 0.12}`;
        return `
        <button class="heatmap-cell" style="${style}" data-action="set-filter" data-filter-key="search" data-filter-value="${escapeAttribute(item.key)}" data-route="#/results">
          <strong title="${escapeAttribute(item.label)}">${escapeHtml(truncate(item.label, 42))}</strong>
          <span>${escapeHtml(`${item.nonPassCount} non-pass`)}</span>
          <small>${escapeHtml(`${item.runCount} runs / ${percent(item.successRate)}`)}</small>
        </button>
      `;
      }).join("")}
    </div>
  `;
}

function renderExecutionScorecards(executions) {
  if (!executions.length) {
    return renderInlineEmpty("No execution scorecards available.");
  }
  return `
    <div class="scorecard-grid">
      ${executions.slice(0, 9).map((execution) => `
        <button class="scorecard" data-action="set-filter" data-filter-key="execution" data-filter-value="${escapeAttribute(execution.id)}" data-route="#/results">
          <span>${escapeHtml(labelPlatform(execution.platform || "unknown"))}</span>
          <strong title="${escapeAttribute(execution.name || "")}">${escapeHtml(truncate(execution.name || "Execution", 46))}</strong>
          <div class="score-line"><i style="width:${percentUnit(execution.successRate || 0)}"></i></div>
          <small>${escapeHtml(`${percent(execution.successRate)} success / ${execution.runCount || 0} runs`)}</small>
        </button>
      `).join("")}
    </div>
  `;
}

function renderKeyValue(label, value, wrap = false) {
  return `
    <div class="key-value ${wrap ? "wrap" : ""}">
      <dt>${escapeHtml(label)}</dt>
      <dd title="${escapeAttribute(value == null ? "" : String(value))}">${escapeHtml(value == null || value === "" ? "--" : String(value))}</dd>
    </div>
  `;
}

function renderJsonDisclosure(title, payload) {
  if (!payload || (typeof payload === "object" && !Object.keys(payload).length)) {
    return "";
  }
  return renderDisclosure(title, JSON.stringify(payload, null, 2));
}

function renderDisclosure(title, text) {
  const id = registerDisclosurePayload(title, text);
  return `
    <button class="disclosure-button" type="button" data-action="open-disclosure" data-disclosure-id="${escapeAttribute(id)}">
      ${icon("external")}
      <span>${escapeHtml(title)}</span>
    </button>
  `;
}

function registerDisclosurePayload(title, text) {
  const id = `disclosure-${state.disclosureSequence += 1}`;
  state.disclosurePayloads.set(id, {
    title: String(title || "Payload"),
    text: String(text || ""),
  });
  return id;
}

function renderModal() {
  if (!state.modal) {
    return "";
  }

  return `
    <div class="modal-layer" role="presentation">
      <button class="modal-scrim" type="button" aria-label="Close payload viewer" data-action="close-modal"></button>
      <section class="payload-modal" role="dialog" aria-modal="true" aria-labelledby="payload-modal-title">
        <header class="payload-modal-header">
          <div>
            <p class="section-label">Payload viewer</p>
            <h2 id="payload-modal-title">${escapeHtml(state.modal.title)}</h2>
          </div>
          <button class="icon-button" type="button" aria-label="Close" data-action="close-modal">${icon("x")}</button>
        </header>
        <pre class="payload-modal-body">${escapeHtml(state.modal.text)}</pre>
      </section>
    </div>
  `;
}

function renderLoadingState(message) {
  return `
    <section class="state-card">
      <div class="loader"></div>
      <h2>Loading workbench</h2>
      <p>${escapeHtml(message)}</p>
    </section>
  `;
}

function renderErrorState(message) {
  return `
    <section class="state-card error">
      <h2>Unable to load data</h2>
      <p>${escapeHtml(message)}</p>
      <button class="primary-button" data-action="refresh">${icon("refresh")} Try again</button>
    </section>
  `;
}

function renderEmptyState(message) {
  return `
    <section class="state-card">
      <h2>No data available</h2>
      <p>${escapeHtml(message)}</p>
    </section>
  `;
}

function renderInlineEmpty(message) {
  return `<div class="inline-empty">${escapeHtml(message)}</div>`;
}

function getFilteredRuns() {
  const runs = state.workspace?.runs || [];
  const search = state.filters.search.trim().toLowerCase();
  return runs.filter((run) => {
    if (state.filters.platform && run.platform !== state.filters.platform) {
      return false;
    }
    if (state.filters.model !== "all" && run.modelId !== state.filters.model) {
      return false;
    }
    if (state.filters.status === "pass" && run.status !== "PASS") {
      return false;
    }
    if (state.filters.status === "nonpass" && run.status === "PASS") {
      return false;
    }
    if (state.filters.category !== "all" && getRunCategory(run) !== state.filters.category) {
      return false;
    }
    if (state.filters.execution !== "all" && run.execution?.id !== state.filters.execution) {
      return false;
    }
    if (!search) {
      return true;
    }
    const haystack = [
      run.title,
      run.taskLabel,
      run.taskId,
      run.modelName,
      run.modelId,
      run.platform,
      run.execution?.name,
      run.failureMessage,
      getRunCategory(run),
      run.paths?.runDir,
    ].filter(Boolean).join(" ").toLowerCase();
    return haystack.includes(search);
  });
}

function getSortedRuns(runs) {
  const sorted = [...runs];
  if (state.sort === "risk") {
    return sorted.sort((left, right) => Number(right.success === false) - Number(left.success === false) || (right.sortTimestamp || 0) - (left.sortTimestamp || 0));
  }
  if (state.sort === "steps") {
    return sorted.sort((left, right) => (right.stepsTaken || 0) - (left.stepsTaken || 0));
  }
  if (state.sort === "duration") {
    return sorted.sort((left, right) => (right.latencyMs || 0) - (left.latencyMs || 0));
  }
  return sorted.sort((left, right) => (right.sortTimestamp || 0) - (left.sortTimestamp || 0));
}

function getExecutionsInScope(runs) {
  const ids = new Set(runs.map((run) => run.execution?.id).filter(Boolean));
  return (state.workspace?.executions || [])
    .filter((execution) => ids.has(execution.id))
    .sort((left, right) => (right.sortTimestamp || 0) - (left.sortTimestamp || 0));
}

function buildScopeStats(runs, executions) {
  const passCount = runs.filter((run) => run.status === "PASS").length;
  const failCount = runs.filter((run) => run.status === "FAIL").length;
  const errorCount = runs.filter((run) => run.status === "ERROR").length;
  const steps = runs.map((run) => run.stepsTaken).filter(isFiniteNumber);
  const latencies = runs.map((run) => run.latencyMs).filter(isFiniteNumber);
  return {
    runCount: runs.length,
    executionCount: executions.length,
    taskCount: new Set(runs.map((run) => run.taskId).filter(Boolean)).size,
    modelCount: new Set(runs.map((run) => run.modelId).filter(Boolean)).size,
    passCount,
    failCount,
    errorCount,
    nonPassCount: failCount + errorCount,
    successRate: runs.length ? passCount / runs.length : 0,
    averageSteps: steps.length ? steps.reduce((sum, value) => sum + value, 0) / steps.length : 0,
    averageLatencySeconds: latencies.length ? (latencies.reduce((sum, value) => sum + value, 0) / latencies.length) / 1000 : 0,
  };
}

function buildModelStats(runs) {
  const map = new Map();
  for (const run of runs) {
    const key = run.modelId || run.modelName || "unknown";
    const entry = map.get(key) || { value: key, label: run.modelName || run.modelId || "unknown", total: 0, success: 0, latency: 0, latencyCount: 0 };
    entry.total += 1;
    entry.success += run.success ? 1 : 0;
    if (isFiniteNumber(run.latencyMs)) {
      entry.latency += run.latencyMs;
      entry.latencyCount += 1;
    }
    map.set(key, entry);
  }
  return Array.from(map.values())
    .map((entry) => ({
      ...entry,
      successRate: entry.total ? entry.success / entry.total : 0,
      avgLatencySeconds: entry.latencyCount ? (entry.latency / entry.latencyCount) / 1000 : 0,
    }))
    .sort((left, right) => right.total - left.total || right.successRate - left.successRate);
}

function buildAppStats(runs) {
  const map = new Map();
  for (const run of runs) {
    const key = getRunCategory(run);
    const entry = map.get(key) || { value: key, label: key, total: 0, success: 0 };
    entry.total += 1;
    entry.success += run.success ? 1 : 0;
    map.set(key, entry);
  }
  return Array.from(map.values())
    .map((entry) => ({ ...entry, successRate: entry.total ? entry.success / entry.total : 0 }))
    .sort((left, right) => right.total - left.total || left.label.localeCompare(right.label));
}

function buildTaskRiskStats(runs) {
  const map = new Map();
  for (const run of runs) {
    const key = run.taskId || run.id;
    const entry = map.get(key) || { key, label: friendlyTaskName(run), runCount: 0, successCount: 0, nonPassCount: 0 };
    entry.runCount += 1;
    entry.successCount += run.success ? 1 : 0;
    entry.nonPassCount += run.success ? 0 : 1;
    map.set(key, entry);
  }
  return Array.from(map.values())
    .map((entry) => ({
      ...entry,
      successRate: entry.runCount ? entry.successCount / entry.runCount : 0,
      risk: entry.runCount ? entry.nonPassCount / entry.runCount : 0,
    }))
    .sort((left, right) => right.risk - left.risk || right.nonPassCount - left.nonPassCount || right.runCount - left.runCount);
}

function buildStepHistogram(runs) {
  const ranges = [
    { min: 0, max: 5, label: "0-5" },
    { min: 6, max: 15, label: "6-15" },
    { min: 16, max: 30, label: "16-30" },
    { min: 31, max: 60, label: "31-60" },
    { min: 61, max: 100, label: "61-100" },
    { min: 101, max: Infinity, label: "100+" },
  ];
  return ranges.map((range) => ({
    ...range,
    count: runs.filter((run) => (run.stepsTaken || 0) >= range.min && (run.stepsTaken || 0) <= range.max).length,
  }));
}

function buildReviewStats(runs) {
  const queue = runs.filter((run) => !run.success || getReviewRecord(run.id));
  const reviewed = queue.filter((run) => getReviewRecord(run.id)).length;
  return {
    queue: queue.length,
    reviewed,
    coverage: queue.length ? reviewed / queue.length : 0,
  };
}

function getPendingReviewRuns(runs) {
  return runs
    .filter((run) => !run.success && !getReviewRecord(run.id))
    .sort((left, right) => (right.sortTimestamp || 0) - (left.sortTimestamp || 0));
}

function getFrames(run) {
  if (!run) {
    return [];
  }

  const steps = (run.steps || []).map((step) => ({
    kind: "step",
    label: `Step ${step.index}`,
    shortLabel: step.actionParse?.action?.type || `step ${step.index}`,
    badge: String(step.index || "?"),
    screenshot: step.screenshot,
    observation: step.observation,
    action: {
      type: step.actionParse?.action?.type,
      payload: step.actionParse?.action,
      parseStatus: step.actionParse?.status,
      execution: step.actionExecution,
    },
    outcome: {
      executionStatus: step.actionExecution?.status || "--",
      message: step.actionExecution?.result || step.actionExecution?.error || step.actionParse?.error || "",
    },
    latencies: {
      stepMs: step.latencyMs,
    },
    prompt: step.prompt,
    llmResponse: step.llmResponse,
    llmReasoning: step.llmReasoning,
    timestamp: step.timestamp,
  }));

  if (run.finalObservation?.screenshot || run.finalAsset || run.finalObservation) {
    steps.push({
      kind: "final",
      label: "Final state",
      shortLabel: run.success ? "pass" : "terminal",
      badge: "F",
      screenshot: run.finalAsset || run.finalObservation?.screenshot,
      observation: run.finalObservation,
    });
  }
  return steps;
}

function getModelOptions() {
  return [
    { value: "all", label: "All models" },
    ...((state.workspace?.facets?.models || []).map((item) => ({ value: item.value, label: `${item.value} (${item.count})` }))),
  ];
}

function getStatusOptions() {
  return [
    { value: "all", label: "All statuses" },
    { value: "pass", label: "Pass only" },
    { value: "nonpass", label: "Non-pass" },
  ];
}

function getCategoryOptions() {
  return [
    { value: "all", label: "All areas" },
    ...buildAppStats(state.workspace?.runs || []).map((item) => ({ value: item.value, label: `${item.label} (${item.total})` })),
  ];
}

function getExecutionOptions() {
  return [
    { value: "all", label: "All executions" },
    ...((state.workspace?.executions || []).map((item) => ({ value: item.id, label: truncate(item.name || "Execution", 42) }))),
  ];
}

function getRunCategory(run) {
  if (run.appName) {
    return titleCase(String(run.appName));
  }
  const parts = String(run.taskId || "").split(".");
  if (parts.length >= 2 && parts[1]) {
    return titleCase(parts[1].replace(/_/g, " "));
  }
  return "Platform";
}

function friendlyTaskName(run) {
  const parts = String(run.taskId || "").split(".");
  const raw = parts.length > 2 ? parts.slice(2).join(" ") : String(run.taskId || run.taskLabel || run.title || "Untitled run");
  return titleCase(raw.replace(/[_-]/g, " "));
}

function instructionText(run) {
  const label = String(run.taskLabel || run.title || "").trim();
  const taskId = String(run.taskId || "").trim();
  if (!label || label === taskId || /^(ios|macos|linux|windows|android)\./i.test(label)) {
    return "";
  }
  return label;
}

function uniqueText(...values) {
  return Array.from(
    new Set(
      values
        .map((value) => String(value || "").trim())
        .filter(Boolean),
    ),
  );
}

function parseRoute() {
  const hash = window.location.hash.replace(/^#\/?/, "");
  const parts = hash.split("/").filter(Boolean);
  if (!parts.length) {
    return { name: "module", module: "overview" };
  }
  if (parts[0] === "runs" && parts[1]) {
    return { name: "run", runId: decodeURIComponent(parts[1]) };
  }
  if (["overview", "results", "analysis"].includes(parts[0])) {
    return { name: "module", module: parts[0] };
  }
  if (parts[0] === "analytics") {
    return { name: "module", module: "analysis" };
  }
  return { name: "module", module: "overview" };
}

function activeModuleId() {
  if (state.route.name === "run") {
    return "results";
  }
  return state.route.module || "overview";
}

function moduleTitle(moduleId) {
  if (moduleId === "results") {
    return "Results";
  }
  if (moduleId === "analysis") {
    return "Analysis";
  }
  return "Overview";
}

function moduleKicker(moduleId) {
  if (moduleId === "results") {
    return "Run browser";
  }
  if (moduleId === "analysis") {
    return "Benchmark signals";
  }
  return "Command center";
}

function labelPlatform(value) {
  const normalized = String(value || "unknown").toLowerCase();
  if (normalized === "ios") {
    return "iOS";
  }
  if (normalized === "macos") {
    return "macOS";
  }
  return titleCase(String(value || "unknown"));
}

function normalizeStatusLabel(status) {
  const normalized = String(status || "UNKNOWN").toUpperCase();
  if (normalized === "PASS") {
    return "Pass";
  }
  if (normalized === "FAIL") {
    return "Fail";
  }
  if (normalized === "ERROR") {
    return "Error";
  }
  return titleCase(normalized.toLowerCase());
}

function reviewStateLabel(run) {
  if (getReviewRecord(run.id)) {
    return "Reviewed";
  }
  if (!run.success) {
    return "Pending";
  }
  return "Not needed";
}

function reviewVerdictLabel(verdict) {
  const labels = {
    "confirmed-pass": "Confirmed pass",
    "confirmed-fail": "Confirmed fail",
    "needs-rerun": "Needs rerun",
    flaky: "Flaky",
    "bad-evaluation": "Bad evaluation",
  };
  return labels[verdict] || titleCase(String(verdict || "reviewed").replace(/[-_]/g, " "));
}

function toneForStatus(status) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "PASS") {
    return "success";
  }
  if (normalized === "FAIL") {
    return "danger";
  }
  if (normalized === "ERROR") {
    return "warning";
  }
  return "neutral";
}

function toneForVerdict(verdict) {
  if (verdict === "confirmed-pass") {
    return "success";
  }
  if (verdict === "confirmed-fail" || verdict === "bad-evaluation") {
    return "danger";
  }
  if (verdict === "needs-rerun" || verdict === "flaky") {
    return "warning";
  }
  return "muted";
}

function loadReviews() {
  try {
    const payload = JSON.parse(window.localStorage.getItem(REVIEW_STORAGE_KEY) || "{}");
    return payload && typeof payload === "object" ? payload : {};
  } catch {
    return {};
  }
}

function saveReviews() {
  window.localStorage.setItem(REVIEW_STORAGE_KEY, JSON.stringify(state.reviews));
}

function getReviewRecord(runId) {
  return state.reviews[runId] || null;
}

function upsertReviewRecord(runId, payload) {
  state.reviews[runId] = payload;
  saveReviews();
}

function deleteReviewRecord(runId) {
  delete state.reviews[runId];
  saveReviews();
}

function icon(name) {
  const paths = {
    dashboard: '<path d="M3 13h8V3H3v10Z"/><path d="M13 21h8V11h-8v10Z"/><path d="M13 3v6h8V3h-8Z"/><path d="M3 21h8v-6H3v6Z"/>',
    table: '<path d="M4 5h16v14H4z"/><path d="M4 10h16"/><path d="M10 5v14"/>',
    chart: '<path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 16l3-5 3 2 4-7"/>',
    bolt: '<path d="M13 2 4 14h7l-1 8 9-12h-7l1-8Z"/>',
    phone: '<path d="M8 2h8a2 2 0 0 1 2 2v16a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2Z"/><path d="M10 18h4"/>',
    refresh: '<path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v6h-6"/>',
    search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
    filter: '<path d="M4 5h16"/><path d="M7 12h10"/><path d="M10 19h4"/>',
    rotate: '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 3v6h6"/>',
    arrowRight: '<path d="M5 12h14"/><path d="m13 5 7 7-7 7"/>',
    arrowLeft: '<path d="M19 12H5"/><path d="m11 5-7 7 7 7"/>',
    chevronLeft: '<path d="m15 18-6-6 6-6"/>',
    chevronRight: '<path d="m9 18 6-6-6-6"/>',
    play: '<path d="M8 5v14l11-7-11-7Z"/>',
    pause: '<path d="M8 5h3v14H8z"/><path d="M15 5h3v14h-3z"/>',
    save: '<path d="M5 3h12l2 2v16H5z"/><path d="M8 3v6h8"/><path d="M8 21v-7h8v7"/>',
    x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    external: '<path d="M14 3h7v7"/><path d="M10 14 21 3"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/>',
  };
  return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${paths[name] || paths.dashboard}</svg>`;
}

function titleCase(value) {
  return String(value || "")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .map((part) => part ? part[0].toUpperCase() + part.slice(1) : "")
    .join(" ");
}

function truncate(value, limit) {
  const text = String(value || "");
  return text.length > limit ? `${text.slice(0, limit - 1)}...` : text;
}

function percent(value) {
  if (!isFiniteNumber(value)) {
    return "--";
  }
  return `${Math.round(clamp(value, 0, 1) * 100)}%`;
}

function percentUnit(value) {
  return `${Math.round(clamp(value, 0, 1) * 100)}%`;
}

function formatNumber(value) {
  if (!isFiniteNumber(value)) {
    return "--";
  }
  return value % 1 === 0 ? String(value) : value.toFixed(1);
}

function formatMs(value) {
  if (!isFiniteNumber(value)) {
    return "--";
  }
  if (value < 1000) {
    return `${Math.round(value)} ms`;
  }
  return formatSeconds(value / 1000);
}

function formatSeconds(value) {
  if (!isFiniteNumber(value)) {
    return "--";
  }
  if (value >= 60) {
    const minutes = Math.floor(value / 60);
    const seconds = Math.round(value % 60);
    return `${minutes}m ${seconds}s`;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)}s`;
}

function formatDateTime(value) {
  if (!value) {
    return "--";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function median(values) {
  if (!values.length) {
    return 0;
  }
  const sorted = [...values].sort((left, right) => left - right);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, Number(value) || 0));
}

function isFiniteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function selected(value, expected) {
  return String(value) === String(expected) ? "selected" : "";
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}
