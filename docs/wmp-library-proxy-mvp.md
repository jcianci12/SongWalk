# Windows Media Player Library Proxy MVP

This document outlines the work needed to expose a user's Windows Media Player Legacy library through SongWalk while keeping WMP as the source of truth.

The goal is not to scan music folders or copy files into SongWalk. The goal is to read the WMP library as WMP sees it, render that library in SongWalk, stream the local files over the existing SongWalk share flow, and write selected user edits back into WMP where the WMP API allows it.

## MVP Outcome

A Windows user can:

1. Run the SongWalk desktop app.
2. Open the owner dashboard.
3. Connect or sync their Windows Media Player library.
4. See a SongWalk library that mirrors WMP's tracks, albums, ratings, and basic metadata.
5. Open the public SongWalk link from a phone.
6. Play supported tracks remotely while the Windows PC is online.
7. Change supported metadata in SongWalk and have those changes written back to WMP.

## Source Of Truth

Use the Windows Media Player COM API via `WMPlayer.OCX`.

Do not parse WMP's internal `.wmdb` files for the MVP. The COM API gives us the user's library as WMP exposes it, including WMP-specific attributes like `UserRating`, `UserPlayCount`, and `SourceURL`.

The local probe on this development machine showed:

- `WMPlayer.OCX` is available.
- WMP library access rights are `full`.
- WMP reports roughly 8.7k library items.

That is enough to justify building the MVP around COM access.

## Proposed Architecture

Add a Windows-only WMP integration layer:

```text
songshare/wmp_library.py
```

Responsibilities:

- Run WMP COM calls in isolated PowerShell subprocesses so COM failures do not kill the SongWalk process.
- Detect whether WMP is available.
- Request media library access if needed.
- Read WMP library items.
- Normalize WMP attributes into SongWalk track records.
- Write supported fields back to WMP.
- Avoid exposing arbitrary filesystem paths to public clients.

SongWalk should then support two kinds of tracks:

- Uploaded/imported SongWalk tracks stored under `songshare-data/libraries/.../files`.
- WMP-backed linked tracks whose audio comes from the local file path reported by WMP.

## WMP Attributes To Read

Start with the fields that map cleanly to the current SongWalk UI:

| SongWalk field | WMP attribute |
| --- | --- |
| Title | `Title` |
| Artist | `Author`, fallback `DisplayArtist` |
| Album | `WM/AlbumTitle`, fallback album-related attributes |
| Album artist | `WM/AlbumArtist` |
| Genre | `WM/Genre` |
| Track number | `WM/TrackNumber` |
| Duration | `Duration` |
| File size | `FileSize` |
| Rating | `UserRating`, fallback `UserEffectiveRating` |
| Play count | `UserPlayCount` |
| Last played | `UserLastPlayedTime` |
| File path | `SourceURL` |
| Stable-ish identity | `TrackingID`, fallback `SourceURL` |
| Media type | `MediaType` |

Only import items where `MediaType` is audio and `SourceURL` resolves to a local file we are willing to stream.

## Data Model Changes

Extend `songshare.store.Track` with source fields:

```text
source_kind: "uploaded" | "wmp"
source_path: string
source_external_id: string
duration_seconds: float
genre: string
album_artist: string
play_count: int
last_played_at: string
```

For existing tracks, default `source_kind` to `uploaded`.

For WMP tracks:

- `stored_name` can be empty or a synthetic value.
- `source_path` stores the local path resolved from WMP `SourceURL`.
- `source_external_id` stores `TrackingID` when present, otherwise a stable normalized path key.
- `size` comes from the file path if available, otherwise WMP `FileSize`.

## Import And Sync Flow

Add an owner-only route:

```text
POST /owner/<token>/wmp/sync
GET  /owner/<token>/wmp/sync/jobs/<job_id>
```

The sync should run as a background job. WMP COM calls can be slow on large libraries, and this repo already has an import job pattern that can be reused.

Sync behavior:

1. Check the request is owner-authenticated and direct local access where appropriate.
2. Create or find a special SongWalk library named `Windows Media Player`.
3. Start a background WMP sync job.
4. Read WMP media items through COM.
5. Normalize each audio item.
6. Upsert tracks into the SongWalk library by `source_external_id`.
7. Commit records in small chunks so large WMP libraries do not wait for one giant payload.
8. Mark missing WMP items as unavailable after the final chunk.
9. Return progress to the owner dashboard.

Recommended MVP behavior for missing files:

- Keep the track in SongWalk.
- Mark it unavailable.
- Hide or disable playback.
- Do not delete automatically until we have more confidence in sync behavior.

## Streaming Flow

Update the existing stream route:

```text
GET /s/<library_id>/tracks/<track_id>/file
```

For uploaded tracks, keep the current behavior.

For WMP tracks:

1. Resolve `source_path` from the stored track.
2. Confirm the track belongs to the requested library.
3. Confirm the path exists and is a file.
4. Confirm the path is the same path imported from WMP, not request-supplied input.
5. Serve it with `send_file(..., conditional=True)`.

Browser support concern:

- MP3 and M4A are likely fine.
- WMA playback is not broadly supported by mobile browsers.
- For MVP, label unsupported files clearly or disable play for unsupported extensions.
- Later, add FFmpeg transcoding for `.wma` and other unsupported formats.

## Write-Back Flow

Use WMP COM `setItemInfo` where allowed.

Start with:

