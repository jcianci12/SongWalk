(function() {
  var selectRow = window.__songwalk.selectRow;
  var findRowByTrackId = window.__songwalk.findRowByTrackId;
  var trackStateFromRow = window.__songwalk.trackStateFromRow;
  var currentPlaybackRow = window.__songwalk.currentPlaybackRow;
  var refreshLibraryAfterMutation = window.__songwalk.refreshLibraryAfterMutation;
  var player = window.__songwalk.player;
  var nextButton = window.__songwalk.nextButton;
  var prevButton = window.__songwalk.prevButton;
  var progressInput = window.__songwalk.progressInput;
  var escapeHtml = window.__songwalk.escapeHtml;

  // ---- Running people widget in title bar ----
  (function injectRunnersWidget() {
    var titleLeft = document.querySelector('.title-band-left');
    if (!titleLeft) return;

    var widget = document.createElement('div');
    widget.className = 'sync-runners-widget';
    widget.id = 'sync-runners-widget';
    widget.style.display = 'none';
    widget.innerHTML = '<div class="sync-runners-title-band" id="sync-runners-tb"></div>';
    // Insert after the brand link, before crumbs
    var brand = titleLeft.querySelector('.app-brand');
    if (brand && brand.nextSibling) {
      titleLeft.insertBefore(widget, brand.nextSibling);
    } else {
      titleLeft.appendChild(widget);
    }
  })();

  // Repurpose "Share access" link as "Listen Together" — BEFORE overflow menu runs
  (function initListenTogether() {
    var titleActions = document.querySelector('.title-actions');
    if (!titleActions) return;

    var links = titleActions.querySelectorAll('a.frame-button');
    var shareLink = null;
    for (var i = 0; i < links.length; i++) {
      if ((links[i].textContent || '').trim() === 'Share access') {
        shareLink = links[i];
        break;
      }
    }

    if (shareLink) {
      shareLink.removeAttribute('href');
      shareLink.style.cursor = 'pointer';
      shareLink.innerHTML = '\u{1F3B5} Listen Together';
      shareLink.title = 'Sync playback with friends';
      shareLink.setAttribute('data-sync-toggle', '');
      shareLink.addEventListener('click', function (e) {
        e.preventDefault();
        if (window.__songwalkToggleSync) window.__songwalkToggleSync();
      });
    }
  })();

  (function bindListenTogether() {
    var syncSocket = null;
    var syncPeerId = null;
    var syncConnected = false;
    var syncEnabled = false;
    var syncRoom = null;
    var syncResyncTimer = null;
    var syncPeers = {};

    function toggleListenTogether() {
      if (syncEnabled) {
        showSyncDialog();
      } else {
        showSyncDialog();
      }
    }

    // Expose for the initListenTogether IIFE and auto-join
    window.__songwalkToggleSync = toggleListenTogether;
    window.__songwalkShowSyncDialog = showSyncDialog;

    function showSyncDialog() {
      var existing = document.getElementById('sync-modal');
      if (existing) {
        existing.showModal();
        // Reconnect if not already connected
        var libraryId = (window.location.pathname.split('/s/')[1] || '').split('?')[0].split('#')[0];
        if (!syncEnabled) enableSync(libraryId);
        return;
      }

      var modal = document.createElement('dialog');
      modal.id = 'sync-modal';
      modal.className = 'sync-modal';

      var libraryId = (window.location.pathname.split('/s/')[1] || '').split('?')[0].split('#')[0];
      // Embed server time in join URL for instant clock calibration
      var stParam = syncServerTimeOffset ? '&st=' + Math.round((Date.now() + syncServerTimeOffset) / 1000) : '';
      var joinUrl = window.location.origin + '/s/' + libraryId + '?sync=join' + stParam;
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
        '<div class="sync-listeners-row">' +
          '<div class="sync-runners" id="sync-runners"></div>' +
        '</div>' +
        '<div class="sync-peers-section">' +
          '<p class="sync-peers-count">Connecting\u2026</p>' +
          '<ul class="sync-peers-list" id="sync-peers-list"></ul>' +
        '</div>' +
        '<div class="sync-status-section">' +
          '<p class="sync-status-text" id="sync-status-text">Connecting\u2026</p>' +
          '<p class="sync-debug-text" id="sync-debug-text" style="font-size:0.72rem;color:var(--text-faint);margin:4px 0 0;"></p>' +
        '</div>' +
        '<div class="sync-modal-actions">' +
          '<button type="button" class="frame-button danger sync-leave-btn">Leave Session</button>' +
        '</div>' +
      '</div>';

      document.body.appendChild(modal);

      modal.querySelector('.sync-copy-btn').addEventListener('click', function () {
        navigator.clipboard.writeText(joinUrl).then(function () {
          this.textContent = 'Copied!';
        }.bind(modal.querySelector('.sync-copy-btn')));
      });

      // Close button just hides the dialog — session keeps running
      modal.querySelector('.sync-close-btn').addEventListener('click', function () {
        modal.close();
      });

      // Leave session button fully disconnects
      modal.querySelector('.sync-leave-btn').addEventListener('click', function () {
        disableSync();
        modal.close();
        // Reset dialog to fresh state
        modal.remove();
      });

      modal.showModal();

      // Auto-connect immediately
      enableSync(libraryId);
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

    var syncServerTimeOffset = 0;  // server clock offset in ms
    var latestVersion = 0;         // latest state version seen, ignore older

    function connectSocket(libraryId) {
      syncSocket = io({
        transports: ['websocket', 'polling']
      });

      // Debug: log transport + connection events to console
      syncSocket.io.on('reconnect_attempt', function () {
        console.log('[Sync] Reconnect attempt, transport:', syncSocket.io.engine.transport.name);
      });
      syncSocket.io.on('reconnect', function () {
        console.log('[Sync] Reconnected');
      });

      syncSocket.on('connect', function () {
        syncConnected = true;
        syncPeerId = syncSocket.id;
        var transport = syncSocket.io.engine.transport.name;
        console.log('[Sync] Connected — transport:', transport, '— socket id:', syncPeerId);
        showDebugText('Connected via ' + transport);
        syncSocket.emit('join_session', { library_id: libraryId });
        updateSyncStatus();
        stopPollFallback();
        startResyncTimer();
      });

      syncSocket.on('connect_error', function (err) {
        console.error('[Sync] Connection error:', err.message);
        showDebugText('Error: ' + err.message);
        startPollFallback(libraryId);
      });

      syncSocket.on('reconnect_error', function (err) {
        console.error('[Sync] Reconnect error:', err.message);
        showDebugText('Reconnect error: ' + err.message);
      });

      syncSocket.on('joined', function (data) {
        syncPeerId = data.peer_id;
        // Compute clock offset: server time minus our local time
        if (data.server_time) {
          syncServerTimeOffset = (data.server_time * 1000) - Date.now();
          console.log('[Sync] Clock offset:', Math.round(syncServerTimeOffset), 'ms');
        }
        updateSyncStatus();

        // If session already has state, join it
        if (data.sync_state && data.sync_state.track_id) {
          var state = data.sync_state;
          console.log('[Sync] Joining session:', state.track_id, state.playing ? 'playing' : 'paused');
          var row = findRowByTrackId(state.track_id);
          if (row && player) {
            selectRow(row, false);
            // Calculate elapsed time since state was recorded
            var serverNow = data.server_time || (Date.now() / 1000);
            var stateAge = serverNow - (state.server_time || serverNow);
            var pos = (state.position || 0);
            if (state.playing) {
              // Advance position by elapsed time
              pos += Math.max(0, stateAge);
            }
            if (pos > 0) player.currentTime = pos;
            if (state.playing) {
              player.play().catch(function () {});
            }
            lastSyncAnchor = {
              trackId: state.track_id,
              position: pos,
              serverTime: serverNow,
              playing: state.playing
            };
          }
        }
      });

      syncSocket.on('peer_joined', function (data) {
        // Rebuild full peer list from server (excludes self)
        syncPeers = {};
        (data.peers || []).forEach(function (pid) {
          if (pid !== syncPeerId) syncPeers[pid] = Date.now();
        });
        updateSyncPeers();
        updateSyncStatus();
      });

      syncSocket.on('peer_left', function (data) {
        syncPeers = {};
        (data.peers || []).forEach(function (pid) {
          if (pid !== syncPeerId) syncPeers[pid] = Date.now();
        });
        updateSyncPeers();
        updateSyncStatus();
      });

      syncSocket.on('sync_action', function (data) {
        if (data.peer_id === syncPeerId) return;

        // Ignore stale/duplicate states using server version
        if (data.version && data.version <= latestVersion) {
          console.log('[Sync] Ignoring stale action v' + data.version + ' (have v' + latestVersion + ')');
          return;
        }
        latestVersion = data.version || latestVersion;

        // Scheduled execution: queue action for the server's execute_at time
        if (data.execute_at) {
          var serverExecuteMs = data.execute_at * 1000;
          var localTimeMs = Date.now();
          var localExecuteMs = serverExecuteMs - (syncServerTimeOffset || 0);
          var delay = Math.max(0, localExecuteMs - localTimeMs);
          console.log('[Sync] Scheduling', data.action, 'v' + data.version, 'in', Math.round(delay), 'ms');
          setTimeout(function () {
            applyRemoteAction(data);
          }, delay);
        } else {
          applyRemoteAction(data);
        }
      });

      syncSocket.on('sync_state', function (data) {
        if (data.peer_id === syncPeerId) return;
        // Only use for drift check if version is newer
        if (data.version && data.version <= latestVersion) return;
        syncWithRemoteState(data);
      });

      syncSocket.on('library_changed', function (data) {
        if (data.peer_id === syncPeerId) return;
        if (!data.library_id || !syncRoom) return;
        var ourLibId = syncRoom.replace('sync:', '');
        if (data.library_id !== ourLibId) return;
        // Skip if already refreshing from our own HTTP response.
        if (window.__songwalk.isReloadingForSharedLibraryState) return;

        var opts = {};
        if (data.event === 'track_deleted' && data.payload) {
          var ids = data.payload.track_ids || [];
          if (!ids.length && data.payload.track_id) ids = [data.payload.track_id];
          opts.deletedTrackIds = ids;
        }
        refreshLibraryAfterMutation(opts);
      });

      syncSocket.on('disconnect', function (reason) {
        syncConnected = false;
        console.log('[Sync] Disconnected — reason:', reason);
        showDebugText('Disconnected: ' + (reason || 'unknown'));
        updateSyncStatus();
      });
    }

    var isRemoteAction = false;  // flag to suppress broadcast during remote sync

    function applyRemoteAction(data) {
      if (!player) return;
      isRemoteAction = true;

      // Server sends authoritative track_id + position — just apply
      if (data.track_id) {
        var currentTrack = trackStateFromRow(currentPlaybackRow());
        if (!currentTrack || currentTrack.id !== data.track_id) {
          var row = findRowByTrackId(data.track_id);
          if (row) selectRow(row, false);
        }
      }

      if (typeof data.position === 'number' && data.position >= 0 && player.src) {
        player.currentTime = data.position;
      }

      if (data.playing && player.paused && player.src) {
        player.play().catch(function () {});
      } else if (!data.playing && !player.paused) {
        player.pause();
      }

      isRemoteAction = false;
    }

    var lastSyncAnchor = { trackId: '', position: 0, serverTime: 0, playing: false };

    function syncWithRemoteState(data) {
      if (!player || !player.src) return;

      var currentTrack = trackStateFromRow(currentPlaybackRow());
      if (!currentTrack || currentTrack.id !== data.track_id) return;

      // Reset anchor if track changed
      if (lastSyncAnchor.trackId !== data.track_id) {
        lastSyncAnchor = { trackId: data.track_id, position: 0, serverTime: 0, playing: false };
      }

      var remotePos = data.position || 0;
      var serverTime = data.server_time || (Date.now() / 1000);

      // Always update anchor from newest authoritative state
      if (!lastSyncAnchor.serverTime || serverTime >= lastSyncAnchor.serverTime) {
        lastSyncAnchor = {
          trackId: data.track_id,
          position: remotePos,
          serverTime: serverTime,
          playing: data.playing
        };
      }

      // Calculate expected position from anchor: paused = fixed, playing = advancing
      var myNow = Date.now() / 1000;
      var myOffset = (syncServerTimeOffset || 0) / 1000;
      var elapsed = myNow - lastSyncAnchor.serverTime - myOffset;
      var expectedPos = lastSyncAnchor.playing
        ? lastSyncAnchor.position + elapsed
        : lastSyncAnchor.position;

      var drift = Math.abs(player.currentTime - expectedPos);

      // Only correct if drifted >500ms and anchor is recent (<10s)
      if (drift > 0.5 && (myNow - lastSyncAnchor.serverTime) < 10) {
        console.log('[Sync] Drift correction:', Math.round(drift * 1000), 'ms →', Math.round(expectedPos * 1000) / 1000);
        player.currentTime = expectedPos;
        lastSyncAnchor = {
          trackId: data.track_id,
          position: expectedPos,
          serverTime: myNow + myOffset,
          playing: lastSyncAnchor.playing
        };
      }

      // Sync play/pause state only if anchor is recent
      if ((myNow - lastSyncAnchor.serverTime) < 5) {
        if (data.playing && player.paused && player.src) {
          player.play().catch(function () {});
        } else if (!data.playing && !player.paused) {
          player.pause();
        }
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
      stopPollFallback();
      if (syncResyncTimer) clearInterval(syncResyncTimer);
      if (syncSocket) {
        syncSocket.emit('leave_session', { library_id: syncRoom ? syncRoom.replace('sync:', '') : '' });
        syncSocket.disconnect();
        syncSocket = null;
      }
      syncPeers = {};

      var btn = document.querySelector('[data-sync-toggle]');
      if (btn) btn.classList.remove('is-active');

      // Hide title bar runners
      var widget = document.getElementById('sync-runners-widget');
      if (widget) widget.style.display = 'none';

      updateSyncPeers();
      updateSyncStatus();
    }

    function updateSyncStatus() {
      var el = document.getElementById('sync-status-text');
      if (!el) return;
      var total = Object.keys(syncPeers).length + 1; // + self
      el.textContent = syncConnected ? 'Connected \u2014 ' + total + ' listening' : 'Not connected';
    }

    function showDebugText(msg) {
      var el = document.getElementById('sync-debug-text');
      if (el) el.textContent = msg;
    }

    // ---- HTTP polling fallback when WebSocket is blocked ----
    var pollTimer = null;

    function startPollFallback(libraryId) {
      if (pollTimer) return;  // already polling
      showDebugText('Polling via HTTP (WebSocket blocked)');
      console.log('[Sync] Starting HTTP poll fallback (sequential)');

      function poll() {
        if (!pollTimer) return;  // stopped
        fetch('/s/' + libraryId + '/state', {
          headers: { 'Accept': 'application/json', 'X-Requested-With': 'fetch' }
        }).then(function (r) { return r.json(); }).then(function (state) {
          if (state && state.sync_state && state.sync_state.peer_id !== syncPeerId) {
            var data = state.sync_state;
            if (data.track_id && data.position !== undefined) {
              syncWithRemoteState(data);
            }
            isRemoteAction = false;
          }
        }).catch(function () {
          // Network error — just wait and retry
        }).finally(function () {
          // Schedule next poll only after this one completes
          if (pollTimer) {
            pollTimer = setTimeout(poll, 2000);
          }
        });
      }

      pollTimer = setTimeout(poll, 1000);  // start first poll after 1s
    }

    function stopPollFallback() {
      if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
        console.log('[Sync] Stopped HTTP poll fallback');
      }
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
      // Update runners in both dialog and title bar
      updateRunners('sync-runners', Object.keys(syncPeers).length);
      updateRunners('sync-runners-tb', Object.keys(syncPeers).length);

      // Show/hide title bar widget
      var widget = document.getElementById('sync-runners-widget');
      if (widget) widget.style.display = syncConnected ? 'flex' : 'none';
    }

    function updateRunners(containerId, count) {
      var container = document.getElementById(containerId);
      if (!container) return;
      if (count === 0) {
        container.innerHTML = '<span class="sync-runner-none">Waiting for friends...</span>';
        return;
      }
      // Use inline data URI for running person (small animated SVG for performance)
      var runnerImg = '<img src="https://media.tenor.com/chfzEVhXQloAAAAj/animated-man-running.gif" class="sync-runner sync-runner-pulse" alt="listener">';
      container.innerHTML = runnerImg.repeat(count + 1); // +1 for self
    }

    if (document.querySelector('.transport-band')) {
      // Auto-join from URL param (e.g. QR code scan)
      if (window.location.search.indexOf('sync=join') !== -1) {
        // Pre-calibrate clock from embedded server timestamp in URL
        var stMatch = window.location.search.match(/[?&]st=(\d+)/);
        if (stMatch) {
          var serverMs = parseInt(stMatch[1], 10) * 1000;
          syncServerTimeOffset = serverMs - Date.now();
          console.log('[Sync] Pre-calibrated clock offset from URL:', Math.round(syncServerTimeOffset), 'ms');
        }
        if (window.__songwalkShowSyncDialog) window.__songwalkShowSyncDialog();
      }

      if (player) {
        var origPlay = player.play;
        player.play = function () {
          var result = origPlay.call(player);
          if (syncEnabled && !isRemoteAction) broadcastAction('play');
          return result;
        };

        var origPause = player.pause;
        player.pause = function () {
          if (syncEnabled && !isRemoteAction) broadcastAction('pause');
          return origPause.call(player);
        };

        if (progressInput) {
          progressInput.addEventListener('change', function () {
            if (syncEnabled) broadcastAction('seek', { position: player.currentTime, playing: !player.paused });
          });
        }

        if (nextButton) {
          nextButton.addEventListener('click', function () {
            if (syncEnabled) setTimeout(function () {
              var track = trackStateFromRow(currentPlaybackRow());
              broadcastAction('play', { track_id: track ? track.id : '', position: 0 });
            }, 200);
          });
        }
        if (prevButton) {
          prevButton.addEventListener('click', function () {
            if (syncEnabled) setTimeout(function () {
              var track = trackStateFromRow(currentPlaybackRow());
              broadcastAction('play', { track_id: track ? track.id : '', position: 0 });
            }, 200);
          });
        }
      }
    }
  })();

  // ---- Album drag-to-reorder ----
  (function bindAlbumDragReorder() {
    var albumSections = document.querySelectorAll('[data-album-section]');
    if (!albumSections.length) return;

    albumSections.forEach(function (section) {
      section.setAttribute('draggable', 'true');

      section.addEventListener('dragstart', function (e) {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', '');
        section.classList.add('is-drag-source');
      });

      section.addEventListener('dragend', function () {
        section.classList.remove('is-drag-source');
        document.querySelectorAll('.album-section').forEach(function (s) {
          s.classList.remove('is-drop-target');
        });
      });

      section.addEventListener('dragenter', function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        section.classList.add('is-drop-target');
      });

      section.addEventListener('dragover', function (e) {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
      });

      section.addEventListener('dragleave', function () {
        section.classList.remove('is-drop-target');
      });

      section.addEventListener('drop', function (e) {
        e.preventDefault();
        section.classList.remove('is-drop-target');
        var source = document.querySelector('.album-section.is-drag-source');
        if (!source || source === section) return;

        // Swap positions in DOM
        var parent = section.parentNode;
        var sourceNext = source.nextSibling;
        var targetNext = section.nextSibling;

        if (sourceNext === section) {
          // Source was directly above target
          parent.insertBefore(section, source);
        } else if (targetNext === source) {
          // Target was directly above source
          parent.insertBefore(source, section);
        } else {
          parent.insertBefore(source, targetNext);
          parent.insertBefore(section, sourceNext);
        }

        // Send new album order to server
        var libraryId = (window.location.pathname.split('/s/')[1] || '').split('?')[0];
        var albumKeys = [];
        parent.querySelectorAll('[data-album-section]').forEach(function (s) {
          var key = s.getAttribute('data-album-key');
          if (key) albumKeys.push(key);
        });

        fetch('/s/' + libraryId + '/albums/reorder', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-Requested-With': 'fetch' },
          body: JSON.stringify({ album_keys: albumKeys })
        }).catch(function () {});
      });
    });
  })();

  // ---- Offline mode toggle ----
  (function bindOfflineMode() {
    if (!('serviceWorker' in navigator)) return;

    var titleActions = document.querySelector('.title-actions');
    if (!titleActions) return;

    var offlineBtn = document.createElement('button');
    offlineBtn.type = 'button';
    offlineBtn.className = 'frame-button';
    offlineBtn.setAttribute('data-offline-toggle', '');
    offlineBtn.innerHTML = '&#9723; Offline';
    offlineBtn.title = 'Cache library for offline playback';
    offlineBtn.style.whiteSpace = 'nowrap';
    titleActions.appendChild(offlineBtn);

    var isCaching = false;
    var cachedCount = 0;

    offlineBtn.addEventListener('click', async function () {
      if (isCaching) return;

      // Wait for service worker to be ready
      await navigator.serviceWorker.ready;
      if (!navigator.serviceWorker.controller) {
        offlineBtn.textContent = 'Reload page & retry';
        setTimeout(function () { offlineBtn.textContent = '\u25A1 Offline'; }, 3000);
        return;
      }
      if (isCaching) return;
      isCaching = true;
      offlineBtn.textContent = 'Caching...';
      offlineBtn.disabled = true;

      // Collect all track URLs from the page
      var tracks = [];
      document.querySelectorAll('[data-track-src]').forEach(function (row) {
        tracks.push({
          id: row.getAttribute('data-track-id'),
          url: row.getAttribute('data-track-src')
        });
      });

      if (!tracks.length) {
        offlineBtn.textContent = 'No tracks';
        offlineBtn.disabled = false;
        isCaching = false;
        return;
      }

      // Listen for progress from service worker
      var onMessage = function (event) {
        if (event.data && event.data.action === 'cache-progress') {
          cachedCount = event.data.cached;
          offlineBtn.textContent = 'Caching ' + cachedCount + '/' + event.data.total;
        }
      };
      navigator.serviceWorker.addEventListener('message', onMessage);

      // Tell service worker to cache all tracks
      var channel = new MessageChannel();
      channel.port1.onmessage = function (event) {
        navigator.serviceWorker.removeEventListener('message', onMessage);
        isCaching = false;
        offlineBtn.disabled = false;
        if (event.data.done) {
          cachedCount = event.data.cached;
          offlineBtn.innerHTML = '\u2713 Offline (' + cachedCount + ')';
          offlineBtn.classList.add('is-active');
        } else {
          offlineBtn.textContent = 'Offline failed';
        }
      };

      navigator.serviceWorker.controller.postMessage(
        { action: 'cache-tracks', tracks: tracks },
        [channel.port2]
      );
    });

    // Check existing cache on load
    caches.open('songwalk-v2').then(function (cache) {
      cache.keys().then(function (keys) {
        var audioKeys = keys.filter(function (k) {
          return k.url.indexOf('/files/') !== -1;
        });
        if (audioKeys.length > 0) {
          cachedCount = audioKeys.length;
          offlineBtn.innerHTML = '\u2713 Offline (' + cachedCount + ')';
          offlineBtn.classList.add('is-active');
        }
      });
    });
  })();
})();
