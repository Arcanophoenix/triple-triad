"use strict";

let CARDS = {};                       // id -> {name, sides, stars, kind, icon}
let BOOT = null;
let OWNED = new Set();                // owned card ids
let STARTERS = new Set();             // starter card ids (always owned)
let COLDECKS = {};                    // deck name -> [card names]

const G = { state: null, history: [], npc: "", sel: null, analysis: null, rewards: [], autoplay: false };
const EDIT = { name: "", ids: [] };   // Manage: the deck being edited
let SOLVE_IDS = [];                   // Solver: chosen deck (card ids)
let ANALYZE_SEQ = 0;                  // guards against stale /api/analyze responses
const AUTOPLAY_DELAY = 450;           // ms to show the pick before auto-playing it

const $ = (id) => document.getElementById(id);
const h = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };

const NO_SERVER = "can't reach the solver server — is `./tt-cli gui` still running? " +
  "restart it and open the URL it prints (this tab may be pointed at an old port)";
const post = async (url, body) => {
  let r;
  try {
    r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch (e) {
    throw new Error(NO_SERVER);
  }
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
};
const face = (v) => (v === 10 ? "A" : String(v));
const fmt = (v) => (v > 0 ? "+" : "") + (Math.round(v * 10) / 10);
const noCard = (s) => String(s).toLowerCase().replace(/ card$/, "").trim();
const short = (s) => String(s).replace(/ Card$/, "");

function nameToId(name) {
  const q = noCard(name);
  for (const [id, c] of Object.entries(CARDS)) if (noCard(c.name) === q) return +id;
  return null;
}
const namesToIds = (list) => (list || []).map(nameToId).filter((x) => x != null);
const idsToNames = (ids) => ids.map((id) => CARDS[id].name);

// ---------- views ----------
function showView(name) {
  for (const v of ["solver", "manage", "game"]) $("view-" + v).hidden = v !== name;
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  if (name === "manage") renderManage();
  if (name === "solver") renderSolver();
}

// ---------- boot ----------
async function boot() {
  try {
    BOOT = await (await fetch("/api/bootstrap")).json();
  } catch (e) {
    $("setup-err").textContent = NO_SERVER;
    return;
  }
  CARDS = BOOT.cards;
  OWNED = new Set(BOOT.ownedIds || []);
  STARTERS = new Set(BOOT.starterIds || []);
  COLDECKS = BOOT.collectionDecks || {};

  const nl = $("npclist");
  BOOT.npcs.slice().sort((a, b) => a.name.localeCompare(b.name)).forEach((n) => {
    const o = h("option"); o.value = n.name;
    o.label = `${n.rules.join(", ") || "no special rules"}${n.hasDeck ? "  ·  deck known" : ""}`;
    nl.appendChild(o);
  });

  document.querySelectorAll(".nav-btn").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));

  // solver
  $("npc").addEventListener("input", refreshNpcInfo);
  $("deck-pick").addEventListener("change", (e) => {
    SOLVE_IDS = e.target.value ? namesToIds(COLDECKS[e.target.value]) : [];
    $("rec-out").innerHTML = "";
    renderPreview();
  });
  $("recommend-btn").addEventListener("click", () => runRecommend(false));
  $("start").addEventListener("click", start);
  $("undo").addEventListener("click", undo);
  $("newgame").addEventListener("click", () => { resetGame(); showView("solver"); });

  try { G.autoplay = localStorage.getItem("tt_autoplay") === "1"; } catch (e) { /* private mode */ }
  $("autoplay").checked = G.autoplay;
  $("autoplay").addEventListener("change", (e) => {
    G.autoplay = e.target.checked;
    try { localStorage.setItem("tt_autoplay", G.autoplay ? "1" : "0"); } catch (er) { /* ignore */ }
    if (G.autoplay) autoMoveIfEnabled();       // it might already be your turn
  });

  // manage
  $("deck-load").addEventListener("change", (e) => { if (e.target.value) loadEditDeck(e.target.value); });
  $("deck-new").addEventListener("click", () => {
    EDIT.name = ""; EDIT.ids = []; $("deck-name").value = ""; $("deck-msg").textContent = ""; renderManage();
  });
  $("card-filter").addEventListener("input", renderPicker);
  $("owned-only").addEventListener("change", renderPicker);
  $("save-deck").addEventListener("click", saveEditDeck);
  $("del-deck").addEventListener("click", deleteEditDeck);

  refreshDeckSelects();
  showView("solver");
}

