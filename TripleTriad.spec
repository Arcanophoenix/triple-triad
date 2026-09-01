# PyInstaller build spec.  Local build:  pyinstaller --clean --noconfirm TripleTriad.spec
# CI builds one of these per OS; see .github/workflows/build.yml
from pathlib import Path

ROOT = Path(SPECPATH)

_ICONS = ("Triple Triad Cards - Final Fantasy XIV Online Wiki - FFXIV _ "
          "FF14 Online Community Wiki and Guide_files")
_ARR = "Cards @ ARR_ Triple Triad - Final Fantasy XIV_files"
_ARR_HTML = "Cards @ ARR_ Triple Triad - Final Fantasy XIV.html"

# read-only resources that ship inside the exe (see tt/paths.py: RESOURCE_ROOT)
datas = [
    (str(ROOT / "gui"), "gui"),
    (str(ROOT / "data" / "cards.json"), "data"),
    (str(ROOT / "data" / "npcs.json"), "data"),
    (str(ROOT / "data" / "decks.json"), "data"),
    (str(ROOT / "data" / "regional.json"), "data"),
    (str(ROOT / "data" / "collection.example.json"), "data"),
    (str(ROOT / "reference" / _ICONS), f"reference/{_ICONS}"),
    (str(ROOT / "reference" / _ARR), f"reference/{_ARR}"),
    (str(ROOT / "reference" / _ARR_HTML), "reference"),
]

# app.py imports sub-commands dynamically, so name them for the analysis
hiddenimports = [
    "tt", "tt.paths", "tt.data", "tt.model", "tt.rules", "tt.solver",
    "tt.recommend", "tt.regions", "tt.format",
    "gui", "play", "solve", "recommend", "regional", "difficulty", "review",
    "fetch_npc_pages", "scrape_npc", "deck", "extract_wiki", "ttdata",
]

a = Analysis(
    ["app.py"],
    pathex=[str(ROOT / "scripts")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyInstaller", "pytest", "_pytest", "pip", "setuptools"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="TripleTriad",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
)
