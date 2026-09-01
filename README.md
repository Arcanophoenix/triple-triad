# Triple Triad solver

Next-best-move and pre-game analysis for FFXIV Triple Triad matches, plus the
card / NPC dataset it runs on.

## Quickstart

Needs Python 3.10+ (no third-party packages). From this folder:

```
./tt-cli gui                     # browser GUI - the board, click to play
./tt-cli play "Triple Triad Master" --deck starter   # same thing in the terminal
./tt-cli                         # list every command
```

`./tt-cli <command> -h` shows a command's options. It also works by full path
from any directory.

## Sharing a build

For people who don't want to install Python, `TripleTriad.spec` packages the whole
thing - engine, GUI, card art - into one double-clickable executable.

- **Cut a release:** push a tag (`git tag v0.1.0 && git push --tags`). The
  `build` workflow (`.github/workflows/build.yml`) runs the tests, builds a binary
  on Linux and Windows with PyInstaller, and attaches the zips to a GitHub Release.
  `workflow_dispatch` builds them without a tag. (macOS isn't built - add a
  `macos-latest` matrix entry if you need it; the runners cost 10x minutes.)
- **Build one locally:** `pip install pyinstaller && pyinstaller --clean --noconfirm
  TripleTriad.spec` → `dist/TripleTriad`. This is also how a Mac user gets a build.
- **What a recipient does:** unzip, run it. It starts the local server and opens
  the board in their browser, same as `./tt-cli gui`. The binary is unsigned, so
  first launch needs a nudge past the OS: Windows → "More info" → "Run anyway";
  macOS → right-click → Open (once). Their collection / history / review cache
  live in a per-user folder (`%APPDATA%\TripleTriad`, `~/Library/Application
  Support/TripleTriad`, or `~/.local/share/triple-triad`), printed on startup and
  overridable with `TRIPLE_TRIAD_HOME`. The bundled NPC decks are read-only;
  `scrape` / `deck add` in a packaged app write overrides into that same folder.

## Layout

```
gui/              browser GUI (served by scripts/gui.py, stdlib http only)
reference/        saved wiki pages (Cards, NPCs, Triple Triad) - dataset source
  NPCs/           saved individual NPC pages -> scraped into decks.json
  Cards @ ARR.../ saved ARR: Triple Triad page - card portraits for the GUI
data/
  cards.json      475 cards - stats, type, stars, acquisition, icon (generated)
  npcs.json       134 NPCs  - match rules, location, MGP, rewards (generated)
  decks.json      NPC -> 5 cards, entered by hand as you meet them
  regional.json   current regional rules per region (reset daily; `tt-cli regional`)
  collection.json cards you own + named player decks (seeded with the 5 starters)
  collection.example.json  blank template a packaged app seeds on first run
  history.jsonl   finished matches, appended by the GUI (read by `tt-cli review`)
app.py            packaged-app entry point (PyInstaller); ./tt-cli is the source-tree one
TripleTriad.spec  PyInstaller build recipe  (see "Sharing a build")
scripts/
  gui.py          local web server + engine behind the browser GUI
  extract_wiki.py rebuild cards.json + npcs.json from the saved wiki pages
  fetch_npc_pages.py  download NPC wiki pages from the saved "Triple Triad NPCs" list
  scrape_npc.py   pull NPC decks + rules from saved reference/NPCs/*.html
  deck.py         add / show / list recorded NPC decks (manual alternative)
  solve.py        move (mid-game best move) and plan (solve a match from empty)
  play.py         interactive: recommendation each of your turns, tracks the board
  recommend.py    best 5-card deck vs an NPC from the cards you own
  regional.py     show / set the current regional rules (per region)
  difficulty.py   rank NPCs by rough difficulty - who to challenge in what order
  review.py       replay logged matches; check the solver's call against the result
tt/               the engine: data, model, rules resolver, alpha-beta solver
tests/            pytest - one assertion group per rule, plus solver checks
```

## Dataset

```
python3 scripts/extract_wiki.py          # regenerate from reference/*.html
```