function refreshDeckSelects() {
  const names = Object.keys(COLDECKS);
  for (const [sel, ph] of [["deck-pick", "— pick a saved deck —"], ["deck-load", "— load a deck —"]]) {
    const el = $(sel); const cur = el.value;
    el.innerHTML = "";
    const o0 = h("option"); o0.value = ""; o0.textContent = ph; el.appendChild(o0);
    names.forEach((n) => { const o = h("option"); o.value = n; o.textContent = n; el.appendChild(o); });
    if (names.includes(cur)) el.value = cur;
  }
}

// ---------- solver ----------
function renderSolver() { refreshNpcInfo(); renderPreview(); }

function npcByName(name) {
  const q = name.trim().toLowerCase();
  return BOOT.npcs.find((n) => n.name.toLowerCase() === q) ||
         (q ? BOOT.npcs.find((n) => n.name.toLowerCase().includes(q)) : null) || null;
}
const deckEntry = (n) => (n ? BOOT.decks[n.name] || null : null);

function refreshNpcInfo() {
  const n = npcByName($("npc").value);
  const d = deckEntry(n);
  const variable = !!(d && d.pool);

  let info = "";
  if (n) {
    info = `${n.zone}  ·  rules: ${n.rules.join(", ") || "none"}`;
    if (d && d.cards) info += `  ·  deck: ${d.cards.map(short).join(", ")}`;
    else if (variable)
      info += `  ·  ${d.fixed.map(short).join(", ")} + ${d.draw} of [${d.pool.map(short).join(", ")}]`;
    else info += "  ·  deck not recorded";
  }
  $("npc-info").textContent = info;
  $("npc-deck").value = "";
  $("npc-deck-wrap").hidden = !(n && !d);        // free-text: nothing recorded at all
}

function npcPayload() {
  return {
    npc: $("npc").value.trim(),
    rules: $("rules").value.trim() ? $("rules").value.split(",").map((s) => s.trim()) : null,
    npcCards: $("npc-deck").value.trim() ? $("npc-deck").value.split(",").map((s) => s.trim()) : null,
  };
}

function renderPreview() {
  const box = $("deck-preview");
  box.innerHTML = "";
  SOLVE_IDS.forEach((id) => box.appendChild(miniCard(id)));
  if (SOLVE_IDS.length && SOLVE_IDS.length !== 5) box.appendChild(h("span", "hint", `${SOLVE_IDS.length}/5`));
  if (SOLVE_IDS.filter((id) => CARDS[id].stars >= 4).length > 1) box.appendChild(h("span", "hint bad", "too many 4-5★"));
}

let REC_ABORT = null;                 // in-flight recommend, so a new run supersedes it

function recProgressUI() {
  const wrap = h("div", "rec-progress");
  const label = h("div", "rp-label", "starting…");
  const bar = document.createElement("progress");
  bar.max = 1; bar.value = 0;
  const count = h("div", "rp-count", "");
  wrap.append(label, bar, count);
  const t0 = performance.now();
  const secs = () => ((performance.now() - t0) / 1000).toFixed(0);
  return {
    el: wrap,
    apply(m) {
      if (m.phase === "screen") {
        label.textContent = "Screening candidate decks…";
        bar.max = m.total; bar.value = m.done;
        count.textContent = `${m.done} / ${m.total} decks  ·  ${secs()}s`;
      } else if (m.phase === "worstcase") {
        label.textContent = "Worst-case check vs every possible draw…";
        bar.max = m.total; bar.value = m.done;
        count.textContent = `${m.done} / ${m.total}  ·  ${secs()}s`;
      } else if (m.phase === "exact-start") {
        if (m.k) {
          label.textContent = `Screened ${m.screened} decks — exact-solving the top ${m.k}…`;
          bar.max = m.k; bar.value = 0;
        } else {
          label.textContent = `Screened ${m.screened} decks — finishing…`;
          bar.removeAttribute("value");           // indeterminate
        }
        count.textContent = `${secs()}s`;
      } else if (m.phase === "exact" || m.phase === "exact-worstcase") {
        label.textContent = m.phase === "exact-worstcase"
          ? "Exact worst-case on the finalists…" : "Exact-solving the top decks…";
        bar.max = m.total; bar.value = m.done;
        count.textContent = `${m.done} / ${m.total} solved  ·  ${secs()}s`;
      }
    },
  };
}

