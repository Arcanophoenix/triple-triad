// Adapted from FFTriadBuddyDalamud's UnsafeReaderTriadCards.cs
// (https://github.com/MgAl2O4/FFTriadBuddyDalamud), MIT License,
// Copyright (c) 2021 MgAl2O4 - see LICENSE-FFTriadBuddyDalamud.txt.
//
// Ports only the read-only "does the game say I own/beat this" reader: two
// calls into the game's own already-loaded UI-state functions, found by
// signature scan, the same technique FFTriadBuddyDalamud's "find missing
// cards" feature is built on. Nothing here writes to game memory or state.
using System;
using System.Runtime.InteropServices;
using Dalamud.Plugin.Services;

namespace TripleTriadNativeExport;

public sealed class UnsafeReaderTriadCards
{
    public bool HasErrors { get; }

    private delegate byte IsCardOwnedDelegate(IntPtr uiState, ushort cardId);
    private delegate byte IsNpcBeatenDelegate(IntPtr uiState, int triadNpcId);

    private readonly IsCardOwnedDelegate? isCardOwnedFunc;
    private readonly IsNpcBeatenDelegate? isNpcBeatenFunc;
    private readonly IntPtr uiStatePtr;

    public UnsafeReaderTriadCards(ISigScanner sigScanner, IPluginLog log)
    {
        var isNpcBeatenPtr = IntPtr.Zero;
        var isCardOwnedPtr = IntPtr.Zero;

        try
        {
            // IsTriadNpcCompleted(void* uiState, int triadNpcId)
            //   identified by pretty unique rowId from the TripleTriad sheet: 0x230002
            isNpcBeatenPtr = sigScanner.ScanText("40 53 48 83 ec 20 8d 82 fe ff dc ff");

            // IsTriadCardOwned(void* uiState, ushort cardId)
            //   used by GSInfoCardList's agent, preparing the card list UI
            isCardOwnedPtr = sigScanner.ScanText("40 53 48 83 ec 20 48 8b d9 66 85 d2 74 3b 0f");

            // UIState addr, static LEA before the IsTriadCardOwned call above
            uiStatePtr = sigScanner.GetStaticAddressFromSig(
                "48 8d 0d ?? ?? ?? ?? e8 ?? ?? ?? ?? 84 c0 74 0f 8b cb");
        }
        catch (Exception ex)
        {
            log.Error(ex, "TripleTriadNativeExport: signature scan threw");
        }

        HasErrors = isNpcBeatenPtr == IntPtr.Zero || isCardOwnedPtr == IntPtr.Zero || uiStatePtr == IntPtr.Zero;
        if (!HasErrors)
        {
            isCardOwnedFunc = Marshal.GetDelegateForFunctionPointer<IsCardOwnedDelegate>(isCardOwnedPtr);
            isNpcBeatenFunc = Marshal.GetDelegateForFunctionPointer<IsNpcBeatenDelegate>(isNpcBeatenPtr);
        }
        else
        {
            log.Error("TripleTriadNativeExport: could not find the triad card/NPC functions - "
                + "a game patch likely moved them and the signatures need updating.");
        }
    }

    public bool IsCardOwned(int cardId)
    {
        if (HasErrors || cardId <= 0 || cardId > 65535) return false;
        return isCardOwnedFunc != null && isCardOwnedFunc(uiStatePtr, (ushort)cardId) != 0;
    }

    public bool IsNpcBeaten(int npcId)
    {
        if (HasErrors || npcId < 0x230002) return false;
        return isNpcBeatenFunc != null && isNpcBeatenFunc(uiStatePtr, npcId) != 0;
    }
}
