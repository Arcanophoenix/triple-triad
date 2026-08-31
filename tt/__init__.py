"""Triple Triad engine: rules resolver + alpha-beta solver for FFXIV matches.

Layout:
  tt.data   - Card DB (data/cards.json), name resolution, RuleSet.from_names
  tt.model  - board geometry, RuleSet, GameState, terminal / scoring
  tt.rules  - resolve_placement(): the capture resolver (basic/Same/Plus/Combo/…)
  tt.solver - legal_moves / apply / analyze(): best move to terminal via alpha-beta
  tt.format - parse/render boards and decks for the CLI

VERIFY markers flag rules behaviour taken from community docs that should be
confirmed against the live game before the solver's verdicts are trusted.
"""