async function runRecommend(refine) {
  const out = $("rec-out");
  out.innerHTML = "";
  if (REC_ABORT) REC_ABORT.abort();
  const ctrl = new AbortController();
  REC_ABORT = ctrl;
  const prog = recProgressUI();
  out.appendChild(prog.el);
  try {
    const resp = await fetch("/api/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...npcPayload(), refine }),
      signal: ctrl.signal,
    });
    if (!resp.ok) {
      let msg = resp.statusText;
      try { msg = (await resp.json()).error || msg; } catch (e) { /* not json */ }
      throw new Error(msg);
    }
    const reader = resp.body.getReader();
    const dec = new TextDecoder();
    let buf = "", result = null, errMsg = null;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let m;
        try { m = JSON.parse(line); } catch (e) { continue; }
        if (m.type === "progress") prog.apply(m);
        else if (m.type === "result") result = m;
        else if (m.type === "error") errMsg = m.error;
      }
    }
    if (errMsg) throw new Error(errMsg);
    if (!result) throw new Error("the recommender returned nothing");
    renderRecResults(result);
  } catch (e) {
    if (e.name === "AbortError") return;          // a newer run took over
    out.innerHTML = "";
    out.appendChild(h("div", "err", e.name === "TypeError" ? NO_SERVER : e.message));
  } finally {
    if (REC_ABORT === ctrl) REC_ABORT = null;
  }
}
function renderRecResults(r) {
  const out = $("rec-out");
  G.recNpc = r.npc;
  out.innerHTML = "";
  out.appendChild(h("div", "hint", `${r.refined ? "exact" : "estimated"} · screened ${r.screened} decks vs ${r.npc}`));
  if (r.note) out.appendChild(h("div", "hint", r.note));
  const status = h("div", "hint");
  r.results.forEach((res) => {
    const row = h("div", "rec-row");
    row.appendChild(h("span", "rec-cards", res.cards.map(short).join(", ")));
    row.appendChild(h("span", "rec-mrg", `first ${fmt(res.first)} / second ${fmt(res.second)} · worst ${fmt(res.worst)}`));
    const use = h("button", "ghost", "use");
    use.addEventListener("click", () => {
      SOLVE_IDS = namesToIds(res.cards);
      $("deck-pick").value = "";
      out.querySelectorAll(".rec-row").forEach((x) => x.classList.remove("chosen"));
      row.classList.add("chosen");
      renderPreview();
    });
    const save = h("button", "ghost", "save");
    save.addEventListener("click", () => saveRecDeck(res.cards, status));
    row.append(use, save);
    out.appendChild(row);
  });
  out.appendChild(status);
  if (!r.refined) {
    const btn = h("button", "ghost", "refine (slow, exact)");
    btn.addEventListener("click", () => runRecommend(true));
    out.appendChild(btn);
  }
}

