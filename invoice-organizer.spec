# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.config import CONF
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)


project_root = Path(SPECPATH)
dist_root = project_root.parent / "dist"
CONF["distpath"] = str(dist_root)
app_version = (project_root / "VERSION").read_text(encoding="utf-8").strip()
version_parts = app_version.split(".")
if len(version_parts) != 3 or not all(part.isdigit() for part in version_parts):
    raise ValueError("VERSION must contain a numeric MAJOR.MINOR.PATCH version.")
version_tuple = tuple(int(part) for part in version_parts) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=version_tuple,
        prodvers=version_tuple,
        mask=0x3F,
        flags=0x0,
        OS=0x40004,
        fileType=0x1,
        subtype=0x0,
        date=(0, 0),
    ),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "080404B0",
                    [
                        StringStruct("CompanyName", "nobody"),
                        StringStruct("FileDescription", "Invoice Organizer"),
                        StringStruct("FileVersion", app_version),
                        StringStruct("InternalName", "InvoiceOrganizer"),
                        StringStruct("OriginalFilename", "InvoiceOrganizer.exe"),
                        StringStruct("ProductName", "Invoice Organizer"),
                        StringStruct("ProductVersion", app_version),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [2052, 1200])]),
    ],
)
webview_datas, webview_binaries, webview_hiddenimports = collect_all("webview")

datas = webview_datas + [
    (str(project_root / "VERSION"), "."),
    (str(project_root / "app" / "templates"), "app/templates"),
    (str(project_root / "app" / "static"), "app/static"),
]
hiddenimports = webview_hiddenimports + [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]

a = Analysis(
    [str(project_root / "desktop.py")],
    pathex=[str(project_root)],
    binaries=webview_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="发票整理工具",
    icon=str(project_root / "assets" / "invoice-organizer.ico"),
    version=version_info,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="发票整理工具",
)
