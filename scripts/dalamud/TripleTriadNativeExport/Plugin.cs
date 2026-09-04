using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using Dalamud.Game.Command;
using Dalamud.IoC;
using Dalamud.Plugin;
using Dalamud.Plugin.Services;

namespace TripleTriadNativeExport;

public sealed class Plugin : IDalamudPlugin
{
    [PluginService] internal static IDalamudPluginInterface PluginInterface { get; private set; } = null!;
    [PluginService] internal static ICommandManager CommandManager { get; private set; } = null!;
    [PluginService] internal static IChatGui ChatGui { get; private set; } = null!;
    [PluginService] internal static IPluginLog Log { get; private set; } = null!;
    [PluginService] internal static ISigScanner SigScanner { get; private set; } = null!;

    private const string CommandName = "/ttexport";

    // The TripleTriadCard Excel sheet runs 1..475 as of Dawntrail; padded well
    // past that so a future patch's new cards get picked up without a rebuild.
    private const int MinCardId = 1;
    private const int MaxCardId = 700;

    // The TripleTriad (NPC match) Excel sheet's row ids start at 0x230002 and
    // the current roster runs up to ~2293905; padded the same way.
    private const int MinNpcId = 0x230002;
    private const int MaxNpcId = 0x230002 + 600;

    private readonly UnsafeReaderTriadCards reader;

    public Plugin()
    {
        reader = new UnsafeReaderTriadCards(SigScanner, Log);

        CommandManager.AddHandler(CommandName, new CommandInfo(OnCommand)
        {
            HelpMessage = "Export owned Triple Triad cards / beaten NPCs to JSON "
                + "for the Triple Triad solver (tt-cli import).",
        });
    }

    public void Dispose()
    {
        CommandManager.RemoveHandler(CommandName);
    }

    private void OnCommand(string command, string args)
    {
        if (reader.HasErrors)
        {
            ChatGui.PrintError("[TripleTriadNativeExport] Could not read game state - "
                + "check /xllog for details (a game patch may have moved the functions "
                + "this plugin looks for).");
            return;
        }

        var ownedCardIds = new List<int>();
        for (var id = MinCardId; id <= MaxCardId; id++)
        {
            if (reader.IsCardOwned(id))
                ownedCardIds.Add(id);
        }

        var beatenNpcIds = new List<int>();
        for (var id = MinNpcId; id <= MaxNpcId; id++)
        {
            if (reader.IsNpcBeaten(id))
                beatenNpcIds.Add(id);
        }

        var export = new
        {
            owned_card_ids = ownedCardIds,
            beaten_npc_ids = beatenNpcIds,
        };

        var dir = PluginInterface.GetPluginConfigDirectory();
        Directory.CreateDirectory(dir);
        var path = Path.Combine(dir, "export.json");
        File.WriteAllText(path, JsonSerializer.Serialize(export, new JsonSerializerOptions { WriteIndented = true }));

        Log.Information($"TripleTriadNativeExport: wrote {ownedCardIds.Count} owned card(s), "
            + $"{beatenNpcIds.Count} beaten NPC(s) to {path}");
        ChatGui.Print($"[TripleTriadNativeExport] {ownedCardIds.Count} card(s), "
            + $"{beatenNpcIds.Count} beaten NPC(s) -> {path}");
    }
}
