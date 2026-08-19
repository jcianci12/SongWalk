# SongWalk Tech Debt Cleanup Plan

> Generated 2026-07-16 from full codebase audit.
> **Last updated: 2026-07-16** — Critical tier (C1-C5) completed.
> Priorities: 🔴 Critical → 🟠 High → 🟡 Medium → 🟢 Low

---

## 🔴 CRITICAL — Security & Data Integrity

### C1. Secrets not gitignored (risk: accidental commit)

- `magic-link-secret.txt` — untracked, NOT in `.gitignore`. Accidental `git add .` commits it.
- `owner-token.txt` — same problem.
- `songwalk-data/` — runtime data dir visible in `git status`, could leak library data.

**Action:** Add to `.gitignore`:
```
magic-link-secret.txt
owner-token.txt
songwalk-data/
```
**Effort:** 1 minute. **Risk of inaction:** credential leak to public repo.

### C2. Python wheels tracked in git (risk: repo bloat)

Two `.whl` files in `build/pyinstaller/vendor/`:
- `pillow-12.2.0-cp313-cp313-win_amd64.whl` (1.57 MB)
- `pystray-0.19.5-py2.py3-none-any.whl`

Binaries stored in git. The build script (`build-windows.ps1`) should install these from PyPI, not vendor them.

**Action:**
1. Add `*.whl` to `.gitignore`
2. `git rm --cached` both wheel files
3. Update `build-windows.ps1` to `pip install pillow pystray` instead of using vendored wheels
4. Keep `cloudflared-windows-amd64.exe` vendored (already gitignored, special binary)

**Effort:** 15 min. **Risk:** bloated repo, merge conflicts on binary diffs.

### C3. Compose prod missing health check (risk: silent failures)

No health check in any compose file. If Flask crashes but container stays up, Drone CI deploys and declares success with a dead service.

**Action:** Add to `compose.prod.yaml`:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8080/healthz"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s
```
**Effort:** 5 min.

### C4. Compose prod missing resource limits (risk: OOM kills host)

No `mem_limit` or `cpus` on the production container. yt-dlp or spotdl imports can spike RAM arbitrarily.

**Action:** Add conservative limits to `compose.prod.yaml`:
```yaml
deploy:
  resources:
    limits:
      memory: 2G
      cpus: '2'
```
**Effort:** 2 min.

### C5. `eventlet` officially deprecated by maintainers (risk: unmaintained dependency)

Research completed 2026-07-16:
- **eventlet 0.41.1** released 2026-07-15. PyPI warns: *"Heavily discouraged. Retirement planned. Migrate to asyncio."* Maintenance-only (bug fixes), no new features.
- **gevent 26.5.0** released 2026-05-21. Actively maintained, no deprecation notice.
- SongWalk uses `socketio.run()` in `__main__.py` which auto-selects eventlet as WSGI server when installed. Socket.IO `async_mode` is `"threading"` (not eventlet green threads).
- Desktop build uses waitress directly — no eventlet needed there.

**Action (done):** Bumped pin to `eventlet>=0.41.1,<1` (from `>=0.39,<1`). Latest patches applied.
**Action (future):** Migrate to gevent or drop eventlet and use waitress for Docker entry point too. Gevent is the mature replacement path. Estimated 2-3h migration + testing.
**Effort:** 15 min (bump done). 3h (full migration to gevent).

> ✅ **DONE** — eventlet bumped to 0.41.1. Migration ticket filed for Sprint 5+.

---

## 🟠 HIGH — Architecture & Maintainability

### H1. Monolithic `__init__.py` (1,660 lines)

`create_app()` contains all route handlers, helper functions, app setup, and config — all in one file. This was fine for MVP but is now a maintenance bottleneck:
- ~60 inner functions
- ~40 route handlers
- No separation of concerns
- Hard to test in isolation

**Action:** Split into Flask blueprints:
```
songwalk/
├── __init__.py          # create_app() factory only (~50 lines)
├── config.py            # all env var reading, defaults
├── routes/
│   ├── library.py       # /s/<id>/... routes
│   ├── owner.py         # /owner/<token>, /libraries routes
│   ├── auth.py          # magic link, cookie endpoints
│   ├── quick_tunnel.py  # tunnel endpoints
│   ├── health.py        # /healthz
│   └── errors.py        # error handlers
└── services/
    ├── import_service.py  # import job dispatch (from __init__.py)
    └── track_helpers.py   # build_track_view, archive_track_path, etc.
