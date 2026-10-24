# -*- mode: python ; coding: utf-8 -*-
"""Empaqueta classroom-dl como un único .exe de consola para Windows."""

import os

from PyInstaller.utils.hooks import collect_all

spec_dir = os.path.abspath(SPECPATH)
repo_dir = os.path.abspath(os.path.join(spec_dir, ".."))
entrypoint = os.path.join(spec_dir, "entrypoint.py")

datas = []
binaries = []
hiddenimports = []

for package in (
    "googleapiclient",
    "google.auth",
    "google.oauth2",
    "google_auth_httplib2",
    "google_auth_oauthlib",
    "requests_oauthlib",
    "httplib2",
    "oauthlib",
    "requests",
    "urllib3",
    "certifi",
    "charset_normalizer",
    "idna",
    "uritemplate",
    "questionary",
    "prompt_toolkit",
    "rich",
    "typer",
    "click",
    "platformdirs",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

a = Analysis(
    [entrypoint],
    pathex=[repo_dir],
    binaries=binaries,
    datas=datas,
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
    a.binaries,
    a.datas,
    [],
    name="classroom-dl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
