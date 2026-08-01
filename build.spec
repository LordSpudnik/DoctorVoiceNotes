# build.spec
# ==========
# PyInstaller build specification for Doctor Voice Notes (Phase 7).
#
# WHY ONEDIR, NOT ONEFILE
# --------------------------
# An earlier version of this spec used onefile mode (single .exe, self-
# extracts to a temp folder on every launch). Two problems with that,
# found during sandbox testing:
#
#   1. Self-extraction of this app's ~140MB of bundled ML libraries took
#      roughly 10 seconds on every single launch, on a modern test
#      machine - a direct violation of PRD FR-01 ("opens within five
#      seconds"). Onedir mode has no extraction step: the .exe reads its
#      dependencies directly from the folder next to it, every time.
#   2. A hard crash (segmentation fault, not a catchable Python
#      exception) was reproduced when importing faster-whisper inside a
#      frozen onefile build in the Linux test sandbox, isolated via
#      bisection to something in how PyInstaller's onefile mode packages
#      ctranslate2's compiled binaries together with tokenizers'. Onedir
#      mode was tested against the same import and did NOT reproduce a
#      resolvable variant of this - see the "KNOWN OPEN RISK" note below
#      for what is and is not confirmed.
#
# The tradeoff: onedir produces a FOLDER (DoctorVoiceNotes.exe plus a
# _internal subfolder), not a single portable .exe file. installer.iss
# packages the whole folder, so this is invisible to the doctor - they
# still only ever see one DoctorVoiceNotes.exe shortcut.
#
# WHY A .spec FILE INSTEAD OF A ONE-LINE `pyinstaller main.py` COMMAND
# ----------------------------------------------------------------------
# Two dependencies in this project need help that a plain command-line
# call cannot express:
#
#   1. customtkinter ships its own theme JSON files and font files inside
#      its package folder. PyInstaller's automatic import scanner only
#      follows Python imports - it does not know to copy non-Python data
#      files sitting inside a package. Without collecting them explicitly,
#      the packaged .exe launches, then crashes the instant it tries to
#      build the first CTk widget, with an error about a missing theme
#      file. This is the exact risk flagged in the Phase 6 handoff notes.
#      CONFIRMED FIXED in sandbox testing: a minimal customtkinter-only
#      frozen build launched and ran its mainloop cleanly with this fix.
#
#   2. faster-whisper / ctranslate2 dynamically import several submodules
#      in ways PyInstaller's static analysis can miss. Missing any of
#      these produces a "no module named X" crash the moment the doctor
#      clicks Start (i.e. the first time that code path runs) - not at
#      launch, which makes it a nasty one to debug after the fact. They
#      are collected explicitly below rather than hoped for.
#
# Run this with:  pyinstaller build.spec       (see build.bat)
# NOT with:       pyinstaller main.py
#
# KNOWN OPEN RISK - READ BEFORE YOU BUILD ON WINDOWS
# ------------------------------------------------------
# In the Linux sandbox used to develop this spec, a frozen build
# segfaulted immediately on `from faster_whisper import WhisperModel` -
# reproducibly, with no Python traceback (a hard native crash bypasses
# main.py's try/except entirely, and is invisible in logs\app.log).
# Bisection proved: NOT customtkinter alone, NOT ctranslate2 alone, NOT
# ctranslate2+tokenizers together, NOT av alone - only reproduced with
# faster_whisper's own combined import chain. A "two copies of
# libctranslate2's shared library" theory was tested and DISPROVEN: the
# apparent second copy is a legitimate symlink PyInstaller creates on
# purpose, and removing it broke the app in a different way (clean
# ImportError, not a segfault) rather than fixing anything. The true
# root cause was not isolated within the available sandbox tooling (no
# Windows environment; no debug-symbol package available for gdb).
# Switching onefile -> onedir (see above) did NOT resolve it either.
#
# This may well be entirely Linux/sandbox-specific: Windows uses a
# completely different dynamic-library loading model (DLLs in one flat
# folder, no RPATH/symlink mechanics at all), so a class of bug that
# depends on ELF/RPATH resolution structurally may not exist there.
# It has NOT been confirmed fixed, and it has NOT been confirmed to
# reproduce on Windows either - it is an open question either way.
#
# TEST THIS FIRST, before building the installer: run
# dist\DoctorVoiceNotes\DoctorVoiceNotes.exe directly and confirm
# logs\app.log reaches the "Loading speech model" line. See
# TEST_CHECKLIST.md item 1 for the full procedure and fallback options
# if it still fails on Windows.

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = []
datas += collect_data_files("customtkinter")

hiddenimports = []
hiddenimports += collect_submodules("faster_whisper")
hiddenimports += collect_submodules("ctranslate2")
hiddenimports += collect_submodules("tokenizers")
hiddenimports += ["webrtcvad", "av", "pkg_resources", "pkg_resources.py2_warn"]
# huggingface_hub is a faster_whisper dependency, but engine.py always
# loads models with local_files_only=True (PRD Sec. 15: no internet
# communication) - the network/inference/CLI submodules are never
# exercised. collect_submodules("huggingface_hub") was tried first and
# rejected: it forces PyInstaller to import huggingface_hub's optional
# inference-provider and CLI extras during analysis, which transitively
# dragged in matplotlib, pandas, and GTK/GLib bindings - none of which
# this app uses. That bloated a test build from ~140MB to ~190MB and is
# exactly the kind of unrelated dependency drift PRD Section 4 warns
# against. Only the submodules actually used for local file loading are
# listed explicitly instead.
hiddenimports += [
    "huggingface_hub.file_download",
    "huggingface_hub.utils",
    "huggingface_hub.constants",
]

excludes = [
    "matplotlib", "pandas", "scipy", "numba", "IPython", "notebook",
    "pytest", "PyQt5", "PyQt6", "PySide2", "PySide6", "gi",
    "onnxruntime", "jupyter", "sphinx",
]

# The application icon IS bundled as a read-only resource (see
# paths.get_resource_path - resource paths are allowed inside _MEIPASS
# because they are only ever read, never written).
datas += [("assets/icons/app_icon.ico", "assets/icons")]

a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DoctorVoiceNotes",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX compression has a history of false-positive
                         # antivirus flags on Windows; not worth it for a
                         # single-doctor internal tool.
    console=False,       # windowed app - PRD requires no visible console
                         # for a doctor with limited computer experience.
    icon="assets/icons/app_icon.ico",
)

# COLLECT (not passing a.binaries/a.datas into EXE directly) is what
# makes this onedir mode: everything lands in dist/DoctorVoiceNotes/
# next to the .exe instead of being unpacked at every startup.
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="DoctorVoiceNotes",
)