async function saveRecDeck(cards, status) {
  const base = (G.recNpc || "deck").trim().split(/\s+/)[0] || "deck";
  let n = 1;
  while (COLDECKS[`${base} ${n}`]) n++;
  const name = (prompt("Save this deck as:", `${base} ${n}`) || "").trim();
  if (!name) return;
  try {
    const rr = await post("/api/savedeck", { name, cards });
    COLDECKS = rr.collectionDecks; BOOT.collectionDecks = rr.collectionDecks;
    refreshDeckSelects();
    SOLVE_IDS = namesToIds(cards);
    if (COLDECKS[name]) $("deck-pick").value = name;
    renderPreview();
    status.textContent = `saved as "${name}" — pick it from your decks any time`;
    status.classList.remove("bad");
  } catch (e) { status.textContent = e.message; status.classList.add("bad"); }
}

async function start() {
  $("setup-err").textContent = "";
  if (SOLVE_IDS.length !== 5) { $("setup-err").textContent = "pick a saved deck or use Recommend (need 5 cards)"; return; }
  if (SOLVE_IDS.filter((id) => CARDS[id].stars >= 4).length > 1) {
    $("setup-err").textContent = "a deck may only hold one 4-5★ card"; return;
  }
  G.pendingCfg = {
    ...npcPayload(),
    deck: idsToNames(SOLVE_IDS),
    youFirst: document.querySelector("input[name=first]:checked").value === "1",
    opp: "optimal",   // in-match recommendation always uses the safe (minimax) model;
                      // the server drops to a fast estimate only for slow positions
  };
  try {
    const r = await post("/api/newgame", G.pendingCfg);
    enterGame(r);
  } catch (e) { $("setup-err").textContent = e.message; }
}

function enterGame(r) {
  G.state = r.state; G.npc = r.npc; G.history = [];
  G.sel = null; G.analysis = null;
  G.poolInfo = r.poolInfo || null;   // {fixed, pool, draw} for a variable-deck NPC
  G.rewards = r.rewards || [];        // the NPC's prize cards, for the post-match panel
  G.logMeta = {                       // for the history log written when the match ends
    deck: r.state.hands[0].slice(),   // your opening hand = your deck
    youFirst: !!G.pendingCfg.youFirst,
    opp: G.pendingCfg.opp,
    saved: false,
  };
  $("name-npc").textContent = r.npc;
  showView("game");
  buildGrid();
  refresh();
}

function resetGame() {
  G.state = null; G.history = []; G.sel = null; G.analysis = null; G.poolInfo = null;
  G.rewards = []; G.logMeta = null;
  $("npc-unseen").hidden = true;
  $("postmatch").hidden = true;
}

// Rebuild the move list by diffing consecutive board states (robust to Undo).
// A step that fills no cell is a reveal, not a move.
function deriveGameLog() {
  const seq = [...G.history, G.state];
  const moves = [];
  for (let k = 1; k < seq.length; k++) {
    const a = seq[k - 1], b = seq[k];
    let cell = -1;
    for (let c = 0; c < 9; c++) if (a.board[c] == null && b.board[c] != null) { cell = c; break; }
    if (cell >= 0) moves.push([a.to_move, b.board[cell].card, cell]);
  }
  const first1 = new Set(seq[0].hands[1].filter((x) => x != null));
  const revealed = [];
  for (const st of seq) for (const id of st.hands[1]) {
    if (id != null && !first1.has(id) && !revealed.includes(id)) revealed.push(id);
  }
  return { moves, revealed };
}

async function saveGameLog() {
  if (!G.logMeta || G.logMeta.saved || !G.state || !G.state.terminal) return;
  G.logMeta.saved = true;   // guard: render() calls renderPostMatch() repeatedly
  const { moves, revealed } = deriveGameLog();
  try {
    await post("/api/loggame", {
      npc: G.npc,
      rules: G.state.rules,
      deck: G.logMeta.deck,           // card ids, like moves / revealed
      youFirst: G.logMeta.youFirst,
      opp: G.logMeta.opp,
      moves, revealed,
      scoreYou: G.state.scoreYou,
    });
  } catch (e) { G.logMeta.saved = false; }   // let a later render() retry
}

