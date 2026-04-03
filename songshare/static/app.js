(function () {
  // Increment this whenever we need to confirm a fresh JS build is running in the browser.
  const SCRIPT_VERSION = "2026-04-03-transport-title-1";
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

  document.querySelectorAll("[data-copy]").forEach((button) => {
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
          setUploadState("Upload complete. Refreshing library...", true);
          const elapsed = performance.now() - startedAt;
          if (elapsed < 450) {
            await new Promise((resolve) => window.setTimeout(resolve, 450 - elapsed));
          }
          window.location.reload();
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

  const rows = Array.from(document.querySelectorAll("[data-track-row]"));
  const albumContainers = Array.from(document.querySelectorAll("[data-album-container]"));
  const albumCards = Array.from(document.querySelectorAll("[data-album-card]"));
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
  const filterInput = document.querySelector("[data-track-filter]");
  const shuffleButton = document.querySelector("[data-transport-shuffle]");
  const prevButton = document.querySelector("[data-transport-prev]");
  const playButton = document.querySelector("[data-transport-play]");
  const nextButton = document.querySelector("[data-transport-next]");
  const repeatButton = document.querySelector("[data-transport-repeat]");
  const contextMenu = document.getElementById("track-context-menu");
  const contextEditField = document.getElementById("context-edit-field");
  const contextFindAlbumInfo = document.getElementById("context-find-album-info");
  const lookupDialog = document.getElementById("lookup-dialog");
  const lookupStatus = document.getElementById("lookup-status");
  const lookupResults = document.getElementById("lookup-results");
  const lookupTitleInput = document.getElementById("lookup-title");
  const lookupArtistInput = document.getElementById("lookup-artist");
  const lookupAlbumInput = document.getElementById("lookup-album");
  const lookupSearchButton = document.getElementById("lookup-search-button");
  const bulkDeleteUrl = deleteButton ? (deleteButton.getAttribute("data-bulk-delete-url") || "") : "";
  const targetAlbumSection = document.querySelector("[data-target-album-section]");
  const mediaSession = typeof navigator !== "undefined" ? navigator.mediaSession : null;

  let selectedRow = null;
  let selectedRows = [];
  let longPressTimer = null;
  let isShuffleEnabled = false;
  let isRepeatEnabled = false;
  const defaultDocumentTitle = document.title;

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

  function currentPlaybackRow() {
    const currentSrc = player ? resolveMediaUrl(player.currentSrc || player.getAttribute("src")) : "";
    if (!currentSrc) {
      return selectedRows.length === 1 ? selectedRow : null;
    }

    return rows.find((row) => rowSourceUrl(row) === currentSrc) || (selectedRows.length === 1 ? selectedRow : null);
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

  // Keep the browser tab tied to the active track instead of selection-only state.
  function syncDocumentTitle(fallbackTitle = defaultDocumentTitle) {
    const track = trackStateFromRow(documentTitleTrack());
    document.title = (track && track.title) || fallbackTitle;
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

  function isMultiSelectEvent(event) {
    return Boolean(event && (event.ctrlKey || event.metaKey));
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

  function matchesSearchValue(haystack, query) {
    return !query || haystack.includes(query);
  }

  function syncAlbumSectionVisibility() {
    albumContainers
      .filter((container) => !container.hasAttribute("data-album-card"))
      .forEach((container) => {
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

    syncAlbumSectionVisibility();
    syncSelectionToVisibleRows();

    debugLog("filter.apply.done", {
      normalizedQuery: query,
      visibleRows: visibleRows().length,
      hiddenRows: rows.filter((row) => row.hidden).length,
      visibleAlbumCards: albumCards.filter((card) => !card.hidden).length,
      hiddenAlbumCards: albumCards.filter((card) => card.hidden).length,
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
    metaTarget.textContent = "Ctrl/Cmd click adds or removes tracks. Delete removes the whole selection.";
    setTransportSelectionSummary(
      `${selectedRows.length} tracks selected`,
      "Open to review the selection state or delete the selected tracks.",
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
    contextMenu.dataset.editField = editField || "";
    contextMenu.hidden = false;
    contextMenu.style.left = `${event.clientX}px`;
    contextMenu.style.top = `${event.clientY}px`;
  }

  function selectRow(row, autoplay) {
    if (!row) {
      return;
    }

    setEditorAccordionOpen(false);
    selectedRow = row;
    selectedRows = [row];
    renderSelection(autoplay);
  }

  function toggleRowSelection(row) {
    if (!row) {
      return;
    }

    if (selectedRows.includes(row)) {
      if (selectedRows.length === 1) {
        selectedRows = [];
        selectedRow = null;
        setEditorAccordionOpen(false);
        renderSelection(false);
        return;
      }

      selectedRows = selectedRows.filter((item) => item !== row);
      if (selectedRow === row) {
        selectedRow = selectedRows[selectedRows.length - 1] || null;
      }
      setEditorAccordionOpen(false);
      renderSelection(false);
      return;
    }

    selectedRows = [...selectedRows, row];
    selectedRow = row;
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

            window.location.reload();
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

  if (rows.length) {
    debugLog("rows.init", {
      rowCount: rows.length,
      albumCardCount: albumCards.length,
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

    rows.forEach((row) => {
      row.addEventListener("click", (event) => {
        if (isMultiSelectEvent(event)) {
          toggleRowSelection(row);
          return;
        }

        selectRow(row, false);
      });

      row.addEventListener("keydown", (event) => {
        if (event.target !== row) {
          return;
        }

        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          selectRow(row, false);
        }
      });

      row.addEventListener("dblclick", () => {
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
    });

    albumCards.forEach((card) => {
      card.addEventListener("click", () => {
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
      });

      card.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") {
          return;
        }

        event.preventDefault();
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
      });
    });

    selectRow(rows[0], false);
  } else {
    setEditorEnabled(false);
  }

  if (targetAlbumSection) {
    window.requestAnimationFrame(() => {
      targetAlbumSection.scrollIntoView({ block: "start", behavior: "smooth" });
    });
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

  if (findAlbumInfoButton) {
    findAlbumInfoButton.addEventListener("click", openLookupDialog);
  }

  if (lookupSearchButton) {
    lookupSearchButton.addEventListener("click", runLookupSearch);
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
    applySearchFilter(filterInput.value);
  } else {
    debugLog("filter.unavailable", {
      filterPresent: Boolean(filterInput),
      rowCount: rows.length,
    });
  }

  if (editForm) {
    editForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!editForm.action) {
        return;
      }

      saveButton.disabled = true;
      try {
        const response = await withGlobalBusy("Saving track...", async () => {
          return await fetch(editForm.action, {
            method: "POST",
            headers: { Accept: "application/json", "X-Requested-With": "fetch" },
            body: new FormData(editForm),
          });
        });

        if (!response.ok) {
          return;
        }

        window.location.reload();
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
          window.location.reload();
        }
      } finally {
        deleteButton.disabled = false;
      }
    });
  }

  if (player && playButton) {
    player.playsInline = true;

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
    player.addEventListener("pause", updatePlayButton);
    player.addEventListener("loadedmetadata", () => {
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
      updateMediaSessionPositionState();
      updatePlayButton();
    });
    player.addEventListener("ratechange", updateMediaSessionPositionState);
    player.addEventListener("emptied", () => {
      syncDocumentTitle();
      syncMediaSession();
    });

    if (!player.getAttribute("src")) {
      syncMediaSession();
    } else {
      updateMediaSessionPlaybackState();
      updateMediaSessionPositionState();
    }

    updatePlayButton();
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
})();
