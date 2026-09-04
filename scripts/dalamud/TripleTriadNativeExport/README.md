# Triple Triad Native Export

A small dev-only Dalamud plugin: reads the game's own "do I own this card" /
"have I beaten this NPC" state and writes it to a JSON file for
`tt-cli import` to pick up. No network access. No writes to game memory or
state - it only *calls* two functions the game's own UI already calls.

**How it works, and its real limits:** `UnsafeReaderTriadCards.cs` is adapted
from [FFTriadBuddyDalamud](https://github.com/MgAl2O4/FFTriadBuddyDalamud)
(MIT, see `LICENSE-FFTriadBuddyDalamud.txt`), an existing, widely-used Dalamud
plugin. It finds two of the game's own functions by *signature scan* (a byte
pattern, not a fixed memory address) and calls them for every plausible card
id (1-700) and NPC id (0x230002-0x230258). This is the same technique that
plugin's "find missing cards" feature already ships. The real caveat:
signature bytes can be invalidated by a major game patch - if `/ttexport`
reports an error, check `/xllog`; the plugin will need its two `ScanText`
patterns (and the `GetStaticAddressFromSig` one) re-found for the new binary,
the same maintenance every such plugin needs after a big patch.

This project could not verify this actually builds and loads - it was written
against the real Dalamud API surface (Dalamud Hooks 15.0.3.2, installed
locally at `~/.xlcore/dalamud/Hooks/`) but this machine has no .NET SDK to
compile it. Build it yourself and report back any compiler errors.

## Building

1. Install the .NET SDK matching Dalamud's target (`dotnet --list-sdks`; get
   one from [dotnet.microsoft.com](https://dotnet.microsoft.com/download) if
   you don't have it - Dalamud Hooks 15.0.3.2 here targets `net10.0`).
2. `cd` into this directory and run:
   ```
   dotnet build -c Release
   ```
   The `Dalamud.NET.Sdk` MSBuild SDK (declared at the top of the `.csproj`)
   auto-locates your local Dalamud install - no manual reference paths
   needed, same as the official
   [SamplePlugin](https://github.com/goatcorp/SamplePlugin) template this is
   based on. If it can't find Dalamud, set the `DALAMUD_HOME` environment
   variable to your Dalamud Hooks dev folder
   (`~/.xlcore/dalamud/Hooks/dev` on this machine) and retry.
3. The built plugin DLL will be at
   `bin/Release/TripleTriadNativeExport.dll` (or similar - the exact
   subfolder depends on the SDK version; `dotnet build` prints the path).

## Loading in-game

1. In chat, run `/xlsettings` -> `Experimental` -> add the **folder**
   containing the built `.dll` to *Dev Plugin Locations*.
2. Run `/xlplugins` -> `Dev Tools` -> `Installed Dev Plugins` -> enable
   `Triple Triad Native Export`.
3. Run `/ttexport` anywhere (no match needs to be active). It prints how many
   cards/NPCs it found and the export file's path to chat, and writes to
   `<plugin config dir>/export.json`.

## Importing into the solver

```
tt-cli import "<path from the chat message>/export.json"
```

Same merge-by-default semantics as an FFXIV Collect import (see
`scripts/collect_import.py --help`) - it will not lose anything you've
recorded by hand.
