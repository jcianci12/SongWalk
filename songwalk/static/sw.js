const CACHE_NAME = 'songwalk-v2';
const STATIC_ASSETS = [
  '/',
  '/static/site.css',
  '/static/app.js',
  '/static/favicon.svg',
  '/static/icons/icon.svg',
  '/static/offline.html'
];

// Install: pre-cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS).catch((err) => {
        console.warn('[SW] Pre-cache partial failure:', err);
      });
    }).then(() => self.skipWaiting())
  );
});

// Activate: clean old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }).then(() => self.clients.claim())
  );
});

// ---- Message handler: cache audio files on demand ----
self.addEventListener('message', (event) => {
  if (event.data && event.data.action === 'cache-tracks') {
    const tracks = event.data.tracks || [];
    cacheTracks(tracks).then((results) => {
      if (event.ports && event.ports[0]) {
        event.ports[0].postMessage({ done: true, cached: results.filter(Boolean).length, total: tracks.length });
      }
    });
  }
});

async function cacheTracks(tracks) {
  const cache = await caches.open(CACHE_NAME);
  const results = [];
  for (const track of tracks) {
    try {
      // Fetch the FULL file (no Range header — we want 200, not 206)
      const response = await fetch(track.url, {
        headers: { 'Range': '' }  // empty Range = no range request, get full file
      });
      if (response.ok) {
        await cache.put(track.url, response);
        results.push(true);
        // Send progress to all clients
        const clients = await self.clients.matchAll();
        clients.forEach(client => {
          client.postMessage({
            action: 'cache-progress',
            cached: results.filter(Boolean).length,
            total: tracks.length,
            trackId: track.id
          });
        });
      } else {
        results.push(false);
      }
    } catch (err) {
      console.warn('[SW] Failed to cache track:', track.id, err);
      results.push(false);
    }
  }
  return results;
}

// ---- Fetch: serve cached files, handle Range requests for audio ----
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  if (event.request.method !== 'GET') return;
  if (!url.protocol.startsWith('http')) return;

  // Static assets: cache-first
  if (url.pathname.startsWith('/static/') || url.pathname.startsWith('/offline')) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        return cached || fetch(event.request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // Audio files: serve from cache with Range support
  if (url.pathname.includes('/files/') || url.pathname.includes('/stream')) {
    event.respondWith(serveAudioWithRange(event.request));
    return;
  }

  // Navigation: network-first, fallback to cache
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).then((response) => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return response;
      }).catch(() => {
        return caches.match(event.request).then((cached) => {
          return cached || caches.match('/static/offline.html');
        });
      })
    );
    return;
  }

  // Everything else: network with cache fallback
  event.respondWith(
    fetch(event.request).catch(() => caches.match(event.request))
  );
});

// ---- Range request support for cached audio ----
async function serveAudioWithRange(request) {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(request.url, { ignoreSearch: true });

  if (!cached) {
    // Not cached — pass through to network
    return fetch(request);
  }

  const rangeHeader = request.headers.get('range');
  if (!rangeHeader) {
    // No Range header — serve full cached response
    return cached;
  }

  // Parse Range header
  const blob = await cached.blob();
  const total = blob.size;
  const match = rangeHeader.match(/bytes=(\d+)-(\d*)/);
  if (!match) return cached;

  const start = parseInt(match[1], 10);
  const end = match[2] ? parseInt(match[2], 10) : Math.min(start + 1024 * 1024, total - 1);

  if (start >= total) {
    return new Response('', { status: 416, headers: { 'Content-Range': `bytes */${total}` } });
  }

  const sliced = blob.slice(start, end + 1);
  return new Response(sliced, {
    status: 206,
    statusText: 'Partial Content',
    headers: {
      'Content-Range': `bytes ${start}-${end}/${total}`,
      'Accept-Ranges': 'bytes',
      'Content-Length': String(sliced.size),
      'Content-Type': cached.headers.get('Content-Type') || 'audio/mpeg',
    }
  });
}