Source is the FFXIV Console Games Wiki (pages saved in `reference/`; the script
globs there, then the project root). The `Triple Triad` page in that folder is
the rules reference for the `VERIFY` items below. `cards.json` is the source of truth for
card stats; boards and hands store a card's index in that file as its id.

The wiki's **card faction column and NPC rule lists are unreliable**. When these
[FFXIV Collect](https://ffxivcollect.com) pages are saved (Web Page, Complete),
`extract_wiki.py` prefers them:

- `reference/Cards - FFXIV Collect.html` -> every card's faction type
- `reference/NPCs/NPCs - FFXIV Collect.html` -> every NPC's match rules + rewards

Collect has no decklists or MGP, so those still come from the wiki. `_TYPE_OVERRIDES`
and `_RULE_OVERRIDES` (in `scrape_npc.py`) patch anything wrong in both sources.
An in-game Match Registration screenshot beats everything.

## Recording an NPC deck

The NPC list gives each NPC's rules but not their 5 cards. To fill that in:

**Bulk-fetch, then scrape.** Save the "Triple Triad NPCs" list page into
`reference/`, then:

```
./tt-cli fetch     # download every roster NPC's wiki page it doesn't already have
./tt-cli scrape    # import decks + rules from reference/NPCs/*.html
```

`fetch` reads the wiki URLs out of the saved list page and pulls each NPC page
(stdlib only, ~1s apart; `--only <name>`, `--limit N`, `--dry-run`, `--force`).
`scrape` reads the deck + rules from each page, checks the rules against
`data/npcs.json`, and writes `data/decks.json`.

**Or one at a time.** Save a single NPC's wiki page into `reference/NPCs/` and
run `./tt-cli scrape "Name"`. `play.py` also prompts for an unrecorded NPC's
cards on the fly and offers to save them.

Some NPCs don't have a fixed five - a few cards are marked "Guaranteed in deck"
and the rest are a pool the game draws from to reach five. Those are stored as
`{"fixed": [...], "pool": [...], "draw": N}` instead of `{"cards": [...]}`; the
scraper detects this automatically.

You usually can't see which pool cards turned up until the NPC starts playing
them, so:

- **Solving** (next best move): the GUI match starts with the unknown pool cards
  face-down. As the NPC plays one - or immediately, if the rules show their hand -
  click it in the "not yet seen" strip to name it. Until every pool card is
  named, the recommendation is the move with the best *worst case* over the cards
  the NPC could still be holding (shown as "worst … , best …"). CLIs take the
  real five via `--npc-deck`.
- **Recommending** a deck happens before you know the draw, so it scores every
  candidate against *all* `C(pool, draw)` possible NPC decks and ranks by the
  worst of them - the deck that holds up whatever the NPC drew.

**Enter by hand:**

```
scripts/deck.py add "Aiglephine" Troll Ifrit Garuda "Ultros & Typhon" Ramuh
scripts/deck.py show Aiglephine
```

Names are loose (case-insensitive, "Card" optional, `&`/`and`, bare number).
Rules default to the NPC's match rules plus any recorded regional rules (below);
`--rules "Three Open,Plus"` overrides the lot.

## Regional rules

An NPC match runs the NPC's **match rules** (fixed, stored in `data/`) plus up to
two **regional rules** that vary by area and reset daily at 15:00 UTC. Only match
rules live in `npcs.json` / `decks.json`; the regional half is tracked per region
in `data/regional.json` and unioned onto the match rules at solve time.

Read the "Regional Rules" row off the in-game Match Registration screen, then:

```
./tt-cli regional                              # every region + what's recorded
./tt-cli regional "The Black Shroud" Same Plus # set it (dated today)
./tt-cli regional "The Black Shroud" --clear   # forget it
./tt-cli regional --npc Buscarron              # which region an NPC is in
```

The GUI shows the selected NPC's region and its regional rules under the opponent
box with an inline **edit**. Entries older than the last daily reset are flagged
stale. `zone -> region` grouping lives in `tt/regions.py` (best-effort - split a
region there if two of its NPCs show different regionals); the Gold Saucer and a
few other spots are marked regional-immune. `--no-regional` on the CLIs (and the
Rules-override field in the GUI) bypasses regional rules entirely.

## Solving

Mid-game - give the board and both remaining hands:

```
scripts/solve.py move \
  --board "Ifrit@A, ., Garuda@B, ., Titan@A, ., ., ., Ramuh@B" \
  --you "Shiva, Odin, Leviathan" --npc "Bahamut, Fenrir, Sephirot" \
  --rules "Plus,Same"            # or --npc-name "Arsieu" to look them up
```

Cells are 1..9 row-major. Under Chaos add `--card <the card you were dealt>`.
Output ranks every legal move by the forced card margin and prints the principal
variation. Mid-game positions solve in well under a second.

`--opp` picks the NPC model. `optimal` (default) assumes perfect minimax play -
safe but pessimistic. `greedy` models the in-game AI (grab the most cards now;
keep strong sides facing open cells), which is what the real NPC does: it gives
an *exploitative* move, a realistic margin, and - because the opponent stops
branching - a ~20x faster search (opening solves drop to well under a second).

### GUI

```
./tt-cli gui          # serves http://127.0.0.1:8787 and opens your browser
./tt-cli gui 9000     # different port
```

Two modes, switched from the top nav. Card portraits come from the saved ARR:
Triple Triad page (wiki icons as fallback); the board frame is stitched from
`reference/*.webp`.

**Manage decks:** on the right, a searchable list of every card - tick the
checkbox to mark what you own (writes `collection.json`; starters are always
on). On the left, the deck editor - click a card to add/drop it (max 5, at most
one 4-5★), name it, `Save`. Saved decks are shared with the CLIs.

**Solver:** type the NPC (a recorded deck loads automatically and is shown;
otherwise a field appears for their 5 cards). Pick one of your saved decks, or
hit **Recommend from owned** - an estimate over your owned pool (seconds for a
small collection, a minute or more for a large one or a many-draw NPC; a live
progress bar shows the screening pass and, with `refine`, the exact solves that
follow). `refine` runs exact solves on the top decks; against a fixed-plus-pool
NPC it reports the worst case over every possible draw. Each recommended row has
`use` (play it now) and `save` (keep it in your decks, default name
`<NPC first word> <n>`). Set who goes first, then **Start match**.

**In match:** each of your turns the recommended card + cell glow (click the cell
to take it, or any card + cell to play something else); on the NPC's turns you
click the card they played and where. Undo / New match in the top bar. If the
NPC draws from a pool, their unknown cards start face-down and there's a "not yet
seen" strip below the board - click a card there to name it once you've seen it;
the recommendation is worst-case over the unknowns until you have.

The in-match recommendation always uses the **safe minimax model** (the one that
has never over-promised in practice). It's tagged "fast estimate" only while the
board is nearly empty or the NPC still has unnamed cards - positions where an
exact solve would stall the turn - and turns exact once the board fills in.

**Auto-play my moves** (top-bar checkbox, remembered): on your turn the
recommended move is played for you a beat after it's shown - you only enter the
NPC's moves. Hitting Undo switches it back off.

**Match over:** a panel appears under the board. On a win it lists the NPC's
prize cards - click `add` on the one you won to mark it owned (writes
`collection.json`). Either way there's a **Play again** with a first / second
choice that re-deals the same matchup (same NPC, same deck; a pool NPC re-draws).
Every finished match is also appended to `data/history.jsonl` - see
`tt-cli review` below.

The Python engine runs in `scripts/gui.py`; the browser only draws. If a card
image is blank or Start says it can't reach the server, the tab is pointed at a
dead port - restart `./tt-cli gui` and open the URL it prints.

### Terminal

Live play - set the match up once, then narrate it turn by turn:

```
scripts/play.py "Aiglephine" --deck starter --second
```

Each of your turns it prints the recommended move (Enter to take it, or type
`<card> <cell>` if you played something else); on the NPC's turns you type what
they played. It renders the board and running score, rejects illegal moves, and
takes `u`ndo / `b`oard / `q`uit. If the NPC's deck isn't in `decks.json` it asks
for their 5 cards and offers to save them - so playing new NPCs fills in the data.

Pre-game - play a whole match out from an empty board (needs a recorded deck):

```
scripts/solve.py plan "Arsieu" --deck "Ramuh,Shiva,Odin,Ifrit,Titan" --second
scripts/solve.py plan "Arsieu" --deck starter          # a named deck from collection.json
```

Every player starts with the five 1-star cards Dodo / Sabotender / Bomb /
Mandragora / Coeurl; they're pre-seeded into `collection.json` as `owned` and as
the `starter` deck. Add cards and decks there as you collect them.

The opening solve is exhaustive to a full board (no heuristic eval): alpha-beta +
PVS + killer moves + transposition table, ~6 s under plain rules and ~15 s under
Plus/Same in Python. Mid-game is instant. A Rust port of `tt/solver._search` +
`tt/rules._resolve` is the next lever if sub-second openings matter.

## Deck recommender

```
scripts/recommend.py "Arsieu"                 # vs that NPC's recorded deck + rules
scripts/recommend.py "Arsieu" --pool all      # ignore ownership - theoretical best
scripts/recommend.py "X" --npc-deck "a,b,c,d,e" --rules "Plus" --exact 0
```

Ranks decks by the worse of the two coin-toss outcomes (you-first / you-second),
then by average margin. It's a funnel:

1. enumerate constraint-legal 5-card decks (<=1 card of 4-5 stars) from a
   heuristic shortlist of your pool; `--cand-cap N` keeps only the N best by card
   heuristic, so the work is bounded no matter how big your collection is;
2. **coarse screen** the whole field (greedy opening, then the last
   `--screen-tail` plies solved exactly) - against a *single representative draw*
   when the NPC's deck is only known up to a random draw, instead of every draw;
3. **worst-case re-check** the top survivors against every possible draw;
4. **exact-solve** the top `--exact` decks; for a random-draw NPC that means
   ranking them against the representative draw first and paying the full
   every-draw solve only on the finalists.

It then reports single-card upgrades from your pool.

- `--exact 0` - screens only, every result tagged `(est)`. Seconds even for a big
  collection against a many-draw NPC.
- `--exact K` - K full opening solves (~6 s plain, ~15 s Plus/Same with `optimal`;
  ~20x faster with `--opp greedy`). Raise for confidence, lower to go faster.
- `--cand-cap` / `--shortlist` shrink step 1; the screen's greedy opening is
  myopic, so `(est)` numbers can misrank - the `--exact` slice is what to trust.
- `--workers` - big runs fan out over a forked process pool. `0` (default) uses
  half your logical CPUs at idle priority (`nice 19`), so a run never competes
  with a foreground game; `1` forces serial. In the GUI, `refine` fans out
  automatically; the plain estimate stays serial (it's already sub-second).
- `--opp greedy` (default `optimal`) models the real NPC: realistic win margins
  and a much faster search, so `--exact` can cover a far larger slice. `optimal`
  is the safe lower bound.
- **Swap is modelled in deck selection.** The rule trades one random card of
  yours for one of theirs before play, so the deck you pick is never the hand you
  play - it hits the recommender squarely. Each deck is scored across the 25
  possible exchanges and **averaged**: the swap is random and uncontrollable, so
  its expectation is the honest number (their deck *draw* is still worst-cased,
  which is a floor you can plan around). Margins for a Swap NPC are therefore
  expected values, not guarantees.
  - `--swap-probe N` samples only the coarse screen (default 5, `0` = all 25).
    Every later phase re-scores on all 25 regardless, and that matters: taking
    the best of hundreds of truncated averages is a winner's curse and reads
    optimistic - the top deck's margin drifted from `+2.0` at one sample to
    `-2.2` at all 25 before this was fixed.
  - Cost: ~25x the evaluations per candidate, so a Swap NPC's estimate runs in
    seconds rather than under one. Swap **+ Order** (only Ushiogi) is the
    expensive corner - the exact pass is `orderings x draws x 25 swaps x 2
    sides` - and takes a couple of minutes.
- Roulette isn't modelled (pick the deck under the always-on rules, then re-run
  with `--rules` once you see the roll); Chaos falls back to the screen estimate.

## Who to challenge next

```
scripts/difficulty.py                     # every NPC, easiest first
scripts/difficulty.py --reverse           # hardest first
scripts/difficulty.py --zone "Gold Saucer"
scripts/difficulty.py --challenge         # only NPCs you can beat right now
scripts/difficulty.py --no-solve          # instant (skip the solver column)
```

The game has no difficulty rating, so the `score` (0-100, five tiers
intro/easy/moderate/hard/brutal) is a heuristic from the NPC's MGP payout,
reward-card rarity, release patch, and ruleset (variance rules like Chaos/Swap
push it up, All/Three Open pull it down). It's only a rough ordering.

When the NPC's **deck is recorded** (`data/decks.json`), the last column shows
the solver's real verdict - the best worst-case margin for a deck built from your
`collection.json`, against the greedy NPC model. That's the number to trust;
`--challenge` uses it to list just the winnable NPCs, best matchup first. Record
more decks with `scrape_npc.py` and more rows get a real number.

## Reviewing your games

Every match you finish in the GUI is appended to `data/history.jsonl` (your deck,
rules, who led, the NPC model, the move list, revealed pool cards, final score).
`tt-cli review` replays each one and re-solves it to check the solver against
reality:

```
scripts/review.py                # one row per game: predicted vs actual margin
scripts/review.py 7              # replay game #7 move by move
scripts/review.py --summary      # aggregate - was the solver right?
scripts/review.py --npc Momodi   # filter the list
```

- **predicted** - the solver's your-margin from the opening position (a range if
  a pool NPC held a card you never saw); **actual** - the real final margin;
  `match` / `OFF` says whether reality landed in the predicted range.
