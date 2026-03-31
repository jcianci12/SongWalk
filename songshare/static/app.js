(function () {
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
  if (uploadForm && hiddenFileInput) {
    const dropzone = uploadForm.querySelector("[data-dropzone]");
    const statusLine = uploadForm.querySelector("[data-upload-status]");

    function setUploadState(message, active) {
      if (statusLine) {
        statusLine.textContent = message;
      }
      uploadForm.classList.toggle("is-busy", Boolean(active));
    }

    async function sendFiles(fileList) {
      if (!fileList || !fileList.length) {
        return;
      }

      const body = new FormData();
      Array.from(fileList).forEach((file) => body.append("tracks", file));
      setUploadState(`Uploading ${fileList.length} track${fileList.length === 1 ? "" : "s"}...`, true);

      const response = await fetch(uploadForm.action, {
        method: "POST",
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
        body,
      });

      const payload = await response.json();
      if (payload.ok) {
        window.location.reload();
        return;
      }

      setUploadState(payload.error || (payload.errors && payload.errors[0]) || "Upload failed.", false);
    }

    hiddenFileInput.addEventListener("change", async () => {
      await sendFiles(hiddenFileInput.files);
    });

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
      if (event.dataTransfer && event.dataTransfer.files.length) {
        await sendFiles(event.dataTransfer.files);
      }
    });
  }

  const rows = Array.from(document.querySelectorAll("[data-track-row]"));
  const albumSections = Array.from(document.querySelectorAll("[data-album-section]"));
  const player = document.getElementById("deck-player");
  const titleTarget = document.getElementById("now-playing-title");
  const metaTarget = document.getElementById("now-playing-meta");
  const artTarget = document.getElementById("selection-art");
  const editForm = document.querySelector("[data-editor-form]");
  const titleInput = document.getElementById("edit-title");
  const artistInput = document.getElementById("edit-artist");
  const albumInput = document.getElementById("edit-album");
  const saveButton = document.getElementById("save-track");
  const deleteButton = document.getElementById("delete-track");
  const filterInput = document.querySelector("[data-track-filter]");
  const playButton = document.querySelector("[data-transport-play]");
  const prevButton = document.querySelector("[data-transport-prev]");
  const nextButton = document.querySelector("[data-transport-next]");
  const progressInput = document.querySelector("[data-transport-progress]");
  const volumeInput = document.querySelector("[data-transport-volume]");
  const currentTimeTarget = document.getElementById("current-time");
  const durationTarget = document.getElementById("duration-time");

  let selectedRow = null;

  function visibleRows() {
    return rows.filter((row) => !row.hidden);
  }

  function setEditorEnabled(enabled) {
    [titleInput, artistInput, albumInput, saveButton, deleteButton].forEach((element) => {
      if (element) {
        element.disabled = !enabled;
      }
    });
  }

  function updatePlayButton() {
    if (!playButton || !player) {
      return;
    }

    playButton.innerHTML = player.paused ? "&#9654;" : "&#10074;&#10074;";
  }

  function selectRow(row, autoplay) {
    if (!row) {
      return;
    }

    if (selectedRow) {
      selectedRow.classList.remove("is-selected");
    }

    selectedRow = row;
    selectedRow.classList.add("is-selected");

    const title = row.getAttribute("data-track-title") || row.getAttribute("data-track-filename") || "Selected track";
    const artist = row.getAttribute("data-track-artist") || "Unknown artist";
    const album = row.getAttribute("data-track-album") || "Unknown album";
    const filename = row.getAttribute("data-track-filename") || "";
    const initials = (album || title)
      .split(" ")
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0].toUpperCase())
      .join("") || "SS";

    titleTarget.textContent = title;
    metaTarget.textContent = `${artist} - ${album} - ${filename}`;
    artTarget.textContent = initials;

    titleInput.value = title;
    artistInput.value = artist === "Unknown artist" ? "" : artist;
    albumInput.value = album === "Unknown album" ? "" : album;
    editForm.action = row.getAttribute("data-track-update-url") || "";
    deleteButton.setAttribute("data-delete-url", row.getAttribute("data-track-delete-url") || "");
    setEditorEnabled(true);

    if (player) {
      const src = row.getAttribute("data-track-src");
      if (src && player.getAttribute("src") !== src) {
        player.src = src;
        progressInput.value = 0;
        currentTimeTarget.textContent = "0:00";
        durationTarget.textContent = "0:00";
      }

      if (autoplay) {
        player.play().catch(() => {});
      }
    }

    updatePlayButton();
  }

  if (rows.length) {
    rows.forEach((row) => {
      row.addEventListener("click", () => {
        selectRow(row, false);
      });

      row.addEventListener("dblclick", () => {
        selectRow(row, true);
      });
    });

    selectRow(rows[0], false);
  } else {
    setEditorEnabled(false);
  }

  if (filterInput && rows.length) {
    filterInput.addEventListener("input", () => {
      const query = filterInput.value.trim().toLowerCase();

      rows.forEach((row) => {
        const haystack = row.getAttribute("data-search") || "";
        row.hidden = Boolean(query) && !haystack.includes(query);
      });

      albumSections.forEach((section) => {
        const hasVisibleRows = Array.from(section.querySelectorAll("[data-track-row]")).some((row) => !row.hidden);
        section.hidden = !hasVisibleRows;
      });
    });
  }

  if (editForm) {
    editForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!editForm.action) {
        return;
      }

      const response = await fetch(editForm.action, {
        method: "POST",
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
        body: new FormData(editForm),
      });

      if (!response.ok) {
        return;
      }

      window.location.reload();
    });
  }

  if (deleteButton) {
    deleteButton.addEventListener("click", async () => {
      const url = deleteButton.getAttribute("data-delete-url");
      if (!url || !window.confirm("Delete this track from the shared library?")) {
        return;
      }

      const response = await fetch(url, {
        method: "POST",
        headers: { Accept: "application/json", "X-Requested-With": "fetch" },
      });

      if (response.ok) {
        window.location.reload();
      }
    });
  }

  if (player && playButton) {
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

    prevButton.addEventListener("click", () => {
      const visible = visibleRows();
      if (!visible.length) {
        return;
      }

      const currentIndex = Math.max(visible.indexOf(selectedRow), 0);
      const target = visible[Math.max(currentIndex - 1, 0)];
      selectRow(target, true);
    });

    nextButton.addEventListener("click", () => {
      const visible = visibleRows();
      if (!visible.length) {
        return;
      }

      const currentIndex = Math.max(visible.indexOf(selectedRow), 0);
      const target = visible[Math.min(currentIndex + 1, visible.length - 1)];
      selectRow(target, true);
    });

    if (volumeInput) {
      player.volume = Number(volumeInput.value);
      volumeInput.addEventListener("input", () => {
        player.volume = Number(volumeInput.value);
      });
    }

    if (progressInput) {
      progressInput.addEventListener("input", () => {
        if (player.duration) {
          player.currentTime = (Number(progressInput.value) / 100) * player.duration;
        }
      });
    }

    player.addEventListener("timeupdate", () => {
      if (!progressInput) {
        return;
      }

      const progress = player.duration ? (player.currentTime / player.duration) * 100 : 0;
      progressInput.value = progress;
      currentTimeTarget.textContent = formatTime(player.currentTime);
      durationTarget.textContent = formatTime(player.duration);
    });

    player.addEventListener("play", updatePlayButton);
    player.addEventListener("pause", updatePlayButton);
    player.addEventListener("loadedmetadata", () => {
      durationTarget.textContent = formatTime(player.duration);
    });
    player.addEventListener("ended", () => {
      const visible = visibleRows();
      const currentIndex = visible.indexOf(selectedRow);
      const target = visible[currentIndex + 1];
      if (target) {
        selectRow(target, true);
      } else {
        player.pause();
        player.currentTime = 0;
        updatePlayButton();
      }
    });

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