- Rating
- Title
- Artist
- Album

When a user edits a WMP-backed track in SongWalk:

1. Update the WMP media item through COM.
2. If WMP write-back succeeds, update the SongWalk mirror record.
3. If WMP write-back fails, return a clear error and do not pretend the edit is synced.

Important: WMP may treat some attributes as read-only depending on file type, DRM status, or library state. The UI should say `Could not save to Windows Media Player` rather than silently falling back.

## Security Rules

This feature exposes local files through a public tunnel, so keep the boundary tight:

- Only owner routes can trigger WMP sync.
- Public users cannot provide file paths.
- Public users can only stream track IDs already present in the library.
- WMP `SourceURL` should be normalized and stored at sync time.
- Do not add a generic "serve local path" endpoint.
- Consider a setting that requires owner confirmation before a WMP library is shared publicly.
- Owner dashboard should show a warning that the PC must stay online and the public link can play the mirrored WMP library.

## Dependencies

Use Windows PowerShell as the WMP COM host.

The first Python COM attempt proved too brittle because a bad COM load can terminate the Python interpreter before SongWalk can catch an exception. Running the WMP COM calls in a PowerShell subprocess keeps the desktop app alive even if WMP misbehaves.

Packaging changes:

- No extra Python dependency is required for the first MVP.
- The Windows desktop runtime assumes `powershell.exe` is available.
- Linux/macOS paths keep working because WMP sync reports unavailable outside Windows.

## UI Changes

Owner dashboard:

- Add `Windows Media Player Library` panel.
- Show WMP availability.
- Show current media access rights.
- Button: `Sync Windows Media Player`.
- Show sync progress.
- Show last sync time, track count, skipped count, and unsupported count.
- Link to open the mirrored WMP SongWalk library.

Library view:

- Add a small source badge for WMP-backed libraries or tracks.
- Disable playback for unsupported formats with a clear label.
- Keep the WMP look and album grouping behavior already in SongWalk.

## Implementation Phases

### Phase 1: Read-Only Probe

- Add `songshare/wmp_library.py`.
- Implement `is_available()`.
- Implement `get_access_rights()`.
- Implement `read_audio_items(limit=None)`.
- Add unit tests around normalization with fake WMP objects.
- Add a local manual command or route to report WMP availability and item count.

Acceptance:

- SongWalk can report whether WMP is available.
- SongWalk can count WMP audio tracks without exposing track names publicly.

### Phase 2: Mirror Library Sync

- Extend the `Track` model for WMP-backed tracks.
- Add store upsert support by external source ID.
- Add owner-only WMP sync route.
- Add background job progress.
- Create or reuse a `Windows Media Player` SongWalk library.
- Render mirrored tracks in the current library UI.

Acceptance:

- Clicking sync creates a SongWalk library that resembles the WMP audio library.
- Refreshing sync updates existing mirrored records rather than duplicating tracks.

### Phase 3: Playback

- Update `stream_track` to support WMP-backed source files.
- Add unsupported extension detection.
- Disable play controls for unsupported formats.
- Add tests for linked-file streaming and path safety.

Acceptance:

- A phone can open the SongWalk share URL and play supported WMP library tracks while the PC is online.

### Phase 4: Write-Back

- Implement WMP lookup by `TrackingID` or `SourceURL`.
- Implement write-back for rating.
- Then implement title, artist, and album.
- Update existing edit/rating endpoints to branch on `source_kind`.
- Add error handling for read-only WMP attributes.

Acceptance:

- Rating changes made in SongWalk appear in WMP after sync or refresh.
- Failed WMP writes show a clear error.

### Phase 5: Polish And Reliability

- Add last sync summary.
- Add skipped file report.
- Add WMA/transcoding decision.
- Add owner warning before public sharing.
- Add tray menu entry: `Sync Windows Media Player`.
- Add periodic optional sync, disabled by default.

## Test Plan

Automated tests:

- WMP item normalization maps expected attributes.
- WMP unavailable state does not break non-Windows runtime.
- WMP sync upserts by external ID.
- WMP sync does not duplicate tracks.
- WMP-backed streaming serves only stored source paths.
- Public clients cannot trigger sync.
- Unsupported formats render as unavailable.
- WMP write-back errors are surfaced.

Manual Windows tests:

- WMP not installed or unavailable.
- WMP access rights are `none`, `read`, and `full`.
- Large library sync with thousands of items.
- MP3 playback on phone over Quick Tunnel.
- WMA behavior on phone.
- Rating update from SongWalk appears in WMP.
- WMP library edit followed by SongWalk resync updates the mirror.

## Open Questions

- Should public share users be allowed to edit WMP metadata, or should write-back be owner-only?
- Should missing WMP files remain visible, become hidden, or be removed on sync?
- Should unsupported formats be hidden or shown as unavailable?
- Do we need playlist support in the MVP, or is album/track library view enough?
- Should SongWalk mirror WMP auto-playlists later?
- Should the WMP mirror library have a stable share URL across syncs?

## Recommended MVP Scope

Build this first:

- Owner-only WMP availability panel.
- Manual WMP sync.
- Mirrored `Windows Media Player` library.
- Read-only metadata mirror.
- Playback for browser-supported local audio files.
- Rating write-back only.

Defer this:

- Full metadata write-back.
- WMA transcoding.
- WMP playlists and auto-playlists.
- Automatic periodic sync.
- Raw `.wmdb` inspection.
