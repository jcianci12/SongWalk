# Desktop Packaging

SongWalk can be packaged for simple local desktop use with PyInstaller. The build is Windows-first and keeps the app runtime unchanged.

## Windows

Use the PowerShell build script:

```powershell
.\build\pyinstaller\build-windows.ps1
```

The script:

- Creates or reuses `.venv`
- Installs the runtime requirements plus `PyInstaller`
- Builds an onedir Windows tray app from `build/pyinstaller/launcher.py`
- Bundles `templates`, `static`, and `images` into the app folder
- Downloads the official 64-bit `cloudflared.exe` into the app folder so Quick Tunnel works from the packaged runtime

Output lands in:

```text
build/pyinstaller/dist/windows/SongWalk/SongWalk.exe
```

Run the executable from that folder. The packaged app:

- starts the local SongWalk server in the background
- enables Quick Tunnel by default in the packaged desktop runtime unless you explicitly set `SONGSHARE_QUICK_TUNNEL_ENABLED=0`
- waits for `http://localhost:8080/healthz` to answer before showing the tray icon
- sits in the Windows notification area
- opens the owner dashboard on startup, preferring the public tunnel URL when it is ready
- opens the owner dashboard when you double-click the tray icon, again preferring the public tunnel URL over localhost
- exposes `Open owner dashboard`, `Open SongWalk`, `Open data folder`, and `Quit SongWalk` from the tray menu
- can bring Cloudflare Quick Tunnel online without a separate machine-wide `cloudflared` install

For the packaged app, the default data directory is `songshare-data/` next to `SongWalk.exe`, which keeps the distribution portable when you move the whole folder together. Set `SONGSHARE_DATA_DIR` only if you want a fixed external location.

## macOS

The repo includes a matching shell script:

```bash
./build/pyinstaller/build-macos.sh
```

Run it on macOS, not on Windows. PyInstaller does not cross-build a native macOS app bundle from this environment in a reliable way. The script uses the same spec file and produces:

```text
build/pyinstaller/dist/macos/SongWalk/SongWalk
```

## Notes

- The Windows build is windowless. Startup failures surface through a Windows error dialog instead of a console window.
- If you want a fixed data location, set `SONGSHARE_DATA_DIR` before launching the packaged app.
- The packaging path does not change the server code, database layout, or runtime flags.
