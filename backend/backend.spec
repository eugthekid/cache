# -*- mode: python ; coding: utf-8 -*-
"""
backend.spec
------------
Freezes run_backend.py into a standalone executable Electron's main
process spawns directly -- no Python install, no venv, no terminal
required on the end user's machine.

Two bundling details that aren't optional, both because of how Alembic
actually works at runtime (see run_backend.py's docstring for why
migrations have to run automatically at all):

- alembic.ini and alembic/ are added as DATA, not left to PyInstaller's
  normal import-following. Alembic doesn't `import` migration files the
  way regular code does -- it reads them off disk by path and execs them
  at runtime, so PyInstaller's static analysis (which only follows real
  import statements) never sees them as dependencies unless they're
  listed explicitly.
- uvicorn picks its event loop and protocol implementations dynamically
  at runtime (uvloop if installed, h11 for HTTP, etc.) rather than through
  static imports PyInstaller's analyzer can trace -- hence the explicit
  hiddenimports below. Missing one fails at first REQUEST, not at
  startup, which is a much worse place to discover it.
"""

from PyInstaller.utils.hooks import collect_submodules

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("alembic")
    + collect_submodules("app")
    + [
        "multipart",
        "openpyxl",
    ]
)

a = Analysis(
    ["run_backend.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("alembic.ini", "."),
        ("alembic", "alembic"),
    ],
    hiddenimports=hiddenimports,
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
    name="cache-backend",
    debug=False,
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
    name="cache-backend",
)
