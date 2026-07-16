(function () {
  var selectRow = window.__songwalk && window.__songwalk.selectRow;
  var findRowByTrackId = window.__songwalk && window.__songwalk.findRowByTrackId;
  var trackStateFromRow = window.__songwalk && window.__songwalk.trackStateFromRow;
  var currentPlaybackRow = window.__songwalk && window.__songwalk.currentPlaybackRow;
  var player = document.getElementById('deck-player');
  var nextButton = document.querySelector('[data-transport-next]');
  var prevButton = document.querySelector('[data-transport-prev]');
  var progressInput = document.querySelector('[data-transport-progress]');

  // ---- Runners widget in title bar ----
  (function injectRunnersWidget() {
    var titleLeft = document.querySelector('.title-band-left');
    if (!titleLeft) return;
    var widget = document.createElement('div');
    widget.className = 'sync-runners-widget';
    widget.id = 'sync-runners-widget';
    widget.style.display = 'none';
    widget.innerHTML = '<div class="sync-runners-title-band" id="sync-runners-tb"></div>';
    var brand = titleLeft.querySelector('.app-brand');
    if (brand && brand.nextSibling) {
      titleLeft.insertBefore(widget, brand.nextSibling);
    } else {
      titleLeft.appendChild(widget);
    }
  })();

  // ---- Repurpose "Share access" link as "Listen Together" ----
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

  // ---- State ----
  var socket = null;
  var enabled = false;
  var peerId = null;
  var peers = [];
  var latestVersion = 0;
  var applyingRemote = false;
  var pendingTimer = null;

  // ---- Diagnostic log (detect echo loops) ----
  window.__songwalk_diag = [];
  function diagLog(event, data) {
    var entry = {
      ts: Date.now(),
      event: event,
      playerTime: player ? player.currentTime : null,
      paused: player ? player.paused : null,
      src: player ? (player.getAttribute('src') || '').split('/').pop() : null,
      applyingRemote: applyingRemote,
      data: data || {}
    };
    window.__songwalk_diag.push(entry);
    // Keep last 200 entries max
    if (window.__songwalk_diag.length > 200) window.__songwalk_diag.shift();
  }

  // ---- User-initiated actions ----
  function userPlay() {
    if (!player) return;
    player.play().catch(function () {});
    broadcastAction('play');
  }

  function userPause() {
    if (!player) return;
    player.pause();
    broadcastAction('pause');
  }

  function userSeek(pos) {
    broadcastAction('seek', { position: pos, playing: player && !player.paused });
  }

  function userNext() {
    if (nextButton) nextButton.click();
    setTimeout(function () {
      var track = trackStateFromRow ? trackStateFromRow(currentPlaybackRow()) : null;
      broadcastAction('play', { track_id: track ? track.id : '', position: 0 });
    }, 200);
  }

  function userPrev() {
    if (prevButton) prevButton.click();
    setTimeout(function () {
      var track = trackStateFromRow ? trackStateFromRow(currentPlaybackRow()) : null;
      broadcastAction('play', { track_id: track ? track.id : '', position: 0 });
    }, 200);
  }

  function broadcastAction(action, extra) {
    if (!socket || !enabled) return;
    var libId = getLibraryId();
    var track = trackStateFromRow ? trackStateFromRow(currentPlaybackRow && currentPlaybackRow()) : null;
    var data = Object.assign({
      library_id: libId,
      action: action,
      track_id: track ? track.id : '',
      position: player ? player.currentTime : 0
    }, extra || {});
    socket.emit('sync_action', data);
  }

  function getLibraryId() {
    return (window.location.pathname.split('/s/')[1] || '').split('?')[0];
  }

  // ---- Connect / Disconnect ----
  function connect() {
    var libId = getLibraryId();
    if (typeof io === 'undefined') {
      var s = document.createElement('script');
      s.src = 'https://cdn.socket.io/4.7.5/socket.io.min.js';
      s.onload = function () { doConnect(libId); };
      document.head.appendChild(s);
    } else {
      doConnect(libId);
    }
  }

  function doConnect(libId) {
    socket = io({ transports: ['websocket', 'polling'] });

    socket.on('connect', function () {
      peerId = socket.id;
      socket.emit('join_session', { library_id: libId });
    });

    socket.on('joined', function (data) {
      peerId = data.peer_id;
      var state = data.sync_state;
      if (state && state.track_id) {
        applyJoinState(state, data.server_time);
      }
    });

    socket.on('peer_joined', function (data) {
      peers = data.peers || [];
      renderPeers();
    });

    socket.on('peer_left', function (data) {
      peers = data.peers || [];
      renderPeers();
    });

    socket.on('sync_action', function (data) {
      if (data.peer_id === peerId) return;
      if (!isValidAction(data)) return;
      if (data.version && data.version <= latestVersion) return;
      latestVersion = data.version || latestVersion;
      scheduleRemoteAction(data);
    });

    socket.on('disconnect', function () {
      renderStatus('Disconnected');
    });
  }

  function disconnect() {
    if (pendingTimer) clearTimeout(pendingTimer);
    if (socket) {
      socket.emit('leave_session', { library_id: getLibraryId() });
      socket.disconnect();
      socket = null;
    }
    peers = [];
    latestVersion = 0;
    renderPeers();
    renderStatus('');
  }

  // ---- Remote action scheduling ----
  function scheduleRemoteAction(data) {
    if (pendingTimer) clearTimeout(pendingTimer);
    if (data.execute_at) {
      var delay = Math.max(0, (data.execute_at * 1000) - Date.now());
      pendingTimer = setTimeout(function () {
        applyRemoteAction(data);
      }, delay);
    } else {
      applyRemoteAction(data);
    }
  }

  function applyRemoteAction(data) {
    if (!player) return;
    applyingRemote = true;
    diagLog('remote_apply', data);

    if (data.track_id) {
      var currentTrack = trackStateFromRow ? trackStateFromRow(currentPlaybackRow && currentPlaybackRow()) : null;
      if (!currentTrack || currentTrack.id !== data.track_id) {
        var row = findRowByTrackId ? findRowByTrackId(data.track_id) : null;
        if (row && selectRow) selectRow(row, false);
      }
    }

    if (typeof data.position === 'number' && data.position >= 0 && player.src) {
      player.currentTime = data.position;
    }

    if (data.playing && player.paused && player.src) {
      player.play().then(function () {
        applyingRemote = false;
      }).catch(function () {
        applyingRemote = false;
      });
    } else if (!data.playing && !player.paused) {
      player.pause();
      applyingRemote = false;
    } else {
      applyingRemote = false;
    }
  }

  function applyJoinState(state, serverTime) {
    if (!player) return;
    var row = findRowByTrackId ? findRowByTrackId(state.track_id) : null;
    if (!row || !selectRow) return;
    applyingRemote = true;
    selectRow(row, false);
    var pos = state.position || 0;
    if (state.playing && state.server_time && serverTime) {
      pos += Math.max(0, serverTime - state.server_time);
    }
    if (pos > 0) player.currentTime = pos;
    if (state.playing) {
      player.play().then(function () {
        applyingRemote = false;
      }).catch(function () {
        applyingRemote = false;
      });
    } else {
      applyingRemote = false;
    }
    // Diagnostic: log join-state application
    diagLog('join_apply', { track_id: state.track_id, position: pos, playing: state.playing });
  }

  function isValidAction(data) {
    if (!data) return false;
    if (!data.track_id && data.action === 'play') return false;
    if (typeof data.position !== 'number' || data.position < 0 || data.position > 86400) return false;
    return true;
  }

  // ---- UI: Dialog + Runners ----
  var toggleListenTogether = function () {
    if (enabled) { showDialog(); return; }
    showDialog();
    enabled = true;
    connect();
  };
  window.__songwalkToggleSync = toggleListenTogether;
  window.__songwalkShowSyncDialog = toggleListenTogether;

  function showDialog() {
    var existing = document.getElementById('sync-modal');
    if (existing) { existing.showModal(); return; }

    var libId = getLibraryId();
    var joinUrl = window.location.origin + '/s/' + libId + '?sync=join';
    var qrUrl = 'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=' + encodeURIComponent(joinUrl);

    var modal = document.createElement('dialog');
    modal.id = 'sync-modal';
    modal.className = 'sync-modal';
    modal.innerHTML =
      '<div class="sync-modal-card">' +
        '<div class="sync-modal-head"><h2>Listen Together</h2><button class="frame-button sync-close-btn">&times;</button></div>' +
        '<div class="sync-qr-section"><p>Scan to join:</p><img src="' + qrUrl + '" alt="QR code" class="sync-qr-img" width="200" height="200"><p class="sync-qr-url">' + joinUrl + '</p><button class="frame-button sync-copy-btn">Copy link</button></div>' +
        '<div class="sync-listeners-row"><div class="sync-runners" id="sync-runners"></div></div>' +
        '<div class="sync-peers-section"><p class="sync-peers-count">Connecting...</p><ul class="sync-peers-list" id="sync-peers-list"></ul></div>' +
        '<div class="sync-status-section"><p class="sync-status-text" id="sync-status-text">Connecting...</p></div>' +
        '<div class="sync-modal-actions"><button class="frame-button danger sync-leave-btn">Leave Session</button></div>' +
      '</div>';
    document.body.appendChild(modal);

    modal.querySelector('.sync-close-btn').onclick = function () { modal.close(); };
    modal.querySelector('.sync-leave-btn').onclick = function () { disconnect(); enabled = false; modal.close(); modal.remove(); };
    modal.querySelector('.sync-copy-btn').onclick = function () { navigator.clipboard.writeText(joinUrl).then(function () { this.textContent = 'Copied!'; }.bind(this)); };
    modal.showModal();
  }

  function renderPeers() {
    var count = document.querySelector('.sync-peers-count');
    if (count) count.textContent = peers.length + ' other' + (peers.length !== 1 ? 's' : '') + ' listening';
    var list = document.getElementById('sync-peers-list');
    if (list) { list.innerHTML = ''; peers.forEach(function (p) { var li = document.createElement('li'); li.textContent = 'Listener'; list.appendChild(li); }); }
    updateRunners('sync-runners', peers.length);
    updateRunners('sync-runners-tb', peers.length);
    var widget = document.getElementById('sync-runners-widget');
    if (widget) widget.style.display = (peerId && peers.length > 0) ? 'flex' : 'none';
  }

  function renderStatus(msg) {
    var el = document.getElementById('sync-status-text');
    if (el) el.textContent = msg || (peerId ? 'Connected \u2014 ' + (peers.length + 1) + ' listening' : 'Connecting...');
  }

  function updateRunners(id, count) {
    var c = document.getElementById(id);
    if (!c) return;
    if (count === 0) { c.innerHTML = '<span class="sync-runner-none">Waiting...</span>'; return; }
    var img = '<img src="https://media.tenor.com/chfzEVhXQloAAAAj/animated-man-running.gif" class="sync-runner sync-runner-pulse" alt="listener">';
    c.innerHTML = img.repeat(count + 1);
  }

  // ---- Init ----
  if (window.location.search.indexOf('sync=join') !== -1) {
    toggleListenTogether();
  }

  // Listen to player events for sync broadcasting (instead of fighting app.js click handler)
  if (player) {
    player.addEventListener('play', function () {
      if (enabled && !applyingRemote) {
        diagLog('broadcast_play', {});
        broadcastAction('play');
      } else {
        diagLog('play_ignored', { enabled: enabled, applyingRemote: applyingRemote });
      }
    });
    player.addEventListener('pause', function () {
      if (enabled && !applyingRemote) {
        diagLog('broadcast_pause', {});
        broadcastAction('pause');
      } else {
        diagLog('pause_ignored', { enabled: enabled, applyingRemote: applyingRemote });
      }
    });
    player.addEventListener('seeked', function () {
      if (enabled && !applyingRemote) {
        diagLog('broadcast_seek', { position: player.currentTime });
        broadcastAction('seek', { position: player.currentTime, playing: !player.paused });
      } else {
        diagLog('seeked_ignored', { enabled: enabled, applyingRemote: applyingRemote });
      }
    });
  }
  if (nextButton) nextButton.addEventListener('click', userNext);
  if (prevButton) prevButton.addEventListener('click', userPrev);
  if (progressInput) {
    progressInput.addEventListener('change', function () {
      if (player && enabled && !applyingRemote) userSeek(player.currentTime);
    });
  }
})();