```

**Effort:** 6-8h. High risk of regressions — need full test suite pass. **Best done incrementally** (one blueprint per PR).

### H2. Duplicate import job systems

Two parallel, incompatible job managers:
- `songwalk/__init__.py`: `ImportJob` dataclass + `ImportJobStore` (used by web routes)
- `songwalk/import_jobs.py`: `ImportJob` dataclass + `ImportJobManager` (different fields, different API)

Same purpose, different field names (`status` vs `state`, `percent` vs `progress_percent`).

**Action:** Delete `songwalk/import_jobs.py` and refactor any callers to use the `__init__.py` version. Or pick whichever is better and migrate everything to it.
**Effort:** 2h.

### H3. Monolithic `app.js` (3,549 lines)

All frontend logic in one IIFE: UI rendering, event handling, API calls, drag-and-drop, search, filtering, playback, import, uploads, star ratings, reordering, collections. No modules, no components, no build step.

**Action:** Phase plan:
1. **Short-term:** Add `"use strict"`, split into ES modules with a simple bundler-less approach (multiple `<script type="module">` tags)
2. **Medium-term:** Extract clear subsystems:
   - `player.js` — audio playback, transport controls
   - `library-ui.js` — track list rendering, search, filter
   - `dragdrop.js` — drag-and-drop logic
   - `import.js` — upload, YouTube, Spotify import UI
   - `api.js` — fetch wrappers
   - `collections.js` — collection management UI
3. **Long-term:** Add build step (esbuild, Vite) for minification + cache busting. Replace `SCRIPT_VERSION = "2026-04-22-album-drag-drop-1"` with content-hash filenames.

**Effort:** 12-16h total across multiple PRs.

### H4. No database — JSON file store with thread lock

Current design uses `Store` class with `threading.Lock()` and JSON files on disk. Works for single-user but breaks at:
- Concurrent library access
- Atomic multi-track operations
- Data migration/versioning
- Eventually: search across libraries

**Question for later:** Does this need a real DB or is JSON fine for the use case (personal/shared music dropbox, not multi-tenant SaaS)?

**Action:** Decide architectural direction. If staying file-based, add atomic write pattern (write to temp file + rename) and document scalability limits explicitly.
**Effort:** Decision: 1h discussion. Implementation: varies.

### H5. Race condition in sync room management

`songwalk/sync.py` module-level `_room_peers` dict modified from socket event handlers without explicit locks. SocketIO async_mode is `"threading"` — concurrent events can corrupt the dict.

**Action:** Add `threading.Lock()` around `_room_peers` mutations. Or switch to `queue.Queue` based message passing.
**Effort:** 1h.

### H6. `_cookie_upload_tokens` dict accessed without locks

`songwalk/__init__.py` line 1684: `_cookie_upload_tokens` dict has a pruning function (`_prune_expired_cookie_tokens`) that runs without any lock while other routes read/write the dict.

**Action:** Add `threading.Lock()` around all `_cookie_upload_tokens` access.
**Effort:** 15 min.

### H7. `desktop.py` crashes on non-Windows at import time

Line 337: `ctypes.windll.user32.MessageBoxW(...)` — Windows-only. Importing `desktop.py` on Linux/macOS raises `AttributeError`.

**Action:** Move Windows-specific code behind a platform guard:
```python
if sys.platform == "win32":
    import ctypes
    ctypes.windll.user32.MessageBoxW(...)