// won a card off the match — mark it owned
async function addPrize(id) {
  const box = $("postmatch");
  try {
    const r = await post("/api/setowned", { card: CARDS[id].name, owned: true });
    OWNED = new Set(r.ownedIds);
  } catch (e) {
    const m = box.querySelector(".pm-msg");
    if (m) { m.textContent = e.message; m.classList.add("bad"); }
    return;
  }
  renderPostMatch();
}

// start a fresh match against the same NPC with the same deck; pick who leads
async function replayMatch(youFirst) {
  if (!G.pendingCfg) return;
  G.pendingCfg = { ...G.pendingCfg, youFirst };
  try {
    const r = await post("/api/newgame", G.pendingCfg);
    enterGame(r);
  } catch (e) { $("tip").textContent = e.message; }
}

function renderPostMatch() {
  const box = $("postmatch");
  const s = G.state;
  if (!s || !s.terminal) { box.hidden = true; box.innerHTML = ""; return; }
  box.hidden = false;
  box.innerHTML = "";

  const you = s.scoreYou, npc = 10 - you;
  const res = you > 5 ? "win" : you < 5 ? "loss" : "draw";
  const head = res === "win" ? `You beat ${G.npc}  ${you}–${npc}`
             : res === "loss" ? `Lost to ${G.npc}  ${you}–${npc}`
             : `Drew with ${G.npc}  ${you}–${npc}`;
  box.appendChild(h("div", "pm-head " + res, head));

  if (res === "win" && G.rewards.length) {
    const pz = h("div", "pm-prizes");
    pz.appendChild(h("div", "pm-label", `Won a card from ${G.npc}? Add it to your collection:`));
    const cards = h("div", "pm-cards");
    G.rewards.forEach((rw) => {
      const cell = h("div", "pm-card");
      cell.appendChild(miniCard(rw.id));
      cell.appendChild(h("span", "pm-cardname", short(rw.name)));
      const owned = OWNED.has(rw.id);
      const btn = h("button", "ghost", owned ? "owned ✓" : "add");
      btn.disabled = owned;
      if (!owned) btn.addEventListener("click", () => addPrize(rw.id));
      cell.appendChild(btn);
      cards.appendChild(cell);
    });
    pz.appendChild(cards);
    pz.appendChild(h("div", "pm-msg hint"));
    box.appendChild(pz);
  }

  const again = h("div", "pm-again");
  again.appendChild(h("div", "pm-label", `Play ${G.npc} again:`));
  const btns = h("div", "pm-againbtns");
  const b1 = h("button", "primary", "You go first");
  const b2 = h("button", "ghost", `${G.npc} goes first`);
  b1.addEventListener("click", () => replayMatch(true));
  b2.addEventListener("click", () => replayMatch(false));
  btns.append(b1, b2);
  again.appendChild(btns);
  box.appendChild(again);

  box.appendChild(h("div", "pm-note", "Logged — run  tt-cli review  to check the solver's call against the result."));
  saveGameLog();
}

// name one of the NPC's face-down cards once you've seen it played
async function reveal(cardId) {
  try {
    G.history.push(G.state);
    const r = await post("/api/reveal", { state: G.state, card: cardId });
    G.state = r.state; G.analysis = null;
    await refresh();
  } catch (e) { G.history.pop(); $("tip").textContent = e.message; }
}
function renderUnseen() {
  const box = $("npc-unseen");
  const s = G.state;
  const holes = s.hands[1].filter((c) => c == null).length;
  if (!holes || !s.npcPool || !s.npcPool.length) { box.hidden = true; return; }
  box.hidden = false;
  box.innerHTML = "";
  box.appendChild(h("span", "unseen-label",
    `${G.npc} — ${holes} card${holes > 1 ? "s" : ""} you haven't seen (click when one turns up):`));
  s.npcPool.forEach((id) => {
    const m = miniCard(id);
    m.title = CARDS[id].name;
    m.addEventListener("click", () => reveal(id));
    box.appendChild(m);
  });
}

