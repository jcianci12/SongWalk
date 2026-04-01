# Nice To Have Features

## Legacy WMP Visualization Import Investigation

Explore whether a legacy Windows Media Player visualization can be inspected and partially recreated for the web UI.

Key constraint:
- A generic `.vis` reader/converter is only realistic if the source file is declarative data.
- If the source is a native WMP plug-in binary (for example a DLL/COM visualization), the animation logic is compiled code, so this becomes reverse engineering and manual reimplementation rather than straightforward import.

Practical approach:
1. Obtain one specific legacy visualization file/plugin as a sample.
2. Identify whether it is a data format or a native binary.
3. If it is data, document the structure and map it into a Songshare-native preset schema.
4. If it is native code, extract only portable assets/metadata where possible and manually recreate the effect on canvas/WebGL.
5. Prefer a Songshare-native WMP-inspired preset format over literal compatibility.

## Upload-Time Embedded Metadata And Art Expansion

Extend upload-time metadata extraction beyond MP3 so Songshare can pull album/title/artist data and embedded cover art from more formats during ingest.

Scope:
1. Add support for `m4a` embedded metadata and cover art extraction at upload time.
2. Add support for `ogg` / `opus` metadata extraction at upload time.
3. Investigate embedded art extraction for `ogg` / `opus`, which is less uniform than MP3 or `m4a`.
4. Decide whether literal `.mp4` files should be accepted, since current upload support is oriented around audio formats and already includes `.m4a` rather than generic `.mp4`.

Notes:
- Upload-time reading is much easier than edit-time writing.
- Current metadata writing is MP3/ID3-focused, so non-MP3 write-back would be a separate task.