- **followed** - the turns where your move matched the recommendation (you should
  see `n/n` if you always take the pick).
- **NPC vs model** - NPC turns where the real NPC deviated from the modelled
  move, and whether that helped (`+`) or cost (`-`) you. Under `greedy` a cost
  means the real NPC out-played the model there.

The first run after new matches re-solves them (parallel, idle priority) and
caches the verdicts to `data/.review_cache.json`; later runs are instant.

In practice the `optimal` model is a reliable floor - most real city / beast-tribe
NPCs play well below it, so an `optimal` verdict of `0` ("can't lose with best
play") has tended to end +2 to +8. `greedy` is the optimistic model; trust
`optimal` when deciding whether a match is safe.

## Rules behaviour

Checked against the wiki's rules page (`reference/Triple Triad ... .html`):

- **Ascension / Descension** - each faction card on the board gives every card of
  that faction +1 / -1, stacking (N on board => +/-N). While a placement is being
  resolved the just-placed card is NOT yet counted toward its faction's total -
  not for itself, and not for its same-faction neighbours either; the counter
  only ticks up once captures settle. Ascension results cap at "A" (10);
  Descension results floor at 1. Confirmed against in-game play (Yellow Moon,
  Noes) and cross-checked against FFTriadBuddy's reference implementation.
- **Fallen Ace** - whichever side is the ATTACKER in a printed 1-vs-A matchup
  always captures the other, in both normal and Reverse play: without Reverse a
  placed 1 gains the ability to capture a defending A; with Reverse the roles
  swap and a placed A gains the ability to capture a defending 1. Cross-checked
  against FFTriadBuddy's `TriadGameModifierFallenAce` - an earlier "hard" reading
  of the wiki wording (which blocked a placed A from capturing a defending 1)
  was wrong and has been corrected.
- Same / Plus compare **effective** (Ascension-adjusted, capped) values and are
  unaffected by Reverse / Fallen Ace.
- Combo is always on; only Same/Plus flips seed a cascade, never a plain capture.
