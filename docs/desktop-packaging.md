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
- Builds an onedir distribution from `songshare/__main__.py`
- Bundles `templates`, `static`, and `images` into the app folder

Output lands in:

```text
build/pyinstaller/dist/windows/SongWalk/SongWalk.exe
```

Run the executable from that folder. The app still writes its data to `songshare-data/` relative to the working directory unless `SONGSHARE_DATA_DIR` is set.

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

- The build keeps the console enabled so the owner URL and startup errors stay visible.
- If you want a fixed data location, set `SONGSHARE_DATA_DIR` before launching the packaged app.
- The packaging path does not change the server code, database layout, or runtime flags.
