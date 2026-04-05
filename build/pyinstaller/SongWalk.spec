# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


ROOT = Path(SPECPATH).resolve().parents[1]
PACKAGE_DIR = ROOT / "songshare"


def collect_package_data(package_dir: Path, relative_dirs: list[str]) -> list[tuple[str, str]]:
    datas: list[tuple[str, str]] = []
    for relative_dir in relative_dirs:
        source_root = package_dir / relative_dir
        if not source_root.exists():
            continue
        for path in source_root.rglob("*"):
            if path.is_file():
                target_dir = f"songshare/{relative_dir}/{path.relative_to(source_root).parent.as_posix()}"
                if target_dir.endswith("/."):
                    target_dir = target_dir[:-2]
                datas.append((str(path), target_dir))
    return datas


datas = collect_package_data(PACKAGE_DIR, ["templates", "static", "images"])

a = Analysis(
    [str(Path(SPECPATH).resolve() / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SongWalk",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="SongWalk",
)