// ---------- manage ----------
function loadEditDeck(name) {
  EDIT.name = name === "starter" ? "" : name;
  EDIT.ids = namesToIds(COLDECKS[name] || []);
  $("deck-name").value = EDIT.name;
  $("deck-msg").textContent = name === "starter"
    ? "loaded the starter deck — save it under a new name to keep edits" : "";
  renderManage();
}
function renderManage() {
  renderSlots();
  renderPicker();
  $("own-count").textContent = `${OWNED.size} owned`;
}
function renderSlots() {
  const slots = $("deck-slots");
  slots.innerHTML = "";
  for (let i = 0; i < 5; i++) {
    const s = h("div", "slot");
    const id = EDIT.ids[i];
    if (id != null) {
      s.appendChild(miniCard(id));
      s.title = CARDS[id].name + " — click to remove";
      s.addEventListener("click", () => { EDIT.ids.splice(i, 1); renderManage(); });
    } else { s.classList.add("empty"); }
    slots.appendChild(s);
  }
  const hi = EDIT.ids.filter((id) => CARDS[id].stars >= 4).length;
  const c = $("deck-count");
  c.textContent = `${EDIT.ids.length}/5` + (hi > 1 ? "  ·  too many 4-5★ cards" : "");
  c.classList.toggle("bad", hi > 1);
}
function renderPicker() {
  const q = $("card-filter").value.toLowerCase().trim();
  const ownedOnly = $("owned-only").checked;
  const pick = $("card-picker");
  const keepScroll = pick.scrollTop;
  pick.innerHTML = "";
  let shown = 0;
  const ids = Object.keys(CARDS).map(Number).sort((a, b) => CARDS[a].name.localeCompare(CARDS[b].name));
  for (const id of ids) {
    const c = CARDS[id];
    if (ownedOnly && !OWNED.has(id)) continue;
    if (q && !c.name.toLowerCase().includes(q) && String(id) !== q) continue;
    if (++shown > 300) { pick.appendChild(h("div", "pick-more", "…narrow the filter to see more")); break; }
    const row = h("div", "pick-row");
    if (EDIT.ids.includes(id)) row.classList.add("in");

    const own = h("input"); own.type = "checkbox"; own.className = "own"; own.checked = OWNED.has(id);
    if (STARTERS.has(id)) { own.disabled = true; own.title = "starter card — always owned"; }
    own.addEventListener("click", (e) => e.stopPropagation());
    own.addEventListener("change", () => setOwned(id, own.checked));
    row.appendChild(own);

    row.appendChild(h("span", "pk-name", c.name.replace(/ Card$/, "")));
    row.appendChild(h("span", "pk-stars", "★".repeat(c.stars)));
    row.appendChild(h("span", "pk-sides", c.sides.map(face).join("/")));
    row.addEventListener("click", () => {
      const at = EDIT.ids.indexOf(id);
      if (at >= 0) EDIT.ids.splice(at, 1);
      else if (EDIT.ids.length < 5) EDIT.ids.push(id);
      renderManage();
    });
    pick.appendChild(row);
  }
  pick.scrollTop = keepScroll;
}
async function setOwned(id, owned) {
  try {
    const r = await post("/api/setowned", { card: CARDS[id].name, owned });
    OWNED = new Set(r.ownedIds);
  } catch (e) { $("deck-msg").textContent = e.message; }
  renderManage();
}
async function saveEditDeck() {
  const name = $("deck-name").value.trim();
  const msg = $("deck-msg");
  try {
    const r = await post("/api/savedeck", { name, cards: idsToNames(EDIT.ids) });
    COLDECKS = r.collectionDecks; BOOT.collectionDecks = r.collectionDecks;
    EDIT.name = name;
    refreshDeckSelects();
    msg.textContent = `saved "${name}"`; msg.classList.remove("bad");
  } catch (e) { msg.textContent = e.message; msg.classList.add("bad"); }
}
async function deleteEditDeck() {
  const name = $("deck-name").value.trim();
  const msg = $("deck-msg");
  if (!name || name === "starter") { msg.textContent = "type the name of a saved deck to delete it"; return; }
  try {
    const r = await post("/api/deletedeck", { name });
    COLDECKS = r.collectionDecks; BOOT.collectionDecks = r.collectionDecks;
    EDIT.name = ""; EDIT.ids = []; $("deck-name").value = "";
    refreshDeckSelects();
    msg.textContent = `deleted "${name}"`; msg.classList.remove("bad");
    renderManage();
  } catch (e) { msg.textContent = e.message; msg.classList.add("bad"); }
}