```
**Effort:** 10 min.

---

## 🟡 MEDIUM — Code Quality & Consistency

### M1. Production debug logging enabled

`songwalk/static/app.js` line 4: `const DEBUG_FILTERING = true;` — debug logging unconditionally on.

**Action:** Gate behind a check like `const DEBUG_FILTERING = location.hostname === 'localhost';` or read from a meta tag set by the Flask template.
**Effort:** 5 min.

### M2. Print statements in production

| File | Line | Issue |
|------|------|-------|
| `quick_tunnel.py` | 204 | `print(f"SongWalk public URL: {public_url}")` |
| `runtime.py` | 95-96 | `print(...)` for URLs |

These are startup banners but should use `app.logger.info()` or be behind a verbosity flag.

**Action:** Replace `print()` with proper logging. Use `app.logger.info()`.
**Effort:** 10 min.

### M3. Bare `except Exception` swallowing errors silently

7 occurrences across `audio_tags.py`, `desktop.py`, `email_service.py`. SMTP failures return `False` with zero logging. MP3 tag read failures silently return `{}`.

**Action:** At minimum, log the exception. Prefer catching specific exception types (`IOError`, `OSError`, `mutagen.MutagenError`).
**Effort:** 1h.

### M4. `broadcast_library_change()` swallows errors silently

`songwalk/sync.py` lines 177-182: catches `RuntimeError` and `AttributeError` with bare `pass`. If broadcasts are failing, nobody knows.

**Action:** Log the exception at `warning` level.
**Effort:** 2 min.

### M5. Missing type hints on ~80% of functions

Most public functions lack type annotations. Worst offenders: `store.py`, `__init__.py` inner functions, `importer.py`, `desktop.py`.

**Action:** Add `from __future__ import annotations` to all modules. Incrementally annotate function signatures. Start with public API surfaces (Store, ImportService, route helpers).
**Effort:** 4-6h spread across sprints.

### M6. No docstrings on public classes

Every major class lacks a docstring: `Store`, `ImportJob`, `ImportJobStore`, `LibraryImportService`, `MusicMetadataClient`, `QuickTunnelManager`, `MagicLinkStore`, `SongWalkDesktopApp`, `DevChangeMonitor`.

**Action:** Add one-line docstrings to each class describing its purpose.
**Effort:** 30 min.

### M7. Inconsistent naming: `ImportJobStore` vs `ImportJobManager`

Two classes with identical purpose have different suffixes. No consistent naming convention for "managers" vs "stores" vs "services".

**Action:** Standardize: "Store" for persistence, "Service" for business logic, "Manager" for lifecycle/process management. Rename accordingly.
**Effort:** 30 min (after H2 is resolved, since one gets deleted).

### M8. Hardcoded magic numbers

| Location | Value | Should be |
|----------|-------|-----------|
| `import_jobs.py:42` | `retention_seconds=3600` | Config constant or env var |
| `import_jobs.py:42` | `max_logs=12` | Config constant |
| `__init__.py:81` | `ttl_seconds=3600` | Config constant |
| `desktop.py:261` | `timeout_seconds=20.0` | Config constant |
| `importer.py:76` | `timeout=1800` (30 min) | Config constant |
| `importer.py:160` | `default limit=6` | Config constant |
| `store.py:185` | `retry range(5)` | Config constant |

**Action:** Extract to module-level constants or `config.py`. Prefix with `_` for private constants.
**Effort:** 30 min.

### M9. Hardcoded external URLs

MusicBrainz API root, Cover Art Archive root, Spotify API endpoints, YouTube URL template, QR code service, animated GIF — all hardcoded in source. If any service changes URL, code breaks without recompile.

**Action:** Move to module-level constants. Add comments noting service documentation URLs.
**Effort:** 15 min.

---

## 🟢 LOW — Polish & Future-Proofing

### L1. Stale branches to delete

- `explore/wmp-legacy-backend` — last commit April 2026, unmerged, abandoned experiment.
- `listen-together` — 2 days old but its work appears merged into main. Verify then delete.

**Action:** `git branch -d explore/wmp-legacy-backend` and confirm no unique work. Verify `listen-together` diff vs main, then delete.
**Effort:** 5 min.

### L2. `songwalk-data/` and `.import-work/` not gitignored

Both appear in `git status` noise. Not critical but clutters workspace.

**Action:** Add to `.gitignore`.
**Effort:** 1 min.

### L3. `build/pyinstaller-live*/` gitignored but `-live-2` variant may not match

Pattern `build/pyinstaller-live*/` should catch all variants. Verify no edge case.

**Action:** Review and add explicit pattern if needed.
**Effort:** 2 min.

### L4. No `SONGWALK_SECRET_KEY` defined in compose envs

Flask uses `os.urandom(24)` as fallback (check `__init__.py`). This means every container restart generates a new secret key, invalidating all existing sessions.

**Action:** Generate a persistent secret key and pass it via compose env or Docker secret.
**Effort:** 5 min.

### L5. `.drone.yml` hardcodes network name with wrong case

Line references `SONGWALK_default` (uppercase SONGWALK) but Docker Compose creates `songwalk_default` (lowercase). If this works, it means the network was manually pre-created with the uppercase name — brittle.

**Action:** Fix to lowercase `songwalk_default` or use Compose project name consistently.
**Effort:** 5 min.

### L6. No test dependencies declared

No `requirements-dev.txt`, no `pytest` in requirements.txt. Tests run via whatever is in the dev venv. CI doesn't run tests at all.

**Action:** Create `requirements-dev.txt` with `pytest`, `pytest-cov`, `coverage`. Add test step to `.drone.yml` for `main` branch pushes.
**Effort:** 30 min.

### L7. No test files for 5 source modules

| Module | Missing test |
|--------|-------------|
| `email_service.py` | No `test_email_service.py` |
| `magic_link.py` | No `test_magic_link.py` |
| `import_jobs.py` | No `test_import_jobs.py` |
| `audio_tags.py` | No `test_audio_tags.py` |
| `__main__.py` | No direct test |

**Action:** Add unit tests for `magic_link.py` and `audio_tags.py` first (pure logic, no network). `email_service.py` needs SMTP mock. `__main__.py` is trivial glue — low priority.
**Effort:** 3-4h for all five.

### L8. `test_store.py` only 100 lines for 709-line module

Extremely thin coverage for the data layer. No edge cases tested: concurrent access, file corruption recovery, disk-full scenarios.

**Action:** Expand test coverage. Add tests for: concurrent lock behavior, malformed JSON recovery, missing file handling, disk error simulation.
**Effort:** 2-3h.

### L9. `werkzeug.utils.secure_filename` deprecated in Werkzeug 3.x

Two usages (`__init__.py` line 26, `store.py` line 16). Still works but may be removed in future major version.

**Action:** Replace with equivalent manual sanitization or use `werkzeug.utils.safe_join` where applicable.
**Effort:** 10 min research + 15 min implementation.

### L10. `urllib` instead of `requests`

`album_lookup.py` and `quick_tunnel.py` use raw `urllib.request` instead of the `requests` library. `requests` is not in `requirements.txt` — likely intentional to avoid dependency. Acceptable if deliberate, but `requests` handles redirects, timeouts, and error handling better.

**Action:** Decide: add `requests` to deps and refactor, or document intentional urllib-only policy.
**Effort:** Decision: 5 min. Refactor: 1h.

### L11. `sync.js` uses `var` almost exclusively

`var` is function-scoped and hoisted, leading to subtle bugs. `let` and `const` are universally available.

**Action:** Replace `var` with `let`/`const` throughout `sync.js` and any remaining `var` in `app.js`.
**Effort:** 20 min.

### L12. No minification or cache busting for static assets

`app.js` (3,549 lines, unminified), `site.css` (3,028 lines, unminified), `sync.js` (329 lines) all served raw. Version string manually bumped in `app.js`.

**Action:** Add esbuild-based minification step. Use content hashes in filenames for cache busting. Wire into Drone CI build step.
**Effort:** 2h.

### L13. `Songwalk logo.png` is 1.55 MB

Large for a web asset. Should be ~100-200KB for web.

**Action:** Optimize with `pngquant` or convert to WebP. Keep original in `docs/` or an `assets-src/` directory.
**Effort:** 10 min.

### L14. `media player legacy example.png` in repo root

Documentation screenshot cluttering root directory.

**Action:** Move to `docs/`.
**Effort:** 1 min.

### L15. UUID-named directories at repo root

Six directories like `529aa120-aee7-4214-a14a-5744362e69cd/` at repo root. Gitignored by `/*-*-*-*-*/` but still on disk. Legacy data from early development.

**Action:** Delete if confirmed unused. They appear to be old songwalk-data instances.
**Effort:** 2 min verification + deletion.

### L16. `songshare-*` log files and `songshare-data/`

Leftover from a renamed project ("songshare" → "songwalk"). `songshare-data/` is gitignored, log files caught by `*.log`.

**Action:** Delete remaining `songshare-*.log` files from disk if not needed. No code changes needed (already gitignored).
**Effort:** 1 min.

---

## 📋 Summary: Recommended Sprint Order

### Sprint 1 (Security & Stability) — ~2h ✅ DONE (C1-C5)
1. ~~C1: gitignore secrets + data dir~~ ✅
2. ~~C2: Remove wheels from git~~ ✅
3. ~~C3: Add health check to prod compose~~ ✅
4. ~~C4: Add resource limits to prod compose~~ ✅
5. ~~C5: Bump eventlet to 0.41.1~~ ✅
6. L1: Delete stale branches
7. L4: Persistent secret key

### Sprint 2 (Bug Fixes & Thread Safety) — ~3h
8. H5: Lock sync room dict
9. H6: Lock cookie upload tokens
10. H7: Platform guard for desktop.py
11. M3: Fix bare except clauses
12. M4: Log sync broadcast failures
13. M2: Replace print() with logger
14. M1: Gate DEBUG_FILTERING

### Sprint 3 (Duplicate Elimination) — ~3h
15. H2: Delete duplicate import job system
16. M7: Standardize naming convention
17. M8: Extract magic numbers to constants
18. M9: Extract hardcoded URLs to constants

### Sprint 4 (Architecture — Incremental) — ~10h
19. H1: Start splitting __init__.py into blueprints (one per PR)
20. H3: Start splitting app.js into modules (one subsystem per PR)
21. M5: Begin type hint annotation
22. M6: Add class docstrings

### Sprint 5 (Testing & CI) — ~6h
23. L6: Create requirements-dev.txt + CI test step
24. L7: Add tests for untested modules
25. L8: Expand store test coverage

### Backlog (Polish)
26. L3, L5, L9-L16: Various low-priority cleanup items

---

## ✅ Quick Wins — COMPLETED (2026-07-16)

All 5 critical items fixed:

| # | Item | Status |
|---|------|--------|
| C1 | Gitignore secrets (`magic-link-secret.txt`, `owner-token.txt`, `songwalk-data/`, `.import-work/`, `*.whl`) | ✅ Done |
| C2 | Remove wheels from git (`git rm --cached` both `.whl` files) | ✅ Done |
| C3 | Health check added to `compose.prod.yaml` (30s interval, /healthz) | ✅ Done |
| C4 | Resource limits added to `compose.prod.yaml` (2G memory, 2 CPUs) | ✅ Done |
| C5 | Eventlet bumped to `>=0.41.1` (latest). Full migration to gevent tracked for future sprint. | ✅ Done |

**Changes to commit:**
- `.gitignore` — added 5 patterns
- `compose.prod.yaml` — added healthcheck + deploy limits
- `requirements.txt` — eventlet `>=0.39` → `>=0.41.1`
- `build/pyinstaller/vendor/*.whl` — untracked from git
