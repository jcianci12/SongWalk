(function () {
  // Increment this whenever we need to confirm a fresh JS build is running in the browser.
  const SCRIPT_VERSION = "2026-04-22-album-drag-drop-1";
  const DEBUG_FILTERING = true;

  function debugLog(scope, ...details) {
    if (!DEBUG_FILTERING || !window.console || typeof window.console.log !== "function") {
      return;
    }

    window.console.log(`[Songshare ${SCRIPT_VERSION}] ${scope}`, ...details);
  }

  window.__SONGWALK_SCRIPT_VERSION = SCRIPT_VERSION;
  debugLog("boot", { href: window.location.href });

  function resolveLibraryTarget(rawValue) {
    const value = (rawValue || "").trim();
    if (!value) {
      return "";
    }

    const uuidMatch = value.match(/[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}/i);
    return uuidMatch ? uuidMatch[0] : "";
  }

  function formatTime(seconds) {
    if (!Number.isFinite(seconds) || seconds < 0) {
      return "0:00";
    }

    const minutes = Math.floor(seconds / 60);
    const remainder = Math.floor(seconds % 60);
    return `${minutes}:${String(remainder).padStart(2, "0")}`;
  }

  function formatBytes(bytes) {
    if (!Number.isFinite(bytes) || bytes < 0) {
      return "0 B";
    }

    const units = ["B", "KB", "MB", "GB"];
    let amount = bytes;
    let unitIndex = 0;
    while (amount >= 1024 && unitIndex < units.length - 1) {
      amount /= 1024;
      unitIndex += 1;
    }

    const precision = unitIndex === 0 ? 0 : 1;
    return `${amount.toFixed(precision)} ${units[unitIndex]}`;
  }

  function nextFrame() {
    return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function initialsFromText(value) {
    return (value || "")
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0].toUpperCase())
      .join("") || "SS";
  }

  function setArtFrame(node, coverUrl, fallbackText) {
    if (!node) {
      return;
    }

    if (coverUrl) {
      node.innerHTML = `<img src="${escapeHtml(coverUrl)}" alt="Album cover art">`;
      return;
    }

    node.textContent = fallbackText || "SS";
  }

  function faviconDataUri(label) {
    const text = encodeURIComponent((label || "SS").slice(0, 2).toUpperCase());
    return `data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='12' fill='%232c82d3'/%3E%3Ctext x='32' y='41' text-anchor='middle' font-size='24' fill='white' font-family='Segoe UI, Arial, sans-serif'%3E${text}%3C/text%3E%3C/svg%3E`;
  }

  function ensureFaviconLink() {
    let icon = document.querySelector("link[data-dynamic-favicon]");
    if (icon) {
      return icon;
    }

    icon = document.createElement("link");
    icon.setAttribute("rel", "icon");
    icon.setAttribute("data-dynamic-favicon", "true");
    document.head.appendChild(icon);
    return icon;
  }

  function setFaviconFrame(coverUrl, fallbackText) {
    const icon = ensureFaviconLink();
    icon.setAttribute("href", coverUrl || faviconDataUri(fallbackText));
  }

  const globalBusy = document.getElementById("global-busy");
  const globalBusyText = document.getElementById("global-busy-text");
  let busyDepth = 0;

  function showGlobalBusy(message) {
    if (!globalBusy) {
      return () => {};
    }

    busyDepth += 1;
    globalBusy.hidden = false;
    document.body.classList.add("is-busy");
    if (globalBusyText) {
      globalBusyText.textContent = message || "Working...";
    }

    let released = false;
    return () => {
      if (released) {
        return;
      }

      released = true;
      busyDepth = Math.max(0, busyDepth - 1);
      if (busyDepth === 0) {
        globalBusy.hidden = true;
        document.body.classList.remove("is-busy");
        if (globalBusyText) {
          globalBusyText.textContent = "Working...";
        }
      }
    };
  }

  async function withGlobalBusy(message, work) {
    const release = showGlobalBusy(message);
    try {
      return await work();
    } finally {
      release();
    }
  }

  function bindCopyButton(button) {
    if (!button || button.dataset.copyBound === "1") {
      return;
    }

    button.dataset.copyBound = "1";
    button.addEventListener("click", async () => {
      const value = button.getAttribute("data-copy");
      if (!value) {
        return;
      }

      await navigator.clipboard.writeText(value);
      const original = button.textContent;
      button.textContent = "Copied";
      window.setTimeout(() => {
        button.textContent = original;
      }, 1200);
    });
  }

  function setButtonCopyValue(button, value) {
    if (!button) {
      return;
    }

    const normalized = (value || "").trim();
    if (normalized) {
      button.disabled = false;
      button.setAttribute("data-copy", normalized);
      return;
    }

    button.disabled = true;
    button.removeAttribute("data-copy");
  }

  document.querySelectorAll("[data-copy]").forEach((button) => {
    bindCopyButton(button);
  });

  function applyQuickTunnelState(panel, tunnel) {
    if (!panel || !tunnel) {
      return;
    }

    const statusNode = panel.querySelector("[data-quick-tunnel-status]");
    const publicUrlNode = panel.querySelector("[data-quick-tunnel-public-url]");
    const ownerUrlNode = panel.querySelector("[data-quick-tunnel-owner-url]");
    const copyPublicButton = panel.querySelector("[data-copy-quick-tunnel-url]");
    const copyOwnerButton = panel.querySelector("[data-copy-quick-tunnel-owner-url]");
    const toggleButton = panel.querySelector("[data-toggle-quick-tunnel]");
    const rotateButton = panel.querySelector("[data-rotate-quick-tunnel]");

    if (statusNode) {
      statusNode.textContent = tunnel.message || tunnel.last_error || "Quick Tunnel is idle.";
    }
    if (publicUrlNode) {
      publicUrlNode.textContent = tunnel.public_url || "Quick Tunnel is offline.";
    }
    if (ownerUrlNode) {
      ownerUrlNode.textContent = tunnel.public_owner_url || "Bring the tunnel online to get a public owner URL.";
    }

    setButtonCopyValue(copyPublicButton, tunnel.public_url || "");
    setButtonCopyValue(copyOwnerButton, tunnel.public_owner_url || "");
    bindCopyButton(copyPublicButton);
    bindCopyButton(copyOwnerButton);

    if (toggleButton) {
      toggleButton.disabled = !tunnel.enabled;
      toggleButton.textContent = tunnel.running ? "Take SongWalk offline" : "Bring SongWalk online";
    }

    if (rotateButton) {
      rotateButton.disabled = !(tunnel.enabled && tunnel.running);
    }
  }

  function shouldPollQuickTunnel(tunnel) {
    return Boolean(tunnel && tunnel.enabled && tunnel.running && !tunnel.public_url);
  }

  document.querySelectorAll("[data-quick-tunnel-panel]").forEach((panel) => {
    const statusUrl = panel.getAttribute("data-status-url");
    const toggleUrl = panel.getAttribute("data-toggle-url");
    const rotateUrl = panel.getAttribute("data-rotate-url");
    const toggleButton = panel.querySelector("[data-toggle-quick-tunnel]");
    const rotateButton = panel.querySelector("[data-rotate-quick-tunnel]");
    let pollTimer = null;
    let latestTunnel = {
      enabled: toggleButton ? !toggleButton.disabled : false,
      running: rotateButton ? !rotateButton.disabled : false,
      public_url: panel.querySelector("[data-quick-tunnel-public-url]")?.textContent || "",
    };

    async function refreshTunnel(url, busyMessage = "") {
      const release = busyMessage ? showGlobalBusy(busyMessage) : () => {};
      try {
        const response = await fetch(url, {
          method: url === statusUrl ? "GET" : "POST",
          headers: {
            Accept: "application/json",
            "X-Requested-With": "fetch",
          },
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || "Could not update the Quick Tunnel.");
        }

        latestTunnel = payload.tunnel || {};
        applyQuickTunnelState(panel, latestTunnel);
        schedulePoll();
      } finally {
        release();
      }
    }

    function schedulePoll() {
      if (!statusUrl) {
        return;
      }

      if (!shouldPollQuickTunnel(latestTunnel)) {
        if (pollTimer) {
          window.clearInterval(pollTimer);
          pollTimer = null;
        }
        return;
      }

      if (pollTimer) {
        return;
      }

      pollTimer = window.setInterval(async () => {
        if (!shouldPollQuickTunnel(latestTunnel)) {
          window.clearInterval(pollTimer);
          pollTimer = null;
          return;
        }

        try {
          await refreshTunnel(statusUrl);
        } catch (_) {
          // Ignore transient tunnel polling failures.
        }
      }, 2000);
    }

    if (toggleButton && toggleUrl) {
      toggleButton.addEventListener("click", async () => {
        const busyMessage = latestTunnel.running ? "Taking SongWalk offline..." : "Bringing SongWalk online...";
        try {
          await refreshTunnel(toggleUrl, busyMessage);
        } catch (error) {
          window.alert(error instanceof Error ? error.message : "Could not change the Quick Tunnel state.");
        }
      });
    }

    if (rotateButton && rotateUrl) {
      rotateButton.addEventListener("click", async () => {
        try {
          await refreshTunnel(rotateUrl, "Rotating public tunnel...");
        } catch (error) {
          window.alert(error instanceof Error ? error.message : "Could not rotate the Quick Tunnel.");
        }
      });
    }

    schedulePoll();
  });

  document.querySelectorAll("[data-delete-library-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();

      const libraryLabel = form.getAttribute("data-library-label") || "this library";
      if (!window.confirm(`Delete library ${libraryLabel}? This removes all tracks and cover art in it.`)) {
        return;
      }

      try {
        const { response, payload } = await withGlobalBusy("Deleting library...", async () => {
          const response = await fetch(form.action, {
            method: "POST",
            headers: {
              Accept: "application/json",
              "X-Requested-With": "fetch",
            },
          });

          let payload = {};
          try {
            payload = await response.json();
          } catch (_) {
            payload = {};
          }

          return { response, payload };
        });

        if (!response.ok || !payload.ok) {
          throw new Error((payload && payload.error) || "Could not delete library.");
        }

        window.location.href = payload.redirect_url || form.getAttribute("data-redirect-url") || "/";
      } catch (error) {
        window.alert(error instanceof Error ? error.message : "Could not delete library.");
      }
    });
  });

  const openShareForm = document.querySelector("[data-open-share]");
  if (openShareForm) {
    openShareForm.addEventListener("submit", (event) => {
      event.preventDefault();
      const input = openShareForm.querySelector("input[name='target']");
      const libraryId = resolveLibraryTarget(input.value);
      if (!libraryId) {
        input.focus();
        return;
      }

      window.location.href = `/s/${libraryId}`;
    });
  }

  const remoteImportShell = document.querySelector("[data-remote-import-shell]");
  const remoteImportPhase = document.querySelector("[data-remote-import-phase]");
  const remoteImportDetail = document.querySelector("[data-remote-import-detail]");
  const remoteImportProgress = document.querySelector("[data-remote-import-progress]");
  const remoteImportBar = document.querySelector("[data-remote-import-bar]");
  const remoteImportCopy = document.querySelector("[data-remote-import-copy]");
  const sharedLibraryStateUrl = document.body ? (document.body.getAttribute("data-library-state-url") || "") : "";
  let libraryLiveRegion = document.querySelector("[data-library-live-region]");
  let currentLibraryTrackCount = Number.parseInt(document.body?.getAttribute("data-library-track-count") || "0", 10);
  let currentLibraryUpdatedAt = document.body?.getAttribute("data-library-updated-at") || "";
  let sharedLibraryStateTimer = null;
  let isReloadingForSharedLibraryState = false;

  function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function setRemoteImportStatus({ visible = false, phase = "", detail = "", percent = null } = {}) {
    if (!remoteImportShell) {
      return;
    }

    remoteImportShell.hidden = !visible;
    if (remoteImportPhase) {
      remoteImportPhase.textContent = phase || "Working...";
    }
    if (remoteImportDetail) {
      remoteImportDetail.textContent = detail || "";
    }

    if (!remoteImportProgress || !remoteImportBar || !remoteImportCopy) {
      return;
    }

    if (typeof percent === "number") {
      remoteImportProgress.hidden = false;
      remoteImportBar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
      remoteImportBar.classList.remove("is-indeterminate");
      remoteImportCopy.textContent = `${Math.max(0, Math.min(100, percent))}%`;
      return;
    }

    remoteImportProgress.hidden = false;
    remoteImportBar.style.width = "100%";
    remoteImportBar.classList.add("is-indeterminate");
    remoteImportCopy.textContent = "Working...";
  }

  function refreshLibraryNodeLists() {
    libraryLiveRegion = document.querySelector("[data-library-live-region]");
    rows = Array.from(document.querySelectorAll("[data-track-row]"));
    albumContainers = Array.from(document.querySelectorAll("[data-album-container]"));
    albumCards = Array.from(document.querySelectorAll("[data-album-card]:not([data-collection-card])"));
    collectionCards = Array.from(document.querySelectorAll("[data-collection-card]"));
    collectionTrackSections = Array.from(document.querySelectorAll("[data-collection-track-section]"));
    collectionTrackAlbums = Array.from(document.querySelectorAll("[data-collection-track-album]"));
    albumDropTargets = Array.from(document.querySelectorAll("[data-drop-album-target]"));
    selectableAlbums = Array.from(document.querySelectorAll("[data-selectable-album]"));
    albumSelectButtons = Array.from(document.querySelectorAll("[data-album-select]"));
    collectionSelectionForms = Array.from(document.querySelectorAll("[data-collection-selection-form]"));
    collectionSelectionSummaries = Array.from(document.querySelectorAll("[data-collection-selection-summary]"));
    filterInput = document.querySelector("[data-track-filter]");
    targetAlbumSection = document.querySelector("[data-target-album-section]");
  }

  function snapshotLibraryUiState() {
    return {
      selectedRowId: trackStateFromRow(selectedRow)?.id || "",
      selectedRowIds: selectedRows.map((row) => trackStateFromRow(row)?.id || "").filter(Boolean),
      selectionAnchorId: trackStateFromRow(selectionAnchorRow)?.id || "",
      playbackRowId: trackStateFromRow(currentPlaybackRow())?.id || "",
      filterValue: filterInput ? filterInput.value : "",
      filterHadFocus: Boolean(filterInput && document.activeElement === filterInput),
      editorOpen: Boolean(toggleEditorButton && toggleEditorButton.getAttribute("aria-expanded") === "true"),
      selectionPanelOpen: Boolean(toggleSelectionPanelButton && toggleSelectionPanelButton.getAttribute("aria-expanded") === "true"),
    };
  }

  function restoreLibraryUiState(state = {}) {
    selectedRows = (state.selectedRowIds || [])
      .map((trackId) => findRowByTrackId(trackId))
      .filter(Boolean);
    selectedRow = findRowByTrackId(state.selectedRowId) || selectedRows[selectedRows.length - 1] || null;
    setSelectionAnchor(findRowByTrackId(state.selectionAnchorId) || selectedRow || null);
    setPlaybackRow(findRowByTrackId(state.playbackRowId));

    if (filterInput) {
      filterInput.value = state.filterValue || "";
    }

    if (filterInput && rows.length) {
      applySearchFilter(filterInput.value);
    } else if (rows.length) {
      syncSelectionToVisibleRows();
    } else {
      setEditorEnabled(false);
      renderSelection(false);
    }

    if (state.selectionPanelOpen && selectedRows.length === 1) {
      setTransportSelectionOpen(true);
    }

    if (state.editorOpen && selectedRows.length === 1 && toggleEditorButton && !toggleEditorButton.disabled) {
      setEditorAccordionOpen(true);
    }

    if (state.filterHadFocus && filterInput) {
      try {
        filterInput.focus({ preventScroll: true });
      } catch (_) {
        filterInput.focus();
      }
    }
  }

  function clearPlayerSource() {
    if (!player) {
      return;
    }

    player.pause();
    player.removeAttribute("src");
    player.load();
    player.currentTime = 0;
    setPlaybackRow(null);
    syncTransportProgress();
    updateMediaSessionPositionState();
    updatePlayButton();
    syncDocumentTitle();
    syncMediaSession();
  }

  async function refreshSharedLibraryContent(nextTrackCount, nextUpdatedAt, preservedState = null) {
    if (!libraryLiveRegion) {
      return false;
    }

    const previousState = preservedState || snapshotLibraryUiState();
    cancelInlineEdit();
    hideContextMenu();
    clearCurrentTrackDrag();
    const response = await fetch(window.location.href, {
      cache: "no-store",
      headers: {
        Accept: "text/html",
        "X-Requested-With": "fetch",
      },
    });

    if (!response.ok) {
      return false;
    }

    const nextDocument = new DOMParser().parseFromString(await response.text(), "text/html");
    const nextRegion = nextDocument.querySelector("[data-library-live-region]");
    if (!nextRegion) {
      return false;
    }

    libraryLiveRegion.replaceWith(nextRegion);
    refreshLibraryNodeLists();
    bindLibraryContent({ selectDefault: false, scrollToTarget: false });
    restoreLibraryUiState(previousState);

    const bodyTrackCount = Number.parseInt(nextDocument.body?.getAttribute("data-library-track-count") || String(nextTrackCount || 0), 10);
    currentLibraryTrackCount = Number.isFinite(bodyTrackCount) ? bodyTrackCount : nextTrackCount;
    currentLibraryUpdatedAt = nextDocument.body?.getAttribute("data-library-updated-at") || nextUpdatedAt || "";

    if (document.body) {
      document.body.setAttribute("data-library-track-count", String(currentLibraryTrackCount || 0));
      document.body.setAttribute("data-library-updated-at", currentLibraryUpdatedAt || "");
    }

    return true;
  }

  async function refreshLibraryAfterMutation({ selectedTrackIds = null, selectedTrackId = null, selectionAnchorId = null, deletedTrackIds = [] } = {}) {
    const preservedState = snapshotLibraryUiState();
    if (Array.isArray(selectedTrackIds)) {
      preservedState.selectedRowIds = selectedTrackIds.filter(Boolean);
    }
    if (typeof selectedTrackId === "string") {
      preservedState.selectedRowId = selectedTrackId;
    }
    if (typeof selectionAnchorId === "string") {
      preservedState.selectionAnchorId = selectionAnchorId;
    }

    const deletedIds = Array.isArray(deletedTrackIds) ? deletedTrackIds.filter(Boolean) : [];
    if (deletedIds.includes(preservedState.playbackRowId)) {
      clearPlayerSource();
      preservedState.playbackRowId = "";
    }
    if (deletedIds.includes(preservedState.selectedRowId)) {
      preservedState.selectedRowId = "";
    }
    if (deletedIds.length) {
      preservedState.selectedRowIds = preservedState.selectedRowIds.filter((trackId) => !deletedIds.includes(trackId));
      if (deletedIds.includes(preservedState.selectionAnchorId)) {
        preservedState.selectionAnchorId = "";
      }
    }

    const refreshed = await refreshSharedLibraryContent(undefined, undefined, preservedState);
    if (!refreshed) {
      window.location.reload();
    }
    return refreshed;
  }

  async function pollSharedLibraryState() {
    if (!sharedLibraryStateUrl || isReloadingForSharedLibraryState) {
      return;
    }

    try {
      const response = await fetch(sharedLibraryStateUrl, {
        cache: "no-store",
        headers: {
          Accept: "application/json",
          "X-Requested-With": "fetch",
        },
      });

      if (!response.ok) {
        return;
      }

      const payload = await response.json();
      const libraryState = payload.library || {};
      const importJob = payload.import_job || {};
      const nextTrackCount = Number.parseInt(String(libraryState.track_count || 0), 10);
      const nextUpdatedAt = libraryState.updated_at || "";

      if (payload.import_active) {
        setRemoteImportStatus({
          visible: true,
          phase: importJob.message || "Importing...",
          detail: importJob.current_item || importJob.status || "",
          percent: typeof importJob.percent === "number" ? importJob.percent : null,
        });
      } else if (remoteImportShell) {
        remoteImportShell.hidden = true;
      }

      if (nextTrackCount !== currentLibraryTrackCount || (nextUpdatedAt && nextUpdatedAt !== currentLibraryUpdatedAt)) {
        isReloadingForSharedLibraryState = true;
        try {
          const refreshed = await refreshSharedLibraryContent(nextTrackCount, nextUpdatedAt);
          if (!refreshed) {
            window.location.reload();
          }
        } finally {
          isReloadingForSharedLibraryState = false;
        }
        return;
      }
    } catch (_) {
      // Ignore transient shared state polling failures.
    }
  }

  async function startRemoteImport(form, sourceUrlOverride = "") {
    const submitButton = form.querySelector("button[type='submit']");
    const busyMessage = form.getAttribute("data-busy-message") || "Importing...";
    const sourceInput = form.querySelector("[data-import-url-input]");
    const sourceValue = sourceUrlOverride || (sourceInput ? sourceInput.value.trim() : "");

    if (sourceInput && sourceUrlOverride) {
      sourceInput.value = sourceUrlOverride;
    }

    if (!sourceValue) {
      if (sourceInput) {
        sourceInput.focus();
      }
      return;
    }

    if (submitButton) {
      submitButton.disabled = true;
    }

    try {
      setRemoteImportStatus({
        visible: true,
        phase: busyMessage,
        detail: "Submitting import job...",
        percent: null,
      });

      const response = await fetch(form.action, {
        method: form.method || "POST",
        body: new FormData(form),
        headers: {
          Accept: "application/json",
          "X-Requested-With": "fetch",
        },
      });

      let payload = {};
      try {
        payload = await response.json();
      } catch (_) {
        payload = {};
      }

      if (!response.ok || !payload.ok) {
        throw new Error((payload.errors && payload.errors[0]) || payload.error || "Import failed.");
      }

      while (payload.status_url) {
        const statusResponse = await fetch(payload.status_url, {
          headers: {
            Accept: "application/json",
            "X-Requested-With": "fetch",
          },
        });

        const statusPayload = await statusResponse.json();
        const job = statusPayload.job || {};
        setRemoteImportStatus({
          visible: true,
          phase: job.message || busyMessage,
          detail: job.current_item || job.status || "",
          percent: typeof job.percent === "number" ? job.percent : null,
        });

        if (job.complete) {
          if (!job.ok) {
            throw new Error(job.error || job.message || "Import failed.");
          }

          window.location.href = job.redirect_url || form.getAttribute("data-success-url") || window.location.href;
          return;
        }

        await sleep(900);
      }
    } catch (error) {
      setRemoteImportStatus({
        visible: true,
        phase: "Import failed.",
        detail: error instanceof Error ? error.message : "Import failed.",
        percent: null,
      });
      window.alert(error instanceof Error ? error.message : "Import failed.");
    } finally {
      if (submitButton) {
        submitButton.disabled = false;
      }
    }
  }

  document.querySelectorAll("[data-ingest-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      await startRemoteImport(form);
    });
  });

  if (sharedLibraryStateUrl) {
    sharedLibraryStateTimer = window.setInterval(pollSharedLibraryState, 1500);
    pollSharedLibraryState();
  }

  const youtubeSearchForm = document.querySelector("[data-youtube-search-form]");
  const youtubeSearchResults = document.querySelector("[data-youtube-search-results]");
  const youtubeSearchStatus = document.querySelector("[data-youtube-search-status]");
  const youtubeImportForm = document.querySelector('[data-ingest-form][data-import-source="youtube"]');
  const spotifySearchForm = document.querySelector("[data-spotify-search-form]");
  const spotifySearchResults = document.querySelector("[data-spotify-search-results]");
  const spotifySearchStatus = document.querySelector("[data-spotify-search-status]");
  const spotifyImportForm = document.querySelector('[data-ingest-form][data-import-source="spotify"]');

  function renderYoutubeSearchResults(results) {
    if (!youtubeSearchResults) {
      return;
    }

    if (!results.length) {
      youtubeSearchResults.hidden = false;
      youtubeSearchResults.innerHTML = '<div class="youtube-search-empty">No YouTube matches found.</div>';
      return;
    }

    youtubeSearchResults.hidden = false;
    youtubeSearchResults.innerHTML = results.map((result) => `
      <article class="youtube-search-result">
        <div class="youtube-search-result-media">
          ${result.thumbnail ? `<img src="${escapeHtml(result.thumbnail)}" alt="">` : `<div class="youtube-search-result-fallback">${escapeHtml(initialsFromText(result.title || "YT"))}</div>`}
        </div>
        <div class="youtube-search-result-copy">
          <strong>${escapeHtml(result.title || "Untitled result")}</strong>
          <span>${escapeHtml(result.channel || "Unknown channel")}</span>
          <span>${escapeHtml(result.duration || "")}</span>
        </div>
        <button type="button" class="frame-button" data-youtube-result-import="${escapeHtml(result.url || "")}">Import</button>
      </article>
    `).join("");

    youtubeSearchResults.querySelectorAll("[data-youtube-result-import]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!youtubeImportForm) {
          return;
        }
        const url = button.getAttribute("data-youtube-result-import") || "";
        await startRemoteImport(youtubeImportForm, url);
      });
    });
  }

  if (youtubeSearchForm) {
    youtubeSearchForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const searchInput = youtubeSearchForm.querySelector("input[name='q']");
      const query = searchInput ? searchInput.value.trim() : "";
      if (!query) {
        if (searchInput) {
          searchInput.focus();
        }
        return;
      }

      if (youtubeSearchStatus) {
        youtubeSearchStatus.textContent = "Searching YouTube...";
      }

      try {
        const params = new URLSearchParams({ q: query });
        const response = await fetch(`${youtubeSearchForm.action}?${params.toString()}`, {
          headers: {
            Accept: "application/json",
            "X-Requested-With": "fetch",
          },
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || "YouTube search failed.");
        }

        if (youtubeSearchStatus) {
          youtubeSearchStatus.textContent = `${payload.results.length} result${payload.results.length === 1 ? "" : "s"} ready to import.`;
        }
        renderYoutubeSearchResults(payload.results || []);
      } catch (error) {
        if (youtubeSearchStatus) {
          youtubeSearchStatus.textContent = error instanceof Error ? error.message : "YouTube search failed.";
        }
        if (youtubeSearchResults) {
          youtubeSearchResults.hidden = true;
          youtubeSearchResults.innerHTML = "";
        }
      }
    });
  }

  function renderSpotifySearchResults(results) {
    if (!spotifySearchResults) {
      return;
    }

    if (!results.length) {
      spotifySearchResults.hidden = false;
      spotifySearchResults.innerHTML = '<div class="spotify-search-empty">No Spotify matches found.</div>';
      return;
    }

    spotifySearchResults.hidden = false;
    spotifySearchResults.innerHTML = results.map((result) => `
      <article class="spotify-search-result">
        <div class="spotify-search-result-media">
          ${result.thumbnail ? `<img src="${escapeHtml(result.thumbnail)}" alt="">` : `<div class="spotify-search-result-fallback">${escapeHtml(initialsFromText(result.title || "SP"))}</div>`}
        </div>
        <div class="spotify-search-result-copy">
          <strong>${escapeHtml(result.title || "Untitled result")}</strong>
          <span>${escapeHtml(result.subtitle || result.kind || "")}</span>
          <span>${escapeHtml(result.kind || "")}</span>
        </div>
        <button type="button" class="frame-button" data-spotify-result-import="${escapeHtml(result.url || "")}">Import</button>
      </article>
    `).join("");

    spotifySearchResults.querySelectorAll("[data-spotify-result-import]").forEach((button) => {
      button.addEventListener("click", async () => {
        if (!spotifyImportForm) {
          return;
        }
        const url = button.getAttribute("data-spotify-result-import") || "";
        await startRemoteImport(spotifyImportForm, url);
      });
    });
  }

  if (spotifySearchForm) {
    spotifySearchForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const searchInput = spotifySearchForm.querySelector("input[name='q']");
      const query = searchInput ? searchInput.value.trim() : "";
      if (!query) {
        if (searchInput) {
          searchInput.focus();
        }
        return;
      }

      if (spotifySearchStatus) {
        spotifySearchStatus.textContent = "Searching Spotify...";
      }

      try {
        const params = new URLSearchParams({ q: query });
        const response = await fetch(`${spotifySearchForm.action}?${params.toString()}`, {
          headers: {
            Accept: "application/json",
            "X-Requested-With": "fetch",
          },
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || "Spotify search failed.");
        }

        if (spotifySearchStatus) {
          spotifySearchStatus.textContent = `${payload.results.length} result${payload.results.length === 1 ? "" : "s"} ready to import.`;
        }
        renderSpotifySearchResults(payload.results || []);
      } catch (error) {
        if (spotifySearchStatus) {
          spotifySearchStatus.textContent = error instanceof Error ? error.message : "Spotify search failed.";
        }
        if (spotifySearchResults) {
          spotifySearchResults.hidden = true;
          spotifySearchResults.innerHTML = "";
        }
      }
    });
  }

  const uploadForm = document.querySelector("[data-upload-form]");
  const hiddenFileInput = document.querySelector("[data-hidden-file-input]");
  const hiddenDirectoryInput = document.querySelector("[data-hidden-directory-input]");
  if (uploadForm && hiddenFileInput) {
    const dropzone = uploadForm.querySelector("[data-dropzone]");
    const uploadStatusShell = document.querySelector("[data-upload-status-shell]");
    const statusLine = document.querySelector("[data-upload-status]");
    const uploadProgress = document.querySelector("[data-upload-progress]");
    const uploadProgressBar = document.querySelector("[data-upload-progress-bar]");
    const uploadProgressCopy = document.querySelector("[data-upload-progress-copy]");
    const windowDropOverlay = document.getElementById("window-drop-overlay");
    let windowDragDepth = 0;

    function setUploadState(message, active) {
      if (statusLine) {
        statusLine.textContent = message || "";
      }
      uploadForm.classList.toggle("is-busy", Boolean(active));
      if (uploadStatusShell) {
        uploadStatusShell.hidden = !active;
      }
    }

    function setUploadProgress(loaded, total) {
      if (!uploadProgress || !uploadProgressBar || !uploadProgressCopy) {
        return;
      }

      const percent = total > 0 ? Math.max(0, Math.min(100, Math.round((loaded / total) * 100))) : 0;
      uploadProgress.hidden = false;
      uploadProgressBar.style.width = `${percent}%`;
      uploadProgressCopy.textContent = total > 0
        ? `${percent}% · ${formatBytes(loaded)} / ${formatBytes(total)}`
        : `${percent}%`;
    }

    function resetUploadProgress() {
      if (!uploadProgress || !uploadProgressBar || !uploadProgressCopy) {
        return;
      }

      uploadProgress.hidden = true;
      uploadProgressBar.style.width = "0%";
      uploadProgressCopy.textContent = "0%";
    }

    function clearUploadState() {
      setUploadState("", false);
      resetUploadProgress();
    }

    function showWindowDropOverlay() {
      if (!windowDropOverlay) {
        return;
      }

      windowDropOverlay.hidden = false;
      document.body.classList.add("is-window-drop-active");
      windowDropOverlay.classList.add("is-active");
      uploadForm.classList.add("is-drop-target");
    }

    function hideWindowDropOverlay() {
      if (!windowDropOverlay) {
        return;
      }

      windowDropOverlay.hidden = true;
      document.body.classList.remove("is-window-drop-active");
      windowDropOverlay.classList.remove("is-active");
      uploadForm.classList.remove("is-drop-target");
    }

    function uploadFilesWithProgress(body) {
      return new Promise((resolve, reject) => {
        const request = new XMLHttpRequest();
        request.open("POST", uploadForm.action);
        request.responseType = "json";
        request.setRequestHeader("Accept", "application/json");
        request.setRequestHeader("X-Requested-With", "fetch");

        request.upload.addEventListener("progress", (event) => {
          if (event.lengthComputable) {
            setUploadProgress(event.loaded, event.total);
          }
        });

        request.addEventListener("load", () => {
          const payload = request.response || JSON.parse(request.responseText || "{}");
          resolve({ ok: request.status >= 200 && request.status < 300, payload });
        });
        request.addEventListener("error", () => reject(new Error("Upload failed.")));
        request.addEventListener("abort", () => reject(new Error("Upload canceled.")));
        request.send(body);
      });
    }

    function readDirectoryEntries(reader) {
      return new Promise((resolve, reject) => {
        reader.readEntries(resolve, reject);
      });
    }

    function readFileEntry(entry) {
      return new Promise((resolve) => {
        entry.file(resolve, () => resolve(null));
      });
    }

    async function flattenEntry(entry) {
      if (!entry) {
        return [];
      }

      if (entry.isFile) {
        const file = await readFileEntry(entry);
        return file ? [file] : [];
      }

      if (!entry.isDirectory) {
        return [];
      }

      const reader = entry.createReader();
      const files = [];
      while (true) {
        const entries = await readDirectoryEntries(reader);
        if (!entries.length) {
          break;
        }

        for (const childEntry of entries) {
          files.push(...await flattenEntry(childEntry));
        }
      }
      return files;
    }

    async function collectDroppedFiles(dataTransfer) {
      if (dataTransfer && dataTransfer.items && dataTransfer.items.length) {
        const entries = Array.from(dataTransfer.items)
          .map((item) => {
            if (typeof item.getAsEntry === "function") {
              return item.getAsEntry();
            }
            if (typeof item.webkitGetAsEntry === "function") {
              return item.webkitGetAsEntry();
            }
            return null;
          })
          .filter(Boolean);

        if (entries.length) {
          const nestedFiles = await Promise.all(entries.map((entry) => flattenEntry(entry)));
          return nestedFiles.flat().filter(Boolean);
        }
      }

      return Array.from((dataTransfer && dataTransfer.files) || []);
    }

    async function sendFiles(fileList) {
      if (!fileList || !fileList.length) {
        return;
      }

      const files = Array.from(fileList);
      const totalBytes = files.reduce((sum, file) => sum + (Number(file.size) || 0), 0);
      const body = new FormData();
      files.forEach((file) => body.append("tracks", file));
      const busyMessage = `Uploading ${files.length} track${files.length === 1 ? "" : "s"}...`;
      const startedAt = performance.now();
      setUploadState(busyMessage, true);
      setUploadProgress(0, totalBytes || 1);
      await nextFrame();

      try {
        const { payload } = await uploadFilesWithProgress(body);

        if (payload.ok) {
          setUploadProgress(totalBytes || 1, totalBytes || 1);
          setUploadState("Upload complete. Updating view...", true);
          const elapsed = performance.now() - startedAt;
          if (elapsed < 450) {
            await new Promise((resolve) => window.setTimeout(resolve, 450 - elapsed));
          }
          window.location.href = payload.redirect_url || uploadForm.getAttribute("data-upload-success-url") || window.location.href;
          return;
        }

        clearUploadState();
        window.alert(payload.error || (payload.errors && payload.errors[0]) || "Upload failed.");
      } catch (error) {
        clearUploadState();
        window.alert(error instanceof Error ? error.message : "Upload failed.");
      } finally {
        windowDragDepth = 0;
        hideWindowDropOverlay();
        if (!uploadStatusShell || uploadStatusShell.hidden) {
          clearUploadState();
        }
      }
    }

    hiddenFileInput.addEventListener("change", async () => {
      await sendFiles(hiddenFileInput.files);
      hiddenFileInput.value = "";
    });

    if (hiddenDirectoryInput) {
      hiddenDirectoryInput.addEventListener("change", async () => {
        await sendFiles(hiddenDirectoryInput.files);
        hiddenDirectoryInput.value = "";
      });
    }

    ["dragenter", "dragover"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        uploadForm.classList.add("is-drop-target");
      });
    });

    ["dragleave", "drop"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (event) => {
        event.preventDefault();
        uploadForm.classList.remove("is-drop-target");
      });
    });

    dropzone.addEventListener("drop", async (event) => {
      event.stopPropagation();
      const droppedFiles = await collectDroppedFiles(event.dataTransfer);
      if (droppedFiles.length) {
        await sendFiles(droppedFiles);
      }
    });

    window.addEventListener("dragenter", (event) => {
      if (!(event.dataTransfer && Array.from(event.dataTransfer.types || []).includes("Files"))) {
        return;
      }

      event.preventDefault();
      windowDragDepth += 1;
      showWindowDropOverlay();
    });

    window.addEventListener("dragover", (event) => {
      if (!(event.dataTransfer && Array.from(event.dataTransfer.types || []).includes("Files"))) {
        return;
      }

      event.preventDefault();
      showWindowDropOverlay();
    });

    window.addEventListener("dragleave", (event) => {
      if (!(event.dataTransfer && Array.from(event.dataTransfer.types || []).includes("Files"))) {
        return;
      }

      event.preventDefault();
      windowDragDepth = Math.max(0, windowDragDepth - 1);
      if (windowDragDepth === 0 || event.target === document.documentElement) {
        hideWindowDropOverlay();
      }
    });

    window.addEventListener("drop", async (event) => {
      if (!(event.dataTransfer && (event.dataTransfer.items?.length || event.dataTransfer.files?.length))) {
        return;
      }

      if (event.defaultPrevented) {
        return;
      }

      event.preventDefault();
      windowDragDepth = 0;
      hideWindowDropOverlay();
      const droppedFiles = await collectDroppedFiles(event.dataTransfer);
      if (droppedFiles.length) {
        await sendFiles(droppedFiles);
      }
    });
  }

  const downloadLink = document.querySelector("[data-library-download]");
  const downloadStatusShell = document.querySelector("[data-download-status-shell]");
  const downloadStatus = document.querySelector("[data-download-status]");
  const downloadProgress = document.querySelector("[data-download-progress]");
  const downloadProgressBar = document.querySelector("[data-download-progress-bar]");
  const downloadProgressCopy = document.querySelector("[data-download-progress-copy]");

  function setDownloadState(message, active) {
    if (downloadStatus) {
      downloadStatus.textContent = message || "";
    }
    if (downloadStatusShell) {
      downloadStatusShell.hidden = !active;
    }
  }

  function setDownloadProgressKnown(loaded, total) {
    if (!downloadProgress || !downloadProgressBar || !downloadProgressCopy) {
      return;
    }

    const percent = total > 0 ? Math.max(0, Math.min(100, Math.round((loaded / total) * 100))) : 0;
    downloadProgress.hidden = false;
    downloadProgressBar.style.width = `${percent}%`;
    downloadProgressBar.classList.remove("is-indeterminate");
    downloadProgressCopy.textContent = `${percent}% - ${formatBytes(loaded)} / ${formatBytes(total)}`;
  }

  function setDownloadProgressUnknown(loaded) {
    if (!downloadProgress || !downloadProgressBar || !downloadProgressCopy) {
      return;
    }

    downloadProgress.hidden = false;
    downloadProgressBar.style.width = "100%";
    downloadProgressBar.classList.add("is-indeterminate");
    downloadProgressCopy.textContent = `${formatBytes(loaded)} downloaded`;
  }

  function resetDownloadProgress() {
    if (!downloadProgress || !downloadProgressBar || !downloadProgressCopy) {
      return;
    }

    downloadProgress.hidden = true;
    downloadProgressBar.style.width = "0%";
    downloadProgressBar.classList.remove("is-indeterminate");
    downloadProgressCopy.textContent = "0%";
  }

  function clearDownloadState() {
    setDownloadState("", false);
    resetDownloadProgress();
  }

  function downloadFilenameFromResponse(response, fallbackName) {
    const disposition = response.headers.get("Content-Disposition") || "";
    const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match) {
      return decodeURIComponent(utf8Match[1]);
    }

    const plainMatch = disposition.match(/filename=\"?([^\";]+)\"?/i);
    if (plainMatch) {
      return plainMatch[1];
    }

    return fallbackName;
  }

  function triggerBlobDownload(blob, filename) {
    const url = window.URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.setTimeout(() => window.URL.revokeObjectURL(url), 1000);
  }

  async function startLibraryDownload(link) {
    const href = link ? (link.getAttribute("href") || "") : "";
    if (!href) {
      return;
    }

    setDownloadState("Preparing library download...", true);
    resetDownloadProgress();

    try {
      const response = await fetch(href, {
        headers: {
          Accept: "application/zip",
          "X-Requested-With": "fetch",
        },
      });

      if (!response.ok) {
        throw new Error("Could not download library.");
      }

      const total = Number.parseInt(response.headers.get("Content-Length") || "0", 10);
      const filename = downloadFilenameFromResponse(response, "songwalk-library.zip");

      if (!response.body || typeof response.body.getReader !== "function") {
        const blob = await response.blob();
        triggerBlobDownload(blob, filename);
        setDownloadProgressKnown(blob.size || total || 1, blob.size || total || 1);
        setDownloadState("Download ready.", true);
        window.setTimeout(clearDownloadState, 1200);
        return;
      }

      const reader = response.body.getReader();
      const chunks = [];
      let loaded = 0;

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }

        if (value) {
          chunks.push(value);
          loaded += value.byteLength;
          setDownloadState("Downloading library...", true);
          if (total > 0) {
            setDownloadProgressKnown(loaded, total);
          } else {
            setDownloadProgressUnknown(loaded);
          }
        }
      }

      const blob = new Blob(chunks, { type: response.headers.get("Content-Type") || "application/zip" });
      triggerBlobDownload(blob, filename);
      setDownloadProgressKnown(blob.size || loaded || total || 1, blob.size || loaded || total || 1);
      setDownloadState("Download ready.", true);
      window.setTimeout(clearDownloadState, 1200);
    } catch (error) {
      clearDownloadState();
      window.alert(error instanceof Error ? error.message : "Could not download library.");
    }
  }

  let rows = Array.from(document.querySelectorAll("[data-track-row]"));
  let albumContainers = Array.from(document.querySelectorAll("[data-album-container]"));
  let albumCards = Array.from(document.querySelectorAll("[data-album-card]:not([data-collection-card])"));
  let collectionCards = Array.from(document.querySelectorAll("[data-collection-card]"));
  let collectionTrackSections = Array.from(document.querySelectorAll("[data-collection-track-section]"));
  let collectionTrackAlbums = Array.from(document.querySelectorAll("[data-collection-track-album]"));
  let albumDropTargets = Array.from(document.querySelectorAll("[data-drop-album-target]"));
  let selectableAlbums = Array.from(document.querySelectorAll("[data-selectable-album]"));
  let albumSelectButtons = Array.from(document.querySelectorAll("[data-album-select]"));
  let collectionSelectionForms = Array.from(document.querySelectorAll("[data-collection-selection-form]"));
  let collectionSelectionSummaries = Array.from(document.querySelectorAll("[data-collection-selection-summary]"));
  const player = document.getElementById("deck-player");
  const titleTarget = document.getElementById("now-playing-title");
  const metaTarget = document.getElementById("now-playing-meta");
  const artTarget = document.getElementById("selection-art");
  const transportSelectionPanel = document.getElementById("transport-selection-panel");
  const toggleSelectionPanelButton = document.getElementById("toggle-selection-panel");
  const toggleSelectionTitle = document.getElementById("toggle-selection-title");
  const toggleSelectionMeta = document.getElementById("toggle-selection-meta");
  const libraryDrawer = document.getElementById("library-navigation");
  const toggleLibraryDrawerButton = document.getElementById("toggle-library-drawer");
  const libraryDrawerScrim = document.getElementById("library-drawer-scrim");
  const editForm = document.querySelector("[data-editor-form]");
  const editorAccordion = document.getElementById("editor-accordion");
  const toggleEditorButton = document.getElementById("toggle-editor");
  const ratingInput = document.getElementById("edit-rating");
  const titleInput = document.getElementById("edit-title");
  const artistInput = document.getElementById("edit-artist");
  const albumInput = document.getElementById("edit-album");
  const saveButton = document.getElementById("save-track");
  const findAlbumInfoButton = document.getElementById("find-album-info");
  const deleteButton = document.getElementById("delete-track");
  let filterInput = document.querySelector("[data-track-filter]");
  const shuffleButton = document.querySelector("[data-transport-shuffle]");
  const prevButton = document.querySelector("[data-transport-prev]");
  const playButton = document.querySelector("[data-transport-play]");
  const nextButton = document.querySelector("[data-transport-next]");
  const repeatButton = document.querySelector("[data-transport-repeat]");
  const progressInput = document.querySelector("[data-transport-progress]");
  const currentTimeTarget = document.querySelector("[data-transport-current]");
  const durationTarget = document.querySelector("[data-transport-duration]");
  const contextMenu = document.getElementById("track-context-menu");
  const contextEditField = document.getElementById("context-edit-field");
  const contextFindAlbumInfo = document.getElementById("context-find-album-info");
  const contextDeleteTrack = document.getElementById("context-delete-track");
  const contextMoveTrack = document.getElementById("context-move-track");
  const contextMoveLibrary = document.getElementById("context-move-library");
  const lookupDialog = document.getElementById("lookup-dialog");
  const lookupStatus = document.getElementById("lookup-status");
  const lookupResults = document.getElementById("lookup-results");
  const lookupTitleInput = document.getElementById("lookup-title");
  const lookupArtistInput = document.getElementById("lookup-artist");
  const lookupAlbumInput = document.getElementById("lookup-album");
  const lookupSearchButton = document.getElementById("lookup-search-button");
  const bulkDeleteUrl = deleteButton ? (deleteButton.getAttribute("data-bulk-delete-url") || "") : "";
  const trackMoveUrl = document.body ? (document.body.getAttribute("data-track-move-url") || "") : "";
  let targetAlbumSection = document.querySelector("[data-target-album-section]");
  const mediaSession = typeof navigator !== "undefined" ? navigator.mediaSession : null;
  const isAppleMobileMediaSession = (() => {
    if (typeof navigator === "undefined") {
      return false;
    }

    const platform = String(navigator.platform || "");
    const userAgent = String(navigator.userAgent || "");
    return /iPad|iPhone|iPod/i.test(userAgent) || (platform === "MacIntel" && navigator.maxTouchPoints > 1);
  })();

  let selectedRow = null;
  let selectedRows = [];
  let selectionAnchorRow = null;
  let inlineEditRow = null;
  let inlineEditField = "";
  let inlineEditInput = null;
  let inlineEditOriginalValue = "";
  let inlineEditSaving = false;
  let longPressTimer = null;
  let isShuffleEnabled = false;
  let isRepeatEnabled = false;
  let playbackRow = null;
  let currentTrackDrag = null;
  let activeAlbumDropTarget = null;
  const selectedAlbumKeys = new Set();
  const defaultDocumentTitle = document.title;

  function rowAlbumKey(row) {
    return row ? (row.getAttribute("data-track-album-key") || "") : "";
  }

  function dropTargetState(node) {
    if (!node) {
      return null;
    }

    return {
      node,
      album: (node.getAttribute("data-drop-album-name") || "").trim(),
      artist: (node.getAttribute("data-drop-album-artist") || "").trim(),
      key: (node.getAttribute("data-drop-album-key") || "").trim(),
    };
  }

  function draggedTrackIdsForRow(row) {
    const track = trackStateFromRow(row);
    if (!track || !track.id) {
      return [];
    }
    return selectedRows.includes(row) ? selectedTrackIds() : [track.id];
  }

  function clearAlbumDropTarget() {
    if (!activeAlbumDropTarget) {
      return;
    }
    activeAlbumDropTarget.classList.remove("is-drop-target");
    activeAlbumDropTarget = null;
  }

  function setAlbumDropTarget(node) {
    if (!node || activeAlbumDropTarget === node) {
      return;
    }
    clearAlbumDropTarget();
    activeAlbumDropTarget = node;
    activeAlbumDropTarget.classList.add("is-drop-target");
  }

  function clearCurrentTrackDrag() {
    if (currentTrackDrag) {
      currentTrackDrag.trackIds.forEach((trackId) => {
        const row = findRowByTrackId(trackId);
        if (row) {
          row.classList.remove("is-drag-source");
        }
      });
    }
    currentTrackDrag = null;
    clearAlbumDropTarget();
    document.body.classList.remove("is-track-dragging");
  }

  function canDropTracksOnTarget(target) {
    if (!currentTrackDrag || !target || !target.key) {
      return false;
    }

    return currentTrackDrag.trackIds.some((trackId) => {
      const row = findRowByTrackId(trackId);
      return rowAlbumKey(row) !== target.key;
    });
  }

  async function moveTracksToAlbumTarget(target) {
    if (!trackMoveUrl) {
      throw new Error("Could not move tracks.");
    }

    const { response, payload } = await withGlobalBusy("Moving tracks to album...", async () => {
      const response = await fetch(trackMoveUrl, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Requested-With": "fetch",
        },
        body: JSON.stringify({
          track_ids: currentTrackDrag ? currentTrackDrag.trackIds : [],
          album: target.album,
          artist: target.artist,
        }),
      });
      const payload = await response.json();
      return { response, payload };
    });

    if (!response.ok || !payload.ok) {
      throw new Error((payload && payload.error) || "Could not move tracks.");
    }

    const nextUrl = new URL(window.location.href);
    nextUrl.searchParams.set("view", "tracks");
    nextUrl.searchParams.set("album", payload.target_album_key || target.key);
    window.location.href = nextUrl.toString();
  }

  function visibleRows() {
    return rows.filter((row) => !row.hidden);
  }

  function resolveMediaUrl(value) {
    const source = (value || "").trim();
    if (!source) {
      return "";
    }

    try {
      return new URL(source, window.location.href).href;
    } catch (_) {
      return source;
    }
  }

  function rowSourceUrl(row) {
    const track = trackStateFromRow(row);
    return track ? track.resolvedSourceUrl : "";
  }

  function setPlaybackRow(row) {
    playbackRow = row && rows.includes(row) ? row : null;
  }

  function currentPlaybackRow() {
    if (playbackRow && rows.includes(playbackRow)) {
      return playbackRow;
    }

    const currentSrc = player ? resolveMediaUrl(player.currentSrc || player.getAttribute("src")) : "";
    if (!currentSrc) {
      const fallbackRow = selectedRows.length === 1 ? selectedRow : null;
      if (fallbackRow && rows.includes(fallbackRow)) {
        playbackRow = fallbackRow;
      }
      return fallbackRow;
    }

    const matchedRow = rows.find((row) => rowSourceUrl(row) === currentSrc);
    if (matchedRow) {
      playbackRow = matchedRow;
      return matchedRow;
    }

    const fallbackRow = selectedRows.length === 1 ? selectedRow : null;
    if (fallbackRow && rows.includes(fallbackRow)) {
      playbackRow = fallbackRow;
    }
    return fallbackRow;
  }

  function trackStateFromRow(row) {
    if (!row) {
      return null;
    }

    const dataset = row.dataset || {};
    const title = dataset.trackTitle || dataset.trackFilename || "Untitled track";
    const artist = dataset.trackArtist || "";
    const album = dataset.trackAlbum || "";

    return {
      id: dataset.trackId || "",
      title,
      artist,
      album,
      filename: dataset.trackFilename || "",
      rating: normalizeRating(dataset.trackRating),
      sourceUrl: dataset.trackSrc || "",
      resolvedSourceUrl: resolveMediaUrl(dataset.trackSrc || ""),
      coverUrl: resolveMediaUrl(dataset.trackCoverUrl || ""),
      coverInitials: dataset.trackCoverInitials || initialsFromText(album || title),
      updateUrl: dataset.trackUpdateUrl || "",
      ratingUrl: dataset.trackRatingUrl || "",
      deleteUrl: dataset.trackDeleteUrl || "",
      moveLibraryUrl: dataset.trackMoveLibraryUrl || "",
      lookupUrl: dataset.trackLookupUrl || "",
      lookupApplyUrl: dataset.trackLookupApplyUrl || "",
    };
  }

  function findRowByTrackId(trackId) {
    return rows.find((row) => trackStateFromRow(row)?.id === trackId) || null;
  }

  function defaultTrackHeading() {
    return "Track details";
  }

  function documentTitleTrack() {
    return currentPlaybackRow() || (selectedRows.length === 1 ? selectedRow : null);
  }

  function syncFavicon(fallbackText = "SS") {
    const track = trackStateFromRow(documentTitleTrack());
    const coverUrl = track ? track.coverUrl : "";
    const fallback = track ? (track.coverInitials || initialsFromText(track.album || track.title || fallbackText)) : fallbackText;
    setFaviconFrame(coverUrl, fallback);
  }

  // Keep the browser tab tied to the active track instead of selection-only state.
  function syncDocumentTitle(fallbackTitle = defaultDocumentTitle) {
    const track = trackStateFromRow(documentTitleTrack());
    document.title = (track && track.title) || fallbackTitle;
    syncFavicon();
  }

  function setTogglePressed(button, pressed) {
    if (!button) {
      return;
    }

    button.setAttribute("aria-pressed", pressed ? "true" : "false");
  }

  function randomVisibleRow(excludingRow) {
    const visible = visibleRows();
    if (!visible.length) {
      return null;
    }

    if (visible.length === 1) {
      return visible[0];
    }

    const candidates = excludingRow ? visible.filter((row) => row !== excludingRow) : visible;
    if (!candidates.length) {
      return excludingRow || visible[0];
    }

    const index = Math.floor(Math.random() * candidates.length);
    return candidates[index] || candidates[0];
  }

  function nextPlaybackRow() {
    const currentRow = currentPlaybackRow() || selectedRow;
    if (isRepeatEnabled && currentRow) {
      return currentRow;
    }

    if (isShuffleEnabled) {
      return randomVisibleRow(currentRow);
    }

    return getAdjacentRow(1, { fromPlayback: true });
  }

  function previousPlaybackRow() {
    const currentRow = currentPlaybackRow() || selectedRow;
    if (isShuffleEnabled) {
      return randomVisibleRow(currentRow);
    }

    return getAdjacentRow(-1, { clamp: true, fromPlayback: true });
  }

  function setMediaSessionMetadata(row) {
    if (!mediaSession || typeof window.MediaMetadata !== "function") {
      return;
    }

    const track = trackStateFromRow(row);
    if (!track) {
      mediaSession.metadata = null;
      return;
    }

    const artwork = track.coverUrl ? [{ src: track.coverUrl }] : [];

    try {
      mediaSession.metadata = new window.MediaMetadata({
        title: track.title,
        artist: track.artist === "Unknown artist" ? "" : track.artist,
        album: track.album === "Unknown album" ? "" : track.album,
        artwork,
      });
    } catch (_) {
      mediaSession.metadata = null;
    }
  }

  function updateMediaSessionPlaybackState() {
    if (!mediaSession) {
      return;
    }

    try {
      mediaSession.playbackState = player && player.getAttribute("src")
        ? (player.paused ? "paused" : "playing")
        : "none";
    } catch (_) {
      // Ignore unsupported playback state updates.
    }
  }

  function updateMediaSessionPositionState() {
    if (!mediaSession || typeof mediaSession.setPositionState !== "function" || !player) {
      return;
    }

    if (!player.getAttribute("src") || !Number.isFinite(player.duration) || player.duration <= 0) {
      try {
        mediaSession.setPositionState({});
      } catch (_) {
        // Ignore unsupported position state updates.
      }
      return;
    }

    try {
      mediaSession.setPositionState({
        duration: player.duration,
        playbackRate: player.playbackRate || 1,
        position: Math.min(player.currentTime, player.duration),
      });
    } catch (_) {
      // Ignore unsupported position state updates.
    }
  }

  function syncMediaSession() {
    setMediaSessionMetadata(currentPlaybackRow());
    updateMediaSessionPlaybackState();
    updateMediaSessionPositionState();
  }

  function getAdjacentRow(offset, { clamp = false, fromPlayback = false } = {}) {
    const visible = visibleRows();
    if (!visible.length) {
      return null;
    }

    const baseRow = fromPlayback ? (currentPlaybackRow() || selectedRow || visible[0]) : (selectedRow || currentPlaybackRow() || visible[0]);
    const currentIndex = Math.max(visible.indexOf(baseRow), 0);
    const targetIndex = currentIndex + offset;

    if (clamp) {
      return visible[Math.min(Math.max(targetIndex, 0), visible.length - 1)] || null;
    }

    return visible[targetIndex] || null;
  }

  function selectAdjacentRow(offset, autoplay, options) {
    const target = getAdjacentRow(offset, options);
    if (!target) {
      return false;
    }

    selectRow(target, autoplay);
    return true;
  }

  function setMediaSessionAction(action, handler) {
    if (!mediaSession || typeof mediaSession.setActionHandler !== "function") {
      return;
    }

    try {
      mediaSession.setActionHandler(action, handler);
    } catch (_) {
      // Ignore unsupported action handlers.
    }
  }

  function bindMediaSessionTransportActions() {
    if (!player) {
      return;
    }

    setMediaSessionAction("play", async () => {
      if (!player.getAttribute("src")) {
        selectRow(currentPlaybackRow() || visibleRows()[0] || rows[0], false);
      }

      await player.play().catch(() => {});
    });
    setMediaSessionAction("pause", () => {
      player.pause();
    });
    setMediaSessionAction("previoustrack", () => {
      const target = previousPlaybackRow();
      if (target) {
        selectRow(target, true);
      }
    });
    setMediaSessionAction("nexttrack", () => {
      const target = nextPlaybackRow();
      if (target) {
        selectRow(target, true);
      }
    });

    // iOS Control Center prefers seek buttons when both seek and track-skip
    // handlers are registered, so keep track navigation explicit there.
    if (isAppleMobileMediaSession) {
      setMediaSessionAction("seekbackward", null);
      setMediaSessionAction("seekforward", null);
    } else {
      setMediaSessionAction("seekbackward", (details) => {
        const offset = Number.isFinite(details && details.seekOffset) ? details.seekOffset : 10;
        player.currentTime = Math.max(player.currentTime - offset, 0);
        updateMediaSessionPositionState();
      });
      setMediaSessionAction("seekforward", (details) => {
        const offset = Number.isFinite(details && details.seekOffset) ? details.seekOffset : 10;
        const duration = Number.isFinite(player.duration) ? player.duration : player.currentTime + offset;
        player.currentTime = Math.min(player.currentTime + offset, duration);
        updateMediaSessionPositionState();
      });
    }

    setMediaSessionAction("seekto", (details) => {
      if (!details || !Number.isFinite(details.seekTime)) {
        return;
      }

      if (details.fastSeek && typeof player.fastSeek === "function") {
        player.fastSeek(details.seekTime);
      } else {
        player.currentTime = details.seekTime;
      }

      updateMediaSessionPositionState();
    });
  }

  function syncSelectionToVisibleRows() {
    const visible = visibleRows();
    const visibleSet = new Set(visible);

    selectedRows = selectedRows.filter((row) => visibleSet.has(row));
    if (selectedRow && !visibleSet.has(selectedRow)) {
      selectedRow = null;
    }

    if (!selectedRow && selectedRows.length) {
      selectedRow = selectedRows[selectedRows.length - 1];
    }

    if (!selectedRow && visible.length) {
      selectedRow = visible[0];
      selectedRows = [selectedRow];
    }

    if (selectedRow && !selectedRows.length) {
      selectedRows = [selectedRow];
    }

    if (!visible.length) {
      selectedRow = null;
      selectedRows = [];
    }

    if (selectionAnchorRow && !visibleSet.has(selectionAnchorRow)) {
      setSelectionAnchor(selectedRow || visible[0] || null);
    }

    debugLog("selection.sync", {
      visibleRows: visible.length,
      selectedRowId: trackStateFromRow(selectedRow)?.id || "",
      selectedRowIds: selectedRows.map((row) => trackStateFromRow(row)?.id || "").filter(Boolean),
    });

    renderSelection(false);
  }

  function selectedTrackIds() {
    return selectedRows.map((row) => trackStateFromRow(row)?.id).filter(Boolean);
  }

  function setSelectionAnchor(row) {
    selectionAnchorRow = row && rows.includes(row) ? row : null;
  }

  function isMultiSelectEvent(event) {
    return Boolean(event && (event.ctrlKey || event.metaKey));
  }

  function isRangeSelectEvent(event) {
    return Boolean(event && event.shiftKey);
  }

  function uniqueRowsInDocumentOrder(items) {
    const seen = new Set(items);
    return rows.filter((row) => seen.has(row));
  }

  function normalizeRating(value) {
    const numeric = Number.parseInt(value, 10);
    if (!Number.isFinite(numeric)) {
      return 0;
    }
    return Math.max(0, Math.min(5, numeric));
  }

  function setInlineRatingState(row, ratingValue) {
    const rating = normalizeRating(ratingValue);
    row.setAttribute("data-track-rating", String(rating));
    row.querySelectorAll("[data-inline-rating-value]").forEach((button) => {
      const starValue = normalizeRating(button.getAttribute("data-inline-rating-value"));
      button.innerHTML = starValue <= rating ? "&#9733;" : "&#9734;";
      button.classList.toggle("is-active", starValue <= rating);
    });
  }

  async function saveInlineRating(row, ratingValue) {
    const rating = normalizeRating(ratingValue);
    const track = trackStateFromRow(row);
    const ratingUrl = track ? track.ratingUrl : "";
    if (!ratingUrl) {
      return;
    }

    const previousRating = track ? track.rating : 0;
    setInlineRatingState(row, rating);

    try {
      const { response, payload } = await withGlobalBusy("Saving rating...", async () => {
        const response = await fetch(ratingUrl, {
          method: "POST",
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-Requested-With": "fetch",
          },
          body: JSON.stringify({ rating }),
        });
        const payload = await response.json();
        return { response, payload };
      });

      if (!response.ok || !payload.ok) {
        throw new Error((payload && payload.error) || "Could not save rating.");
      }

      setInlineRatingState(row, payload.track && payload.track.rating);

      if (selectedRow === row) {
        renderSelection(false);
      }
    } catch (error) {
      setInlineRatingState(row, previousRating);
      throw error;
    }
  }

  function editableFieldNode(row, field) {
    if (!row || !field) {
      return null;
    }

    return row.querySelector(`[data-context-edit-field="${field}"]`);
  }

  function rowFieldValue(row, field) {
    const track = trackStateFromRow(row);
    if (!track) {
      return "";
    }

    if (field === "artist") {
      return track.artist;
    }
    if (field === "album") {
      return track.album;
    }
    return track.title;
  }

  function isInlineEditTarget(target) {
    return Boolean(
      target
      && typeof target.closest === "function"
      && target.closest(".inline-edit-input"),
    );
  }

  function cancelInlineEdit() {
    if (!inlineEditRow || !inlineEditField) {
      inlineEditRow = null;
      inlineEditField = "";
      inlineEditInput = null;
      inlineEditOriginalValue = "";
      inlineEditSaving = false;
      return;
    }

    const fieldNode = editableFieldNode(inlineEditRow, inlineEditField);
    if (fieldNode) {
      fieldNode.textContent = inlineEditOriginalValue;
      fieldNode.classList.remove("is-inline-editing");
    }

    inlineEditRow = null;
    inlineEditField = "";
    inlineEditInput = null;
    inlineEditOriginalValue = "";
    inlineEditSaving = false;
  }

  async function submitTrackUpdate(row, values, busyMessage = "Saving track...") {
    const track = trackStateFromRow(row);
    const updateUrl = track ? track.updateUrl : "";
    if (!updateUrl) {
      throw new Error("Could not save track.");
    }

    const formData = new FormData();
    formData.set("title", values.title || "");
    formData.set("artist", values.artist || "");
    formData.set("album", values.album || "");
    formData.set("rating", String(values.rating ?? 0));

    const response = await withGlobalBusy(busyMessage, async () => {
      return await fetch(updateUrl, {
        method: "POST",
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
        body: formData,
      });
    });

    if (!response.ok) {
      throw new Error("Could not save track.");
    }
  }

  async function commitInlineEdit() {
    if (!inlineEditRow || !inlineEditField || !inlineEditInput || inlineEditSaving) {
      return;
    }

    const nextValue = inlineEditInput.value;
    if (nextValue === inlineEditOriginalValue) {
      cancelInlineEdit();
      return;
    }

    inlineEditSaving = true;
    inlineEditInput.disabled = true;

    try {
      const track = trackStateFromRow(inlineEditRow);
      await submitTrackUpdate(
        inlineEditRow,
        {
          title: inlineEditField === "title" ? nextValue : (track ? track.title : ""),
          artist: inlineEditField === "artist" ? nextValue : (track ? track.artist : ""),
          album: inlineEditField === "album" ? nextValue : (track ? track.album : ""),
          rating: track ? track.rating : 0,
        },
        `Saving ${inlineEditField}...`,
      );
      await refreshLibraryAfterMutation({
        selectedTrackIds: track ? [track.id] : [],
        selectedTrackId: track ? track.id : "",
        selectionAnchorId: track ? track.id : "",
      });
    } catch (error) {
      inlineEditSaving = false;
      inlineEditInput.disabled = false;
      inlineEditInput.focus();
      inlineEditInput.select();
      window.alert(error instanceof Error ? error.message : "Could not save track.");
    }
  }

  function beginInlineEdit(row, field) {
    if (!row || !field || selectedRows.length !== 1 || selectedRow !== row) {
      return;
    }

    if (inlineEditRow === row && inlineEditField === field) {
      return;
    }

    cancelInlineEdit();
    hideContextMenu();
    setEditorAccordionOpen(false);

    const fieldNode = editableFieldNode(row, field);
    if (!fieldNode) {
      return;
    }

    const currentValue = rowFieldValue(row, field);
    const input = document.createElement("input");
    input.type = "text";
    input.className = "inline-edit-input";
    input.value = currentValue;
    input.setAttribute("aria-label", `Edit ${field}`);

    fieldNode.textContent = "";
    fieldNode.classList.add("is-inline-editing");
    fieldNode.appendChild(input);

    inlineEditRow = row;
    inlineEditField = field;
    inlineEditInput = input;
    inlineEditOriginalValue = currentValue;
    inlineEditSaving = false;

    ["click", "dblclick", "mousedown", "contextmenu"].forEach((eventName) => {
      input.addEventListener(eventName, (event) => {
        event.stopPropagation();
      });
    });

    input.addEventListener("keydown", async (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        await commitInlineEdit();
        return;
      }

      if (event.key === "Escape") {
        event.preventDefault();
        cancelInlineEdit();
      }
    });

    input.addEventListener("blur", async () => {
      if (!inlineEditSaving) {
        await commitInlineEdit();
      }
    });

    window.requestAnimationFrame(() => {
      input.focus();
      input.select();
    });
  }

  function setEditorEnabled(enabled) {
    [titleInput, artistInput, albumInput, ratingInput, saveButton, findAlbumInfoButton, deleteButton, toggleEditorButton].forEach((element) => {
      if (element) {
        element.disabled = !enabled;
      }
    });
  }

  function setEditorAccordionOpen(open) {
    if (!editorAccordion || !toggleEditorButton) {
      return;
    }

    const isOpen = Boolean(open);
    editorAccordion.classList.toggle("is-open", isOpen);
    toggleEditorButton.setAttribute("aria-expanded", isOpen ? "true" : "false");
  }

  function updatePlayButton() {
    if (!playButton || !player) {
      return;
    }

    playButton.innerHTML = player.paused ? "&#9654;" : "&#10074;&#10074;";
    updateMediaSessionPlaybackState();
  }

  function updateNowPlayingDisc() {
    var disc = document.querySelector('.now-playing-disc');
    if (!disc || !player) return;

    if (!player.paused && player.getAttribute('src')) {
      disc.classList.add('is-spinning');
    } else {
      disc.classList.remove('is-spinning');
    }

    var discImg = disc.querySelector('img');
    var discTitle = document.querySelector('.disc-track-title');
    var discArtist = document.querySelector('.disc-track-artist');

    if (discImg && artTarget) {
      var artImg = artTarget.querySelector('img');
      if (artImg && artImg.src) {
        discImg.src = artImg.src;
        discImg.style.display = '';
      } else {
        discImg.style.display = 'none';
      }
    }

    if (discTitle && titleTarget) {
      discTitle.textContent = titleTarget.textContent;
    }
    if (discArtist && metaTarget) {
      discArtist.textContent = metaTarget.textContent;
    }
  }

  function formatPlaybackTime(value) {
    if (!Number.isFinite(value) || value < 0) {
      return "0:00";
    }

    const totalSeconds = Math.floor(value);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;

    if (hours > 0) {
      return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }

    return `${minutes}:${String(seconds).padStart(2, "0")}`;
  }

  function syncTransportProgress() {
    const hasSource = Boolean(player && player.getAttribute("src"));
    const duration = player && Number.isFinite(player.duration) && player.duration > 0 ? player.duration : 0;
    const currentTime = player && Number.isFinite(player.currentTime) ? Math.min(player.currentTime, duration || player.currentTime) : 0;

    if (currentTimeTarget) {
      currentTimeTarget.textContent = formatPlaybackTime(currentTime);
    }

    if (durationTarget) {
      durationTarget.textContent = formatPlaybackTime(duration);
    }

    if (!progressInput) {
      return;
    }

    if (!hasSource || duration <= 0) {
      progressInput.disabled = true;
      progressInput.max = "100";
      progressInput.value = "0";
      return;
    }

    progressInput.disabled = false;
    progressInput.max = String(duration);
    progressInput.value = String(currentTime);
  }

  function hideContextMenu() {
    if (contextMenu) {
      contextMenu.dataset.editField = "";
      contextMenu.hidden = true;
    }
  }

  function contextEditLabel(field) {
    if (field === "title") {
      return "Edit title";
    }
    if (field === "artist") {
      return "Edit artist";
    }
    if (field === "album") {
      return "Edit album";
    }
    return "Edit details";
  }

  function inputForEditField(field) {
    if (field === "artist") {
      return artistInput;
    }
    if (field === "album") {
      return albumInput;
    }
    return titleInput;
  }

  function openEditorForField(field) {
    if (!selectedRow || !toggleEditorButton || toggleEditorButton.disabled) {
      return;
    }

    setEditorAccordionOpen(true);
    const input = inputForEditField(field);
    if (input) {
      input.focus();
      if (typeof input.select === "function") {
        input.select();
      }
    }
  }

  function contextEditFieldFromTarget(target) {
    if (!target || typeof target.closest !== "function") {
      return "";
    }

    const editTarget = target.closest("[data-context-edit-field]");
    return editTarget ? (editTarget.getAttribute("data-context-edit-field") || "") : "";
  }

  function normalizeSearchText(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/\s+/g, " ")
      .trim();
  }

  function rowSearchValue(row) {
    return normalizeSearchText(row.getAttribute("data-search") || "");
  }

  function cardSearchValue(card) {
    return normalizeSearchText(card.getAttribute("data-search") || "");
  }

  function setCollectionOpen(card, open) {
    if (!card) {
      return;
    }

    const panel = card.querySelector("[data-collection-panel]");
    const isOpen = Boolean(open);
    card.classList.toggle("is-open", isOpen);
    card.setAttribute("aria-expanded", isOpen ? "true" : "false");
    if (panel) {
      panel.hidden = !isOpen;
    }
  }

  function albumTrackIds(node) {
    return String(node?.getAttribute("data-album-track-ids") || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
  }

  function selectedAlbumTrackIds() {
    const trackIds = [];
    selectableAlbums.forEach((node) => {
      const key = node.getAttribute("data-album-key") || "";
      if (!selectedAlbumKeys.has(key)) {
        return;
      }

      albumTrackIds(node).forEach((trackId) => {
        if (!trackIds.includes(trackId)) {
          trackIds.push(trackId);
        }
      });
    });
    return trackIds;
  }

  function trackAlbumTrackIds(row) {
    return String(row?.getAttribute("data-track-album-track-ids") || "")
      .split(",")
      .map((value) => value.trim())
      .filter(Boolean);
  }

  function selectedTrackAlbumState() {
    const albumKeys = [];
    const trackIds = [];

    selectedRows.forEach((row) => {
      const key = row.getAttribute("data-track-album-key") || "";
      if (!key || albumKeys.includes(key)) {
        return;
      }

      albumKeys.push(key);
      trackAlbumTrackIds(row).forEach((trackId) => {
        if (!trackIds.includes(trackId)) {
          trackIds.push(trackId);
        }
      });
    });

    return { count: albumKeys.length, trackIds };
  }

  function collectionSelectionState(scope) {
    if (scope === "tracks") {
      return selectedTrackAlbumState();
    }

    return {
      count: selectedAlbumKeys.size,
      trackIds: selectedAlbumTrackIds(),
    };
  }

  function syncCollectionSelectionForms() {
    const albumSelectionState = collectionSelectionState("albums");

    selectableAlbums.forEach((node) => {
      const key = node.getAttribute("data-album-key") || "";
      const isSelected = selectedAlbumKeys.has(key);
      node.classList.toggle("is-group-selected", isSelected);
    });

    albumSelectButtons.forEach((button) => {
      const node = button.closest("[data-selectable-album]");
      const key = node ? (node.getAttribute("data-album-key") || "") : "";
      const isSelected = selectedAlbumKeys.has(key);
      button.setAttribute("aria-pressed", isSelected ? "true" : "false");
      button.textContent = isSelected ? "Selected" : "Select";
    });

    collectionSelectionForms.forEach((form) => {
      const scope = form.getAttribute("data-collection-selection-scope") || "albums";
      const state = scope === "albums" ? albumSelectionState : collectionSelectionState(scope);
      form.querySelectorAll("[data-selected-track-ids]").forEach((input) => {
        input.value = state.trackIds.join(",");
      });
      const picker = form.querySelector("[data-collection-picker]");
      const hasCollectionChoice = !picker || Boolean(picker.value);
      form.querySelectorAll("[data-requires-collection-selection]").forEach((button) => {
        button.disabled = !state.count || !hasCollectionChoice;
      });
    });

    collectionSelectionSummaries.forEach((summary) => {
      const scope = summary.getAttribute("data-collection-selection-scope") || "albums";
      const state = scope === "albums" ? albumSelectionState : collectionSelectionState(scope);
      const emptySummary = summary.getAttribute("data-empty-summary") || "";
      const singular = summary.getAttribute("data-selection-singular") || "album";
      const plural = summary.getAttribute("data-selection-plural") || `${singular}s`;

      if (!state.count) {
        summary.textContent = emptySummary;
      } else if (state.count === 1) {
        summary.textContent = `1 ${singular} selected.`;
      } else {
        summary.textContent = `${state.count} ${plural} selected.`;
      }
    });
  }

  function toggleAlbumSelection(node) {
    if (!node) {
      return;
    }

    const key = node.getAttribute("data-album-key") || "";
    if (!key) {
      return;
    }

    if (selectedAlbumKeys.has(key)) {
      selectedAlbumKeys.delete(key);
    } else {
      selectedAlbumKeys.add(key);
    }
    syncCollectionSelectionForms();
  }

  function matchesSearchValue(haystack, query) {
    return !query || haystack.includes(query);
  }

  function syncAlbumSectionVisibility() {
    collectionTrackAlbums.forEach((group) => {
      const hasVisibleRows = Array.from(group.querySelectorAll("[data-track-row]")).some((row) => !row.hidden);
      group.hidden = !hasVisibleRows;
    });

    albumContainers
      .filter((container) => !container.hasAttribute("data-album-card"))
      .forEach((container) => {
        if (container.hasAttribute("data-collection-track-section")) {
          const hasVisibleGroups = Array.from(container.querySelectorAll("[data-collection-track-album]")).some((group) => !group.hidden);
          container.hidden = !hasVisibleGroups;
          return;
        }

        const hasVisibleRows = Array.from(container.querySelectorAll("[data-track-row]")).some((row) => !row.hidden);
        container.hidden = !hasVisibleRows;
        debugLog("filter.section", {
          albumKey: container.getAttribute("data-album-key") || "",
          hasVisibleRows,
          hidden: container.hidden,
        });
      });
  }

  function applySearchFilter(rawQuery) {
    const query = normalizeSearchText(rawQuery);

    debugLog("filter.apply.start", {
      rawQuery,
      normalizedQuery: query,
      rowCount: rows.length,
      albumCardCount: albumCards.length,
      collectionCardCount: collectionCards.length,
    });

    rows.forEach((row) => {
      const track = trackStateFromRow(row);
      const haystack = rowSearchValue(row);
      const match = matchesSearchValue(haystack, query);
      row.hidden = !match;
      debugLog("filter.row", {
        id: track ? track.id : "",
        title: track ? track.title : "",
        haystack,
        match,
        hidden: row.hidden,
      });
    });

    collectionTrackSections.forEach((section) => {
      const summaryHaystack = normalizeSearchText(section.getAttribute("data-collection-name-search") || "");
      if (!matchesSearchValue(summaryHaystack, query)) {
        return;
      }

      section.querySelectorAll("[data-track-row]").forEach((row) => {
        row.hidden = false;
      });
    });

    albumCards.forEach((card) => {
      const haystack = cardSearchValue(card);
      const match = matchesSearchValue(haystack, query);
      card.hidden = !match;
      debugLog("filter.albumCard", {
        primaryTrackId: card.getAttribute("data-album-primary-track-id") || "",
        haystack,
        match,
        hidden: card.hidden,
      });
    });

    collectionCards.forEach((card) => {
      const haystack = cardSearchValue(card);
      const childMatches = Array.from(card.querySelectorAll("[data-collection-album-link]")).some((link) => {
        return matchesSearchValue(cardSearchValue(link), query);
      });
      const match = matchesSearchValue(haystack, query) || childMatches;
      card.hidden = !match;
      setCollectionOpen(card, Boolean(query) && match && childMatches);
      debugLog("filter.collectionCard", {
        title: card.querySelector(".album-title")?.textContent || "",
        haystack,
        childMatches,
        match,
        hidden: card.hidden,
      });
    });

    syncAlbumSectionVisibility();
    syncSelectionToVisibleRows();

    debugLog("filter.apply.done", {
      normalizedQuery: query,
      visibleRows: visibleRows().length,
      hiddenRows: rows.filter((row) => row.hidden).length,
      visibleAlbumCards: albumCards.filter((card) => !card.hidden).length,
      hiddenAlbumCards: albumCards.filter((card) => card.hidden).length,
      visibleCollectionCards: collectionCards.filter((card) => !card.hidden).length,
      hiddenCollectionCards: collectionCards.filter((card) => card.hidden).length,
    });
  }

  function currentLookupQuery() {
    return {
      title: lookupTitleInput ? lookupTitleInput.value.trim() : "",
      artist: lookupArtistInput ? lookupArtistInput.value.trim() : "",
      album: lookupAlbumInput ? lookupAlbumInput.value.trim() : "",
    };
  }

  function countLookupFields(query) {
    return [query.title, query.artist, query.album].filter(Boolean).length;
  }

  function updateRowSelectionState() {
    rows.forEach((row) => {
      const isSelected = selectedRows.includes(row);
      row.classList.toggle("is-selected", isSelected);
      row.classList.toggle("is-primary-selected", row === selectedRow);
    });

    albumCards.forEach((card) => {
      const browseUrl = card.getAttribute("data-album-browse-url");
      if (browseUrl) {
        card.classList.remove("is-selected");
        return;
      }

      const primaryTrackId = card.getAttribute("data-album-primary-track-id");
      const isSelected = Boolean(selectedRow) && trackStateFromRow(selectedRow)?.id === primaryTrackId;
      card.classList.toggle("is-selected", isSelected);
    });
  }

  function setTransportSelectionOpen(open) {
    if (!transportSelectionPanel || !toggleSelectionPanelButton) {
      return;
    }

    const isOpen = Boolean(open);
    transportSelectionPanel.classList.toggle("is-open", isOpen);
    toggleSelectionPanelButton.setAttribute("aria-expanded", isOpen ? "true" : "false");
  }

  function setTransportSelectionSummary(title, meta) {
    if (toggleSelectionTitle) {
      toggleSelectionTitle.textContent = title || defaultTrackHeading();
    }

    if (toggleSelectionMeta) {
      toggleSelectionMeta.textContent = meta || "Choose a row to view details, edit metadata, or delete it.";
    }
  }

  function hasLibraryDrawerControls() {
    return Boolean(libraryDrawer && toggleLibraryDrawerButton && libraryDrawerScrim);
  }

  function setLibraryDrawerOpen(open) {
    if (!hasLibraryDrawerControls()) {
      return;
    }

    const isOpen = Boolean(open);
    libraryDrawer.classList.toggle("is-open", isOpen);
    libraryDrawerScrim.hidden = !isOpen;
    libraryDrawerScrim.classList.toggle("is-open", isOpen);
    toggleLibraryDrawerButton.setAttribute("aria-expanded", isOpen ? "true" : "false");
    document.body.classList.toggle("is-library-drawer-open", isOpen);
  }

  function renderMultiSelection() {
    titleTarget.textContent = `${selectedRows.length} tracks selected`;
    metaTarget.textContent = "Shift click selects a range. Ctrl/Cmd click adds or removes tracks. Delete removes the whole selection.";
    setTransportSelectionSummary(
      `${selectedRows.length} tracks selected`,
      "Open to review the selection state, edit one track, or delete the selected tracks.",
    );
    setArtFrame(artTarget, "", String(selectedRows.length));
    setEditorAccordionOpen(false);
    setTransportSelectionOpen(false);

    if (titleInput) {
      titleInput.value = "";
      titleInput.disabled = true;
    }
    if (artistInput) {
      artistInput.value = "";
      artistInput.disabled = true;
    }
    if (albumInput) {
      albumInput.value = "";
      albumInput.disabled = true;
    }
    if (ratingInput) {
      ratingInput.value = "0";
    }
    if (editForm) {
      editForm.action = "";
    }
    if (saveButton) {
      saveButton.disabled = true;
    }
    if (toggleEditorButton) {
      toggleEditorButton.disabled = true;
    }
    if (findAlbumInfoButton) {
      findAlbumInfoButton.disabled = true;
      findAlbumInfoButton.setAttribute("data-lookup-url", "");
      findAlbumInfoButton.setAttribute("data-lookup-apply-url", "");
    }
    if (deleteButton) {
      deleteButton.disabled = false;
      deleteButton.setAttribute("data-delete-url", "");
      deleteButton.textContent = `Delete ${selectedRows.length} tracks`;
    }

    syncDocumentTitle();
    syncMediaSession();
  }

  function renderSingleSelection(row, autoplay) {
    const track = trackStateFromRow(row);
    const title = track ? track.title : defaultTrackHeading();
    const artist = track && track.artist ? track.artist : "Unknown artist";
    const album = track && track.album ? track.album : "Unknown album";
    const filename = track ? track.filename : "";
    const coverUrl = track ? track.coverUrl : "";
    const coverInitials = track ? track.coverInitials : initialsFromText(album || title);

    titleTarget.textContent = title;
    metaTarget.textContent = `${artist} - ${album} - ${filename}`;
    setTransportSelectionSummary(title, `${artist} - ${album}`);
    setArtFrame(artTarget, coverUrl, coverInitials);

    titleInput.value = title;
    artistInput.value = artist === "Unknown artist" ? "" : artist;
    albumInput.value = album === "Unknown album" ? "" : album;
    if (ratingInput) {
      ratingInput.value = track ? String(track.rating) : "0";
    }
    editForm.action = track ? track.updateUrl : "";
    deleteButton.setAttribute("data-delete-url", track ? track.deleteUrl : "");
    deleteButton.textContent = "Delete";
    findAlbumInfoButton.setAttribute("data-lookup-url", track ? track.lookupUrl : "");
    findAlbumInfoButton.setAttribute("data-lookup-apply-url", track ? track.lookupApplyUrl : "");
    setEditorEnabled(true);

    if (player) {
      const src = track ? track.sourceUrl : "";
      setPlaybackRow(track ? row : null);
      if (src && player.getAttribute("src") !== src) {
        player.src = src;
      }

      if (autoplay) {
        player.play().catch(() => {});
      }
    }

    syncDocumentTitle();
    syncMediaSession();
    updatePlayButton();
  }

  function renderSelection(autoplay) {
    updateRowSelectionState();
    syncCollectionSelectionForms();

    if (!selectedRows.length) {
      if (titleTarget) {
        titleTarget.textContent = defaultTrackHeading();
      }
      if (metaTarget) {
        metaTarget.textContent = "Choose a row to edit metadata or play it from the transport bar.";
      }
      setTransportSelectionSummary(defaultTrackHeading(), "Choose a row to view details, edit metadata, or delete it.");
      setArtFrame(artTarget, "", "SS");
      if (ratingInput) {
        ratingInput.value = "0";
      }
      setEditorAccordionOpen(false);
      setTransportSelectionOpen(false);
      if (deleteButton) {
        deleteButton.textContent = "Delete";
      }
      setEditorEnabled(false);
      syncDocumentTitle();
      syncMediaSession();
      updatePlayButton();
      return;
    }

    if (!selectedRow || !selectedRows.includes(selectedRow)) {
      selectedRow = selectedRows[selectedRows.length - 1];
    }

    if (selectedRows.length > 1) {
      renderMultiSelection();
      return;
    }

    renderSingleSelection(selectedRow, autoplay);
  }

  function openContextMenu(event, row, editField = "") {
    if (!contextMenu) {
      return;
    }

    if (!selectedRows.includes(row)) {
      setEditorAccordionOpen(false);
      selectedRows = [row];
      selectedRow = row;
      renderSelection(false);
    }

    if (contextEditField) {
      contextEditField.textContent = contextEditLabel(editField);
    }
    if (contextDeleteTrack) {
      contextDeleteTrack.textContent = selectedRows.length > 1 ? `Delete ${selectedRows.length} tracks` : "Delete track";
    }
    if (contextMoveLibrary) {
      contextMoveLibrary.value = "";
    }
    if (contextMoveTrack) {
      contextMoveTrack.disabled = true;
    }
    contextMenu.dataset.editField = editField || "";
    contextMenu.hidden = false;
    const gutter = 12;
    const rect = contextMenu.getBoundingClientRect();
    const maxLeft = Math.max(gutter, window.innerWidth - rect.width - gutter);
    const maxTop = Math.max(gutter, window.innerHeight - rect.height - gutter);
    contextMenu.style.left = `${Math.min(Math.max(gutter, event.clientX), maxLeft)}px`;
    contextMenu.style.top = `${Math.min(Math.max(gutter, event.clientY), maxTop)}px`;
  }

  function selectRow(row, autoplay) {
    if (!row) {
      return;
    }

    cancelInlineEdit();
    setEditorAccordionOpen(false);
    selectedRow = row;
    selectedRows = [row];
    setSelectionAnchor(row);
    renderSelection(autoplay);
  }

  function selectRowRange(row, { append = false } = {}) {
    if (!row) {
      return;
    }

    cancelInlineEdit();
    const visible = visibleRows();
    const anchor = selectionAnchorRow && visible.includes(selectionAnchorRow)
      ? selectionAnchorRow
      : (selectedRow && visible.includes(selectedRow) ? selectedRow : row);
    const anchorIndex = visible.indexOf(anchor);
    const targetIndex = visible.indexOf(row);

    if (anchorIndex === -1 || targetIndex === -1) {
      selectRow(row, false);
      return;
    }

    const start = Math.min(anchorIndex, targetIndex);
    const end = Math.max(anchorIndex, targetIndex);
    const range = visible.slice(start, end + 1);
    selectedRows = append ? uniqueRowsInDocumentOrder([...selectedRows, ...range]) : range;
    selectedRow = row;
    setEditorAccordionOpen(false);
    renderSelection(false);
  }

  function toggleRowSelection(row) {
    if (!row) {
      return;
    }

    cancelInlineEdit();
    if (selectedRows.includes(row)) {
      if (selectedRows.length === 1) {
        selectedRows = [];
        selectedRow = null;
        setSelectionAnchor(null);
        setEditorAccordionOpen(false);
        renderSelection(false);
        return;
      }

      selectedRows = selectedRows.filter((item) => item !== row);
      if (selectedRow === row) {
        selectedRow = selectedRows[selectedRows.length - 1] || null;
      }
      setSelectionAnchor(selectedRow || row);
      setEditorAccordionOpen(false);
      renderSelection(false);
      return;
    }

    selectedRows = [...selectedRows, row];
    selectedRow = row;
    setSelectionAnchor(row);
    setEditorAccordionOpen(false);
    renderSelection(false);
  }

  async function runLookupSearch() {
    if (!selectedRow || !lookupDialog || !lookupResults || !lookupStatus) {
      return;
    }

    const track = trackStateFromRow(selectedRow);
    const lookupUrl = track ? track.lookupUrl : "";
    const applyUrl = track ? track.lookupApplyUrl : "";
    if (!lookupUrl || !applyUrl) {
      return;
    }

    lookupResults.innerHTML = "";
    const query = currentLookupQuery();
    if (countLookupFields(query) < 2) {
      lookupStatus.textContent = "Enter at least two fields. Use title + artist, artist + album, or title + album.";
      return;
    }

    lookupStatus.textContent = "Searching MusicBrainz...";
    if (lookupSearchButton) {
      lookupSearchButton.disabled = true;
    }

    try {
      const params = new URLSearchParams(query);
      const { response, payload } = await withGlobalBusy("Searching MusicBrainz...", async () => {
        const response = await fetch(`${lookupUrl}?${params.toString()}`, {
          headers: { Accept: "application/json", "X-Requested-With": "fetch" },
        });
        const payload = await response.json();
        return { response, payload };
      });

      if (!response.ok || !payload.ok) {
        lookupStatus.textContent = payload.error || "Lookup failed.";
        return;
      }

      if (lookupTitleInput) {
        lookupTitleInput.value = payload.query.title || "";
      }
      if (lookupArtistInput) {
        lookupArtistInput.value = payload.query.artist || "";
      }
      if (lookupAlbumInput) {
        lookupAlbumInput.value = payload.query.album || "";
      }

      if (!payload.candidates.length) {
        lookupStatus.textContent = "No candidate releases found. Try changing the title, artist, or album and search again.";
        return;
      }

      lookupStatus.textContent = "Choose the closest match to apply album artwork and metadata.";
      lookupResults.innerHTML = payload.candidates
        .map((candidate, index) => {
          const cover = candidate.cover_art_url
            ? `<img src="${escapeHtml(candidate.cover_art_url)}" alt="${escapeHtml(candidate.title)} cover art">`
            : escapeHtml(initialsFromText(candidate.title));

          return `
            <article class="lookup-result">
              <div class="lookup-result-art">${cover}</div>
              <div class="lookup-result-copy">
                <p class="lookup-result-title">${escapeHtml(candidate.title)}</p>
                <p>${escapeHtml(candidate.artist)}</p>
                <p>${escapeHtml(candidate.track_title || "")}</p>
                <p>${escapeHtml([candidate.date, candidate.country].filter(Boolean).join(" - "))}</p>
              </div>
              <button
                type="button"
                class="frame-button primary"
                data-apply-candidate="${index}"
              >
                Apply
              </button>
            </article>
          `;
        })
        .join("");

      lookupResults.querySelectorAll("[data-apply-candidate]").forEach((button) => {
        button.addEventListener("click", async () => {
          const candidate = payload.candidates[Number(button.getAttribute("data-apply-candidate"))];
          if (!candidate) {
            return;
          }

          lookupStatus.textContent = "Applying album info...";

          try {
            const { response: applyResponse, payload: applyPayload } = await withGlobalBusy(
              "Applying album info...",
              async () => {
                const response = await fetch(applyUrl, {
                  method: "POST",
                  headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                    "X-Requested-With": "fetch",
                  },
                  body: JSON.stringify({
                    release_id: candidate.release_id,
                    release_group_id: candidate.release_group_id,
                    title: candidate.track_title || (track ? track.title : ""),
                    artist: candidate.artist || (track ? track.artist : ""),
                    album: candidate.title || (track ? track.album : ""),
                  }),
                });
                const payload = await response.json();
                return { response, payload };
              },
            );

            if (!applyResponse.ok || !applyPayload.ok) {
              lookupStatus.textContent = applyPayload.error || "Could not apply album info.";
              return;
            }

            await refreshLibraryAfterMutation({
              selectedTrackIds: track ? [track.id] : [],
              selectedTrackId: track ? track.id : "",
              selectionAnchorId: track ? track.id : "",
            });
            if (lookupDialog && lookupDialog.open) {
              lookupDialog.close();
            }
          } catch (error) {
            lookupStatus.textContent = error instanceof Error ? error.message : "Could not apply album info.";
          }
        });
      });
    } catch (error) {
      lookupStatus.textContent = error instanceof Error ? error.message : "Lookup failed.";
    } finally {
      if (lookupSearchButton) {
        lookupSearchButton.disabled = false;
      }
    }
  }

  async function openLookupDialog() {
    if (!selectedRow || !lookupDialog) {
      return;
    }

    const track = trackStateFromRow(selectedRow);
    if (lookupTitleInput) {
      lookupTitleInput.value = track ? track.title : "";
    }
    if (lookupArtistInput) {
      const artist = track ? track.artist : "";
      lookupArtistInput.value = artist === "Unknown artist" ? "" : artist;
    }
    if (lookupAlbumInput) {
      const album = track ? track.album : "";
      lookupAlbumInput.value = album === "Unknown album" ? "" : album;
    }

    if (!lookupDialog.open) {
      lookupDialog.showModal();
    }

    await runLookupSearch();
  }

  function bindTrackRow(row) {
    row.addEventListener("click", (event) => {
      if (isInlineEditTarget(event.target)) {
        return;
      }

      const editField = contextEditFieldFromTarget(event.target);
      if (editField && selectedRows.length === 1 && selectedRow === row) {
        beginInlineEdit(row, editField);
        return;
      }

      if (isRangeSelectEvent(event)) {
        selectRowRange(row, { append: isMultiSelectEvent(event) });
        return;
      }

      if (isMultiSelectEvent(event)) {
        toggleRowSelection(row);
        return;
      }

      var alreadySelected = row.classList.contains('is-selected');
      selectRow(row, alreadySelected);
    });

    row.addEventListener("keydown", (event) => {
      if (event.target !== row) {
        return;
      }

      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        if (isRangeSelectEvent(event)) {
          selectRowRange(row, { append: isMultiSelectEvent(event) });
          return;
        }
        if (isMultiSelectEvent(event)) {
          toggleRowSelection(row);
          return;
        }
        selectRow(row, false);
      }
    });

    row.addEventListener("dblclick", (event) => {
      if (contextEditFieldFromTarget(event.target) || isInlineEditTarget(event.target)) {
        return;
      }

      selectRow(row, true);
    });

    row.addEventListener("contextmenu", (event) => {
      event.preventDefault();
      openContextMenu(event, row, contextEditFieldFromTarget(event.target));
    });

    row.addEventListener("touchstart", (event) => {
      if (event.touches.length !== 1) {
        return;
      }

      const touch = event.touches[0];
      const editField = contextEditFieldFromTarget(event.target);
      longPressTimer = window.setTimeout(() => {
        openContextMenu({ clientX: touch.clientX, clientY: touch.clientY }, row, editField);
      }, 450);
    }, { passive: true });

    ["touchend", "touchcancel", "touchmove"].forEach((eventName) => {
      row.addEventListener(eventName, () => {
        if (longPressTimer) {
          window.clearTimeout(longPressTimer);
          longPressTimer = null;
        }
      }, { passive: true });
    });

    row.querySelectorAll("[data-inline-rating-value]").forEach((button) => {
      button.addEventListener("click", async (event) => {
        event.preventDefault();
        event.stopPropagation();
        selectRow(row, false);

        try {
          await saveInlineRating(row, button.getAttribute("data-inline-rating-value"));
        } catch (error) {
          window.alert(error instanceof Error ? error.message : "Could not save rating.");
        }
      });
    });

    row.addEventListener("dragstart", (event) => {
      if (
        !event.dataTransfer
        || (event.target && typeof event.target.closest === "function" && event.target.closest("button, input, a"))
        || isInlineEditTarget(event.target)
      ) {
        event.preventDefault();
        return;
      }

      if (!selectedRows.includes(row)) {
        selectRow(row, false);
      }

      const trackIds = draggedTrackIdsForRow(row);
      if (!trackIds.length) {
        event.preventDefault();
        return;
      }

      currentTrackDrag = { trackIds };
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("application/x-songwalk-track-ids", JSON.stringify(trackIds));
      event.dataTransfer.setData("text/plain", `${trackIds.length} track${trackIds.length === 1 ? "" : "s"}`);
      document.body.classList.add("is-track-dragging");

      trackIds.forEach((trackId) => {
        const draggedRow = findRowByTrackId(trackId);
        if (draggedRow) {
          draggedRow.classList.add("is-drag-source");
        }
      });
    });

    row.addEventListener("dragend", () => {
      clearCurrentTrackDrag();
    });
  }

  function bindAlbumCard(card) {
    const activateCard = () => {
      const browseUrl = card.getAttribute("data-album-browse-url");
      if (browseUrl) {
        window.location.href = browseUrl;
        return;
      }

      const primaryTrackId = card.getAttribute("data-album-primary-track-id");
      const row = findRowByTrackId(primaryTrackId);
      if (row) {
        selectRow(row, false);
      }
    };

    card.addEventListener("click", activateCard);
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }

      event.preventDefault();
      activateCard();
    });
  }

  function bindCollectionCard(card) {
    const toggleCard = (event) => {
      if (event && event.target && typeof event.target.closest === "function" && event.target.closest("[data-collection-album-link]")) {
        return;
      }

      const isOpen = card.getAttribute("aria-expanded") === "true";
      setCollectionOpen(card, !isOpen);
    };

    card.addEventListener("click", toggleCard);
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }

      event.preventDefault();
      toggleCard(event);
    });
  }

  function bindAlbumSelectButton(button) {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      toggleAlbumSelection(button.closest("[data-selectable-album]"));
    });
  }

  function bindAlbumDropTarget(node) {
    node.addEventListener("dragenter", (event) => {
      const target = dropTargetState(node);
      if (!canDropTracksOnTarget(target)) {
        return;
      }
      event.preventDefault();
      setAlbumDropTarget(node);
    });

    node.addEventListener("dragover", (event) => {
      const target = dropTargetState(node);
      if (!canDropTracksOnTarget(target)) {
        return;
      }
      event.preventDefault();
      event.dataTransfer.dropEffect = "move";
      setAlbumDropTarget(node);
    });

    node.addEventListener("dragleave", (event) => {
      const nextTarget = event.relatedTarget;
      if (nextTarget && typeof node.contains === "function" && node.contains(nextTarget)) {
        return;
      }
      if (activeAlbumDropTarget === node) {
        clearAlbumDropTarget();
      }
    });

    node.addEventListener("drop", async (event) => {
      const target = dropTargetState(node);
      if (!canDropTracksOnTarget(target)) {
        return;
      }

      event.preventDefault();
      setAlbumDropTarget(node);

      try {
        await moveTracksToAlbumTarget(target);
      } catch (error) {
        window.alert(error instanceof Error ? error.message : "Could not move tracks.");
        clearCurrentTrackDrag();
      }
    });
  }

  function bindFilterControl() {
    if (!filterInput || !rows.length) {
      debugLog("filter.unavailable", {
        filterPresent: Boolean(filterInput),
        rowCount: rows.length,
      });
      return;
    }

    ["input", "search", "change"].forEach((eventName) => {
      filterInput.addEventListener(eventName, () => {
        debugLog("filter.event", {
          eventName,
          value: filterInput.value,
        });
        applySearchFilter(filterInput.value);
      });
    });

    debugLog("filter.ready", {
      initialValue: filterInput.value,
    });
  }

  function bindLibraryContent({ selectDefault = false, scrollToTarget = false } = {}) {
    if (!rows.length) {
      setEditorEnabled(false);
      return;
    }

    debugLog("rows.init", {
      rowCount: rows.length,
      albumCardCount: albumCards.length,
      collectionCardCount: collectionCards.length,
      filterPresent: Boolean(filterInput),
      sampleRows: rows.slice(0, 5).map((row) => {
        const track = trackStateFromRow(row);
        return {
          id: track ? track.id : "",
          title: track ? track.title : "",
          search: rowSearchValue(row),
        };
      }),
    });

    rows.forEach(bindTrackRow);
    albumCards.forEach(bindAlbumCard);
    collectionCards.forEach(bindCollectionCard);
    albumSelectButtons.forEach(bindAlbumSelectButton);
    albumDropTargets.forEach(bindAlbumDropTarget);
    bindFilterControl();

    collectionSelectionForms.forEach((form) => {
      const picker = form.querySelector("[data-collection-picker]");
      if (picker) {
        picker.addEventListener("change", syncCollectionSelectionForms);
      }
    });
    if (collectionSelectionForms.length) {
      syncCollectionSelectionForms();
    }

    if (selectDefault && rows.length) {
      selectRow(rows[0], false);
    }

    if (scrollToTarget && targetAlbumSection) {
      window.requestAnimationFrame(() => {
        targetAlbumSection.scrollIntoView({ block: "start", behavior: "smooth" });
      });
    }
  }

  bindLibraryContent({ selectDefault: true, scrollToTarget: true });

  async function moveSelectedTrackToLibrary() {
    if (!contextMoveLibrary || !selectedRow || selectedRows.length !== 1) {
      return;
    }

    const targetLibraryToken = (contextMoveLibrary.value || "").trim();
    const track = trackStateFromRow(selectedRow);
    const moveLibraryUrl = track ? track.moveLibraryUrl : "";
    if (!targetLibraryToken || !moveLibraryUrl) {
      return;
    }

    const { response, payload } = await withGlobalBusy("Moving track to library...", async () => {
      const response = await fetch(moveLibraryUrl, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
          "X-Requested-With": "fetch",
        },
        body: JSON.stringify({ target_library_token: targetLibraryToken }),
      });
      const payload = await response.json();
      return { response, payload };
    });

    if (!response.ok || !payload.ok) {
      throw new Error((payload && payload.error) || "Could not move track.");
    }

    window.location.href = payload.redirect_url || window.location.href;
  }

  if (hasLibraryDrawerControls()) {
    setLibraryDrawerOpen(false);
  }

  document.addEventListener("click", (event) => {
    if (contextMenu && !contextMenu.hidden && !contextMenu.contains(event.target)) {
      hideContextMenu();
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") {
      return;
    }

    if (inlineEditRow) {
      cancelInlineEdit();
      return;
    }

    hideContextMenu();
    if (toggleLibraryDrawerButton && toggleLibraryDrawerButton.getAttribute("aria-expanded") === "true") {
      setLibraryDrawerOpen(false);
      toggleLibraryDrawerButton.focus();
    }
  });

  window.addEventListener("resize", hideContextMenu);
  window.addEventListener("scroll", hideContextMenu, true);

  if (contextFindAlbumInfo) {
    contextFindAlbumInfo.addEventListener("click", async () => {
      hideContextMenu();
      await openLookupDialog();
    });
  }

  if (contextEditField) {
    contextEditField.addEventListener("click", () => {
      const editField = contextMenu ? (contextMenu.dataset.editField || "") : "";
      hideContextMenu();
      openEditorForField(editField || "title");
    });
  }

  if (contextDeleteTrack) {
    contextDeleteTrack.addEventListener("click", () => {
      hideContextMenu();
      if (deleteButton) {
        deleteButton.click();
      }
    });
  }

  if (contextMoveLibrary) {
    contextMoveLibrary.addEventListener("change", () => {
      if (contextMoveTrack) {
        contextMoveTrack.disabled = !(selectedRows.length === 1 && contextMoveLibrary.value);
      }
    });
  }

  if (contextMoveTrack) {
    contextMoveTrack.addEventListener("click", async () => {
      try {
        await moveSelectedTrackToLibrary();
      } catch (error) {
        window.alert(error instanceof Error ? error.message : "Could not move track.");
      } finally {
        hideContextMenu();
      }
    });
  }

  if (findAlbumInfoButton) {
    findAlbumInfoButton.addEventListener("click", openLookupDialog);
  }

  if (lookupSearchButton) {
    lookupSearchButton.addEventListener("click", runLookupSearch);
  }

  if (downloadLink) {
    downloadLink.addEventListener("click", async (event) => {
      if (!window.fetch || !window.Blob || !window.URL || typeof window.URL.createObjectURL !== "function") {
        return;
      }

      event.preventDefault();
      await startLibraryDownload(downloadLink);
    });
  }

  if (toggleSelectionPanelButton) {
    toggleSelectionPanelButton.addEventListener("click", () => {
      const isOpen = toggleSelectionPanelButton.getAttribute("aria-expanded") === "true";
      setTransportSelectionOpen(!isOpen);
    });
  }

  if (toggleLibraryDrawerButton) {
    toggleLibraryDrawerButton.addEventListener("click", () => {
      const isOpen = toggleLibraryDrawerButton.getAttribute("aria-expanded") === "true";
      setLibraryDrawerOpen(!isOpen);
      if (!isOpen && libraryDrawer) {
        libraryDrawer.focus();
      }
    });
  }

  if (libraryDrawerScrim) {
    libraryDrawerScrim.addEventListener("click", () => {
      setLibraryDrawerOpen(false);
      if (toggleLibraryDrawerButton) {
        toggleLibraryDrawerButton.focus();
      }
    });
  }

  [lookupTitleInput, lookupArtistInput, lookupAlbumInput]
    .filter(Boolean)
    .forEach((input) => {
      input.addEventListener("keydown", async (event) => {
        if (event.key !== "Enter") {
          return;
        }

        event.preventDefault();
        await runLookupSearch();
      });
    });

  if (toggleEditorButton) {
    toggleEditorButton.addEventListener("click", () => {
      if (toggleEditorButton.disabled) {
        return;
      }

      const isOpen = toggleEditorButton.getAttribute("aria-expanded") === "true";
      setEditorAccordionOpen(!isOpen);
    });
  }

  if (lookupDialog) {
    lookupDialog.addEventListener("click", (event) => {
      const rect = lookupDialog.getBoundingClientRect();
      const outside =
        event.clientX < rect.left ||
        event.clientX > rect.right ||
        event.clientY < rect.top ||
        event.clientY > rect.bottom;
      if (outside) {
        lookupDialog.close();
      }
    });
  }

  if (filterInput && rows.length) {
    applySearchFilter(filterInput.value);
  }

  if (editForm) {
    editForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!editForm.action || !selectedRow) {
        return;
      }

      saveButton.disabled = true;
      try {
        const selectedTrackId = trackStateFromRow(selectedRow)?.id || "";
        await submitTrackUpdate(selectedRow, {
          title: titleInput ? titleInput.value : "",
          artist: artistInput ? artistInput.value : "",
          album: albumInput ? albumInput.value : "",
          rating: ratingInput ? ratingInput.value : "0",
        });
        await refreshLibraryAfterMutation({
          selectedTrackIds: selectedTrackId ? [selectedTrackId] : [],
          selectedTrackId,
          selectionAnchorId: selectedTrackId,
        });
      } finally {
        saveButton.disabled = false;
      }
    });
  }

  if (deleteButton) {
    deleteButton.addEventListener("click", async () => {
      const trackIds = selectedTrackIds();
      const isBulkDelete = trackIds.length > 1;
      const url = isBulkDelete ? bulkDeleteUrl : deleteButton.getAttribute("data-delete-url");
      const message = isBulkDelete
        ? `Delete ${trackIds.length} tracks from the shared library?`
        : "Delete this track from the shared library?";

      if (!url || !trackIds.length || !window.confirm(message)) {
        return;
      }

      deleteButton.disabled = true;
      try {
        const deletedTrackIds = [...trackIds];
        const response = await withGlobalBusy(isBulkDelete ? "Deleting tracks..." : "Deleting track...", async () => {
          if (isBulkDelete) {
            return await fetch(url, {
              method: "POST",
              headers: {
                Accept: "application/json",
                "Content-Type": "application/json",
                "X-Requested-With": "fetch",
              },
              body: JSON.stringify({ track_ids: trackIds }),
            });
          }

          return await fetch(url, {
            method: "POST",
            headers: { Accept: "application/json", "X-Requested-With": "fetch" },
          });
        });

        if (response.ok) {
          await refreshLibraryAfterMutation({
            selectedTrackIds: [],
            selectedTrackId: "",
            selectionAnchorId: "",
            deletedTrackIds,
          });
        }
      } finally {
        deleteButton.disabled = false;
      }
    });
  }

  (function injectNowPlayingDisc() {
    var transportBand = document.querySelector('.transport-band');
    if (!transportBand || !player) return;

    if (transportBand.querySelector('.now-playing-disc-shell')) return;

    var discShell = document.createElement('div');
    discShell.className = 'now-playing-disc-shell';

    var disc = document.createElement('div');
    disc.className = 'now-playing-disc';

    var discImg = document.createElement('img');
    discImg.src = '';
    discImg.alt = 'Album art';
    discImg.style.display = 'none';

    var discFallback = document.createElement('div');
    discFallback.className = 'disc-fallback';

    // Pixel-art CD layers
    var discOverlay = document.createElement('div');
    discOverlay.className = 'disc-overlay';

    var discRim = document.createElement('div');
    discRim.className = 'disc-rim';

    var discHub = document.createElement('div');
    discHub.className = 'disc-hub';

    disc.appendChild(discImg);
    disc.appendChild(discFallback);
    disc.appendChild(discOverlay);
    disc.appendChild(discRim);
    disc.appendChild(discHub);

    var discInfo = document.createElement('div');
    discInfo.className = 'now-playing-disc-info';

    var discTitle = document.createElement('span');
    discTitle.className = 'disc-track-title';
    discTitle.textContent = 'No track playing';

    var discArtist = document.createElement('span');
    discArtist.className = 'disc-track-artist';
    discArtist.textContent = '';

    discInfo.appendChild(discTitle);
    discInfo.appendChild(discArtist);

    discShell.appendChild(disc);
    discShell.appendChild(discInfo);

    transportBand.insertBefore(discShell, transportBand.firstChild);
  })();

  if (player && playButton) {
    player.playsInline = true;
    bindMediaSessionTransportActions();

    if (progressInput) {
      progressInput.addEventListener("input", () => {
        if (progressInput.disabled) {
          return;
        }

        const nextTime = Number.parseFloat(progressInput.value);
        if (!Number.isFinite(nextTime)) {
          return;
        }

        if (typeof player.fastSeek === "function") {
          player.fastSeek(nextTime);
        } else {
          player.currentTime = nextTime;
        }

        syncTransportProgress();
        updateMediaSessionPositionState();
      });
    }

    playButton.addEventListener("click", async () => {
      if (!selectedRow && rows.length) {
        selectRow(visibleRows()[0] || rows[0], false);
      }

      if (!player.src && selectedRow) {
        selectRow(selectedRow, false);
      }

      if (player.paused) {
        await player.play().catch(() => {});
      } else {
        player.pause();
      }

      updatePlayButton();
      updateNowPlayingDisc();
    });

    if (prevButton) {
      prevButton.addEventListener("click", () => {
        const target = previousPlaybackRow();
        if (target) {
          selectRow(target, true);
        }
      });
    }

    if (nextButton) {
      nextButton.addEventListener("click", () => {
        const target = nextPlaybackRow();
        if (target) {
          selectRow(target, true);
        }
      });
    }

    if (shuffleButton) {
      setTogglePressed(shuffleButton, isShuffleEnabled);
      shuffleButton.addEventListener("click", () => {
        isShuffleEnabled = !isShuffleEnabled;
        setTogglePressed(shuffleButton, isShuffleEnabled);
      });
    }

    if (repeatButton) {
      setTogglePressed(repeatButton, isRepeatEnabled);
      repeatButton.addEventListener("click", () => {
        isRepeatEnabled = !isRepeatEnabled;
        setTogglePressed(repeatButton, isRepeatEnabled);
      });
    }

    player.addEventListener("play", updatePlayButton);
    player.addEventListener("play", updateNowPlayingDisc);
    player.addEventListener("pause", updatePlayButton);
    player.addEventListener("pause", updateNowPlayingDisc);
    player.addEventListener("loadedmetadata", () => {
      syncTransportProgress();
      updateMediaSessionPositionState();
    });
    player.addEventListener("timeupdate", () => {
      syncTransportProgress();
      updateMediaSessionPositionState();
    });
    player.addEventListener("ended", () => {
      const target = nextPlaybackRow();
      if (target) {
        selectRow(target, true);
        return;
      }

      player.pause();
      player.currentTime = 0;
      syncTransportProgress();
      updateMediaSessionPositionState();
      updatePlayButton();
    });
    player.addEventListener("ratechange", updateMediaSessionPositionState);
    player.addEventListener("emptied", () => {
      if (!player.getAttribute("src")) {
        setPlaybackRow(null);
      }
      syncTransportProgress();
      syncDocumentTitle();
      syncMediaSession();
    });

    if (!player.getAttribute("src")) {
      syncMediaSession();
    } else {
      updateMediaSessionPlaybackState();
      updateMediaSessionPositionState();
    }

    syncTransportProgress();
    updatePlayButton();
    updateNowPlayingDisc();
  }

  if (document.body && document.body.dataset.devMode === "1") {
    let currentToken = null;

    async function pollForReload() {
      try {
        const response = await fetch("/__dev/reload-token", {
          cache: "no-store",
          headers: { Accept: "application/json" },
        });

        if (!response.ok) {
          return;
        }

        const payload = await response.json();
        if (currentToken === null) {
          currentToken = payload.token;
          return;
        }

        if (payload.token !== currentToken) {
          window.location.reload();
        }
      } catch (_) {
        // Ignore transient reload failures while the dev server restarts.
      }
    }

    window.setInterval(pollForReload, 1000);
    pollForReload();
  }

  (function bindTransportSwipe() {
    var transportBand = document.querySelector('.transport-band');
    if (!transportBand) return;

    var swipeThreshold = 50;
    var touchStartX = 0;
    var touchStartY = 0;
    var touchStartTime = 0;

    transportBand.addEventListener('touchstart', function(e) {
      if (e.touches.length !== 1) return;
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
      touchStartTime = Date.now();
    }, { passive: true });

    transportBand.addEventListener('touchend', function(e) {
      if (!e.changedTouches.length) return;
      var dx = e.changedTouches[0].clientX - touchStartX;
      var dy = e.changedTouches[0].clientY - touchStartY;
      var dt = Date.now() - touchStartTime;

      if (Math.abs(dx) < swipeThreshold) return;
      if (Math.abs(dy) > Math.abs(dx)) return;
      if (dt > 500) return;

      if (dx < 0) {
        if (typeof nextButton !== 'undefined' && nextButton) {
          nextButton.click();
        }
      } else {
        if (typeof prevButton !== 'undefined' && prevButton) {
          prevButton.click();
        }
      }
    });
  })();

  (function bindTitleOverflow() {
    var titleActions = document.querySelector('.title-actions');
    if (!titleActions) return;

    var buttons = titleActions.querySelectorAll(':scope > .frame-button');
    if (buttons.length <= 1) return;

    var overflowBtn = document.createElement('button');
    overflowBtn.type = 'button';
    overflowBtn.className = 'title-actions-overflow';
    overflowBtn.setAttribute('aria-label', 'More actions');
    overflowBtn.setAttribute('aria-expanded', 'false');
    overflowBtn.setAttribute('hidden', '');
    overflowBtn.innerHTML = '&#8943;';

    var dropdown = document.createElement('div');
    dropdown.className = 'title-actions-dropdown';
    dropdown.setAttribute('hidden', '');

    for (var i = 1; i < buttons.length; i++) {
      var clone = buttons[i].cloneNode(true);
      clone.classList.remove('title-actions-moved');
      clone.addEventListener('click', (function(orig) {
        return function(e) {
          e.stopPropagation();
          orig.click();
        };
      })(buttons[i]));
      dropdown.appendChild(clone);
    }

    for (var j = 1; j < buttons.length; j++) {
      buttons[j].classList.add('title-actions-moved');
    }

    titleActions.appendChild(overflowBtn);
    titleActions.appendChild(dropdown);

    overflowBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      var isOpen = !dropdown.classList.contains('is-open');
      if (isOpen) {
        dropdown.classList.add('is-open');
        dropdown.removeAttribute('hidden');
        overflowBtn.setAttribute('aria-expanded', 'true');
      } else {
        dropdown.classList.remove('is-open');
        dropdown.setAttribute('hidden', '');
        overflowBtn.setAttribute('aria-expanded', 'false');
      }
    });

    document.addEventListener('click', function(e) {
      if (!dropdown.classList.contains('is-open')) return;
      if (!titleActions.contains(e.target)) {
        dropdown.classList.remove('is-open');
        dropdown.setAttribute('hidden', '');
        overflowBtn.setAttribute('aria-expanded', 'false');
      }
    });

    function updateOverflowVisibility() {
      var isMobile = window.matchMedia('(max-width: 720px)').matches;
      for (var k = 1; k < buttons.length; k++) {
        buttons[k].style.display = isMobile ? 'none' : '';
      }
      if (isMobile) {
        overflowBtn.removeAttribute('hidden');
      } else {
        overflowBtn.setAttribute('hidden', '');
        dropdown.setAttribute('hidden', '');
        dropdown.classList.remove('is-open');
      }
    }

    window.matchMedia('(max-width: 720px)').addEventListener('change', updateOverflowVisibility);
    updateOverflowVisibility();
  })();

  (function bindListenTogether() {
    var syncSocket = null;
    var syncPeerId = null;
    var syncConnected = false;
    var syncEnabled = false;
    var syncRoom = null;
    var syncResyncTimer = null;
    var syncPeers = {};
    var syncIgnoreUntil = 0;

    function initListenTogether() {
      var syncBtn = document.createElement('button');
      syncBtn.type = 'button';
      syncBtn.className = 'frame-button transport-toggle';
      syncBtn.setAttribute('data-sync-toggle', '');
      syncBtn.innerHTML = '\u{1F3B5} Listen Together';
      syncBtn.title = 'Sync playback with friends';

      var transportControls = document.querySelector('.transport-controls');
      if (transportControls) {
        transportControls.parentNode.insertBefore(syncBtn, transportControls);
      }

      syncBtn.addEventListener('click', toggleListenTogether);
    }

    function toggleListenTogether() {
      if (syncEnabled) {
        disableSync();
      } else {
        showSyncDialog();
      }
    }

    function showSyncDialog() {
      var existing = document.getElementById('sync-modal');
      if (existing) {
        existing.showModal();
        return;
      }

      var modal = document.createElement('dialog');
      modal.id = 'sync-modal';
      modal.className = 'sync-modal';

      var libraryId = (window.location.pathname.split('/s/')[1] || '').split('?')[0].split('#')[0];
      var joinUrl = window.location.origin + '/s/' + libraryId + '?sync=join';
      var qrUrl = 'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=' + encodeURIComponent(joinUrl);

      modal.innerHTML = '<div class="sync-modal-card">' +
        '<div class="sync-modal-head">' +
          '<h2>\u{1F3B5} Listen Together</h2>' +
          '<button type="button" class="frame-button sync-close-btn">&times;</button>' +
        '</div>' +
        '<div class="sync-qr-section">' +
          '<p>Scan this QR code to join:</p>' +
          '<img src="' + escapeHtml(qrUrl) + '" alt="QR code to join session" class="sync-qr-img" width="200" height="200">' +
          '<p class="sync-qr-url">' + escapeHtml(joinUrl) + '</p>' +
          '<button type="button" class="frame-button sync-copy-btn">Copy link</button>' +
        '</div>' +
        '<div class="sync-peers-section">' +
          '<p class="sync-peers-count">No one else connected</p>' +
          '<ul class="sync-peers-list" id="sync-peers-list"></ul>' +
        '</div>' +
        '<div class="sync-status-section">' +
          '<p class="sync-status-text" id="sync-status-text">Not connected</p>' +
        '</div>' +
        '<div class="sync-modal-actions">' +
          '<button type="button" class="frame-button primary sync-start-btn">Start Session</button>' +
        '</div>' +
      '</div>';

      document.body.appendChild(modal);

      modal.querySelector('.sync-close-btn').addEventListener('click', function () {
        modal.close();
      });

      modal.querySelector('.sync-copy-btn').addEventListener('click', function () {
        navigator.clipboard.writeText(joinUrl).then(function () {
          this.textContent = 'Copied!';
        }.bind(modal.querySelector('.sync-copy-btn')));
      });

      modal.querySelector('.sync-start-btn').addEventListener('click', function () {
        enableSync(libraryId);
        modal.querySelector('.sync-start-btn').textContent = 'Connected \u2713';
        modal.querySelector('.sync-start-btn').disabled = true;
        modal.querySelector('.sync-status-text').textContent = 'Session active \u2014 listening together';
      });

      modal.showModal();

      if (window.location.search.indexOf('sync=join') !== -1) {
        modal.querySelector('.sync-start-btn').click();
      }
    }

    function enableSync(libraryId) {
      syncRoom = 'sync:' + libraryId;
      syncEnabled = true;

      var btn = document.querySelector('[data-sync-toggle]');
      if (btn) btn.classList.add('is-active');

      if (typeof io === 'undefined') {
        loadSocketIO(function () {
          connectSocket(libraryId);
        });
      } else {
        connectSocket(libraryId);
      }
    }

    function loadSocketIO(callback) {
      var script = document.createElement('script');
      script.src = 'https://cdn.socket.io/4.7.5/socket.io.min.js';
      script.onload = callback;
      document.head.appendChild(script);
    }

    function connectSocket(libraryId) {
      syncSocket = io({
        transports: ['websocket', 'polling']
      });

      syncSocket.on('connect', function () {
        syncConnected = true;
        syncPeerId = syncSocket.id;
        syncSocket.emit('join_session', { library_id: libraryId });
        updateSyncStatus();
        startResyncTimer();
      });

      syncSocket.on('joined', function (data) {
        syncPeerId = data.peer_id;
        updateSyncStatus();
      });

      syncSocket.on('peer_joined', function (data) {
        syncPeers[data.peer_id] = Date.now();
        updateSyncPeers();
      });

      syncSocket.on('peer_left', function (data) {
        delete syncPeers[data.peer_id];
        updateSyncPeers();
      });

      syncSocket.on('sync_action', function (data) {
        if (data.peer_id === syncPeerId) return;
        if (Date.now() < syncIgnoreUntil) return;
        applyRemoteAction(data);
      });

      syncSocket.on('sync_state', function (data) {
        if (data.peer_id === syncPeerId) return;
        syncWithRemoteState(data);
      });

      syncSocket.on('disconnect', function () {
        syncConnected = false;
        updateSyncStatus();
      });
    }

    function applyRemoteAction(data) {
      if (!player) return;

      switch (data.action) {
        case 'play':
          if (data.track_id) {
            var row = findRowByTrackId(data.track_id);
            if (row) selectRow(row, false);
          }
          if (player.src) {
            if (typeof data.position === 'number' && data.position > 0) {
              player.currentTime = data.position;
            }
            player.play().catch(function () {});
          }
          break;
        case 'pause':
          player.pause();
          if (typeof data.position === 'number' && data.position > 0) {
            player.currentTime = data.position;
          }
          break;
        case 'seek':
          if (typeof data.position === 'number' && data.position >= 0 && player.src) {
            player.currentTime = data.position;
          }
          break;
        case 'next':
          if (nextButton) nextButton.click();
          break;
        case 'prev':
          if (prevButton) prevButton.click();
          break;
      }
    }

    function syncWithRemoteState(data) {
      if (!player || !player.src) return;

      var currentTrack = trackStateFromRow(currentPlaybackRow());
      if (!currentTrack || currentTrack.id !== data.track_id) return;

      var diff = Math.abs(player.currentTime - (data.position || 0));
      if (diff > 0.3) {
        player.currentTime = data.position || 0;
      }

      if (data.playing && player.paused) {
        player.play().catch(function () {});
      } else if (!data.playing && !player.paused) {
        player.pause();
      }
    }

    function broadcastAction(action, extra) {
      if (!syncSocket || !syncEnabled || !syncRoom) return;

      var libId = syncRoom.replace('sync:', '');
      var track = trackStateFromRow(currentPlaybackRow());
      var trackId = track ? track.id : '';

      var data = Object.assign({
        library_id: libId,
        action: action,
        track_id: trackId,
        position: player ? player.currentTime : 0
      }, extra || {});

      syncSocket.emit('sync_action', data);
      syncIgnoreUntil = Date.now() + 500;
    }

    function startResyncTimer() {
      if (syncResyncTimer) clearInterval(syncResyncTimer);
      syncResyncTimer = setInterval(function () {
        if (!syncSocket || !syncEnabled) return;
        var libId = syncRoom ? syncRoom.replace('sync:', '') : '';
        var track = trackStateFromRow(currentPlaybackRow());
        syncSocket.emit('sync_state', {
          library_id: libId,
          action: 'state',
          track_id: track ? track.id : '',
          position: player ? player.currentTime : 0,
          playing: player ? !player.paused : false
        });
      }, 5000);
    }

    function disableSync() {
      syncEnabled = false;
      if (syncResyncTimer) clearInterval(syncResyncTimer);
      if (syncSocket) {
        syncSocket.emit('leave_session', { library_id: syncRoom ? syncRoom.replace('sync:', '') : '' });
        syncSocket.disconnect();
        syncSocket = null;
      }
      syncPeers = {};

      var btn = document.querySelector('[data-sync-toggle]');
      if (btn) btn.classList.remove('is-active');

      updateSyncPeers();
      updateSyncStatus();
    }

    function updateSyncStatus() {
      var el = document.getElementById('sync-status-text');
      if (!el) return;
      el.textContent = syncConnected ? 'Connected \u2014 ' + (Object.keys(syncPeers).length + 1) + ' listening' : 'Not connected';
    }

    function updateSyncPeers() {
      var count = document.querySelector('.sync-peers-count');
      var list = document.getElementById('sync-peers-list');
      var peerCount = Object.keys(syncPeers).length;
      if (count) count.textContent = peerCount + ' other' + (peerCount !== 1 ? 's' : '') + ' connected';
      if (list) {
        list.innerHTML = '';
        Object.keys(syncPeers).forEach(function (id) {
          var li = document.createElement('li');
          li.textContent = '\u{1F464} Friend (' + id.slice(0, 8) + ')';
          list.appendChild(li);
        });
      }
    }

    if (document.querySelector('.transport-band')) {
      initListenTogether();

      if (player) {
        var origPlay = player.play;
        player.play = function () {
          var result = origPlay.call(player);
          if (syncEnabled) broadcastAction('play');
          return result;
        };

        var origPause = player.pause;
        player.pause = function () {
          if (syncEnabled) broadcastAction('pause');
          return origPause.call(player);
        };

        if (progressInput) {
          progressInput.addEventListener('change', function () {
            if (syncEnabled) broadcastAction('seek', { position: player.currentTime });
          });
        }

        if (nextButton) {
          nextButton.addEventListener('click', function () {
            if (syncEnabled) setTimeout(function () { broadcastAction('next'); }, 100);
          });
        }
        if (prevButton) {
          prevButton.addEventListener('click', function () {
            if (syncEnabled) setTimeout(function () { broadcastAction('prev'); }, 100);
          });
        }
      }
    }
  })();
})();