// ---------- card art ----------
function miniCard(id) {
  const c = CARDS[id];
  const e = h("div", "mini");
  e.style.backgroundImage = `url(/card/${id}.png)`;
  e.appendChild(h("span", "num n-n", face(c.sides[0])));
  e.appendChild(h("span", "num n-e", face(c.sides[1])));
  e.appendChild(h("span", "num n-s", face(c.sides[2])));
  e.appendChild(h("span", "num n-w", face(c.sides[3])));
  return e;
}
function cardEl(id, owner) {
  const c = CARDS[id];
  const e = h("div", "card owner-" + owner);
  e.style.backgroundImage = `url(/card/${id}.png)`;
  e.appendChild(h("span", "num n-n", face(c.sides[0])));
  e.appendChild(h("span", "num n-e", face(c.sides[1])));
  e.appendChild(h("span", "num n-s", face(c.sides[2])));
  e.appendChild(h("span", "num n-w", face(c.sides[3])));
  return e;
}

// ---------- board ----------
function buildGrid() {
  const g = $("grid"); g.innerHTML = "";
  for (let i = 0; i < 9; i++) {
    const c = h("div", "cell"); c.dataset.cell = i;
    c.addEventListener("click", () => onCell(i));
    g.appendChild(c);
  }
}
function renderHand(side, recCard) {
  const wrap = $(side === 0 ? "hand-you" : "hand-npc");
  wrap.innerHTML = "";
  const hand = G.state.hands[side];
  for (let i = 0; i < 5; i++) {
    const slot = h("div", "slot");
    const id = hand[i];
    if (id === null) {
      slot.appendChild(h("div", "card unknown", "?"));   // NPC card not yet identified
    } else if (id != null) {
      slot.appendChild(cardEl(id, side));
      if (G.sel === id && side === G.state.to_move) slot.classList.add("sel");
      if (recCard != null && recCard === id) slot.classList.add("rec");
      slot.addEventListener("click", () => onHand(side, id));
    }
    wrap.appendChild(slot);
  }
}
function render() {
  const s = G.state;
  $("rules-badge").textContent = s.rules.join(", ") || "no special rules";
  $("score").textContent = `You ${s.scoreYou} – ${10 - s.scoreYou} ${G.npc}`;
  $("turn").textContent = s.terminal ? "" : (s.to_move === 0 ? "your move" : `${G.npc}'s move — enter it`);

  // a recommendation is only shown if it still fits the current board: right side
  // to move, target cell still empty, card still in hand (guards a stale analyze)
  const a = G.analysis;
  const recFits = a && !s.terminal && a.toMove === s.to_move &&
    a.best.cell >= 0 && a.best.cell < 9 && s.board[a.best.cell] == null &&
    (s.hands[s.to_move] || []).includes(a.best.card);

  $("grid").querySelectorAll(".cell").forEach((cell, i) => {
    cell.innerHTML = ""; cell.classList.remove("rec");
    cell.classList.toggle("empty", s.board[i] == null);
    if (s.board[i]) cell.appendChild(cardEl(s.board[i].card, s.board[i].owner));
  });
  renderHand(0, recFits ? a.best.card : null);
  renderHand(1, null);
  renderUnseen();

  if (recFits) {
    $("grid").children[a.best.cell].classList.add("rec");
    const outcome = (v) => (v > 0 ? `win by ${v}` : v < 0 ? `lose by ${-v}` : "draw");
    let verdict = outcome(a.best.value);
    if (a.uncertain)
      verdict = a.best.value === a.best.best
        ? `${outcome(a.best.value)} either way`
        : `worst ${outcome(a.best.value)}, best ${outcome(a.best.best)}`;
    const who = s.to_move === 0 ? "play" : `${G.npc} likely plays`;
    const tag = a.approx ? "  ·  fast estimate" : "";
    $("rec-line").textContent = `${who} ${CARDS[a.best.card].name} → cell ${a.best.cell + 1}   (${verdict})${tag}`;
  } else {
    $("rec-line").textContent = "";
  }

  const b = $("banner");
  if (s.terminal) {
    const r = s.scoreYou > 5 ? "win" : s.scoreYou < 5 ? "loss" : "draw";
    b.hidden = false; b.className = "banner " + r;
    b.textContent = r === "win" ? "WIN" : r === "loss" ? "LOSS" : "DRAW";
  } else { b.hidden = true; }
  renderPostMatch();

  const unseen = s.hands[1].some((c) => c === null);
  $("tip").textContent = s.terminal ? "" :
    unseen ? "when the NPC plays a card you haven't seen, click it in the row below to name it — then click it in their hand and the cell"
    : s.to_move === 0 ? "click a card then an empty cell — or click the glowing cell to take the pick"
                      : "click the card the NPC played, then the cell they put it in";
}
async function refresh() {
  render();
  if (G.state.terminal) return;
  if (G.state.to_move === 0) {
    if (G.state.hands[1].some((c) => c === null))
      $("tip").textContent = "working out the worst case over the NPC's unknown cards…";
    const seq = ++ANALYZE_SEQ;
    const stateAtCall = G.state;
    let a = null, err = null;
    try { a = await post("/api/analyze", { state: G.state }); }
    catch (e) { err = e; }
    if (seq !== ANALYZE_SEQ || G.state !== stateAtCall) return;   // superseded by a newer move/reveal
    if (err) { G.analysis = null; $("tip").textContent = "analyze failed: " + err.message; }
    else G.analysis = a;
    render();
    autoMoveIfEnabled();
  } else {
    G.analysis = null;
  }
}

// with "Auto-play my moves" on, take the recommended move for you a beat after
// it's shown; the NPC's moves are still entered by hand
function autoMoveIfEnabled() {
  if (!G.autoplay || !G.state || G.state.terminal || G.state.to_move !== 0) return;
  const a = G.analysis;
  if (!a || a.toMove !== 0) return;
  const { cell, card } = a.best;
  if (!(cell >= 0 && cell < 9) || G.state.board[cell] != null) return;
  if (!G.state.hands[0].includes(card)) return;
  const at = G.state;
  $("tip").textContent = "auto-playing the recommended move…";
  setTimeout(() => {
    if (G.autoplay && G.state === at && !G.state.terminal && G.state.to_move === 0) onCell(cell);
  }, AUTOPLAY_DELAY);
}

// ---------- interaction ----------
function onHand(side, id) {
  if (G.state.terminal || side !== G.state.to_move) return;
  G.sel = (G.sel === id) ? null : id;
  render();
}
async function onCell(i) {
  const s = G.state;
  if (s.terminal || s.board[i] != null) return;
  let card = G.sel;
  if (card == null && G.analysis && G.analysis.toMove === s.to_move &&
      G.analysis.best.cell === i && s.hands[s.to_move].includes(G.analysis.best.card))
    card = G.analysis.best.card;
  if (card == null) { $("tip").textContent = "pick a card first"; return; }
  if (!s.hands[s.to_move].includes(card)) return;
  try {
    G.history.push(s);
    const r = await post("/api/apply", { state: s, card, cell: i });
    G.state = r.state; G.sel = null; G.analysis = null;
    await refresh();
  } catch (e) {
    G.history.pop();
    $("tip").textContent = e.message;
  }
}
function undo() {
  if (!G.history.length) return;
  if (G.autoplay) {                    // taking the wheel back - stop auto-playing
    G.autoplay = false;
    $("autoplay").checked = false;
    try { localStorage.setItem("tt_autoplay", "0"); } catch (e) { /* ignore */ }
  }
  G.state = G.history.pop(); G.sel = null; G.analysis = null;
  refresh();
}

boot();
