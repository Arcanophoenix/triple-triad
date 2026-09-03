"use strict";

let CARDS = {};                       // id -> {name, sides, stars, kind, icon}
let BOOT = null;
let OWNED = new Set();                // owned card ids
let BEATEN = new Set();               // names of NPCs you have beaten
let STARTERS = new Set();             // starter card ids (always owned)
let COLDECKS = {};                    // deck name -> [card names]
let REG = null;                       // /api/regionaloverview payload (Regional tab)

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
  for (const v of ["solver", "manage", "npcs", "regional", "game"]) $("view-" + v).hidden = v !== name;
  document.querySelectorAll(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  if (name === "manage") renderManage();
  if (name === "solver") renderSolver();
  if (name === "npcs") renderNpcs();
  if (name === "regional") renderRegional();
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
  BEATEN = new Set(BOOT.beaten || []);
  STARTERS = new Set(BOOT.starterIds || []);
  COLDECKS = BOOT.collectionDecks || {};

  const nl = $("npclist");
  BOOT.npcs.slice().sort((a, b) => a.name.localeCompare(b.name)).forEach((n) => {
    const o = h("option"); o.value = n.name;
    o.label = n.rules.join(", ") || "no special rules";
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
  $("swap-go").addEventListener("click", swapConfirm);
  $("swap-cancel").addEventListener("click", () => { $("swapask").hidden = true; showView("solver"); });
  $("roulette-go").addEventListener("click", rouletteConfirm);
  $("roulette-cancel").addEventListener("click", () => { $("rouletteask").hidden = true; showView("solver"); });
  $("undo").addEventListener("click", undo);
  $("newgame").addEventListener("click", () => { resetGame(); showView("solver"); });

  try { G.autoplay = localStorage.getItem("tt_autoplay") === "1"; } catch (e) { /* private mode */ }
  $("autoplay").checked = G.autoplay;
  $("autoplay").addEventListener("change", (e) => {
    G.autoplay = e.target.checked;
    try { localStorage.setItem("tt_autoplay", G.autoplay ? "1" : "0"); } catch (er) { /* ignore */ }
    if (G.autoplay) { autoMoveIfEnabled(); autoPlayNpcFinalCard(); }  // might already be someone's turn
  });

  // manage
  $("deck-load").addEventListener("change", (e) => { if (e.target.value) loadEditDeck(e.target.value); });
  $("deck-new").addEventListener("click", () => {
    EDIT.name = ""; EDIT.ids = []; $("deck-name").value = ""; $("deck-msg").textContent = ""; renderManage();
  });
  $("card-filter").addEventListener("input", renderPicker);
  $("owned-only").addEventListener("change", renderPicker);
  $("npc-filter").addEventListener("input", renderNpcs);
  $("npc-unbeaten-only").addEventListener("change", renderNpcs);
  $("npc-import").addEventListener("change", (e) => importCollectFile(e.target.files[0]));
  $("npc-progress").addEventListener("change", (e) => setProgress(e.target.value));
  $("npc-suggest").addEventListener("click", suggestNext);
  $("save-deck").addEventListener("click", saveEditDeck);
  $("del-deck").addEventListener("click", deleteEditDeck);

  refreshDeckSelects();
  fillProgressSelect();
  renderExpFilter();
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
  }
  $("npc-info").textContent = info;
  renderRegionalInfo(n);
}

// ---------- regional rules ----------
const FIXED_REGION = "(fixed rules)";

function regionalEntry(region) {
  if (!region || region === FIXED_REGION) return null;
  return ((BOOT.regional && BOOT.regional.current) || {})[region]
      || { rules: [], date: null, stale: true };
}
function regionalRulesFor(n) {
  const e = n && regionalEntry(n.region);
  return e ? e.rules.slice() : [];
}
function combineRuleNames(match, regional) {
  const out = [], seen = new Set();
  for (const r of [...(match || []), ...(regional || [])]) {
    const k = (r || "").trim().toLowerCase();
    if (k && !seen.has(k)) { seen.add(k); out.push(r.trim()); }
  }
  return out;
}

function renderRegionalInfo(n) {
  const box = $("regional-info");
  box.innerHTML = "";
  box.classList.remove("stale");
  if (!n) return;
  if (!n.region) {
    box.textContent = `regional rules: region unknown for "${n.zone}" — not applied`;
    return;
  }
  if (n.region === FIXED_REGION) {
    box.textContent = `regional rules: none — ${n.zone} ignores them`;
    return;
  }
  const e = regionalEntry(n.region);
  const label = e.rules.length ? e.rules.join(", ") : "none set";
  const when = e.date ? ` · ${e.date}${e.stale ? " · STALE, re-check" : ""}` : "";
  box.appendChild(h("span", null, `regional (${n.region}): ${label}${when} `));
  const btn = h("button", "linklike", e.rules.length ? "edit" : "set");
  btn.type = "button";
  btn.addEventListener("click", () => editRegional(n.region));
  box.appendChild(btn);
  if (e.stale && e.rules.length) box.classList.add("stale");
}

async function editRegional(region) {
  const e = regionalEntry(region) || { rules: [] };
  const ans = prompt(
    `Regional rules for ${region}\n` +
    `Comma-separated, read off the Match Registration screen. ` +
    `Blank = None/None (no regional rules today). The Regional tab has chips + Clear.`,
    e.rules.join(", "));
  if (ans === null) return;
  try {
    BOOT.regional = await post("/api/regional", { region, rules: ans });
    refreshNpcInfo();
  } catch (err) {
    $("npc-info").textContent = "regional update failed: " + err.message;
  }
}

// ---------- regional tab ----------
const REG_WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

async function renderRegional() {
  const board = $("reg-board");
  try {
    REG = await (await fetch("/api/regionaloverview")).json();
  } catch (e) {
    board.textContent = NO_SERVER;
    return;
  }
  BOOT.regional = REG;                         // keep the Solver tab's inline view in sync
  $("reg-ruleday").textContent = `— rule-day ${REG.ruleDay}, rolls 15:00 UTC`;
  renderRegToday();
  renderRegBoard();
  renderRegPattern();
  renderRegHistory();
}

function renderRegToday() {
  const box = $("reg-today");
  box.innerHTML = "";
  const miss = (REG.today && REG.today.missing) || [];
  if (!miss.length) {
    box.textContent = "every region logged for this rule-day ✓";
    return;
  }
  box.appendChild(h("span", null, `still to check today (${miss.length}): `));
  box.appendChild(h("strong", null, miss.join(", ")));
}

function renderRegBoard() {
  const board = $("reg-board");
  board.innerHTML = "";
  for (const region of REG.regions) {
    const cur = (REG.current || {})[region] || { rules: [], date: null, stale: true };
    const row = h("div", "reg-row");

    row.appendChild(h("div", "reg-name", region));

    const rules = h("div", "reg-rules");
    if (cur.rules.length) {
      cur.rules.forEach((r) => rules.appendChild(h("span", "reg-tag", r)));
    } else if (cur.date) {
      rules.appendChild(h("span", "reg-tag empty", "None / None"));
    } else {
      rules.appendChild(h("span", "reg-unset", "not recorded"));
    }
    row.appendChild(rules);

    const when = h("div", "reg-when");
    if (cur.date) {
      when.textContent = cur.stale ? `${cur.date} · stale` : cur.date;
      if (cur.stale) when.classList.add("stale");
    }
    row.appendChild(when);

    const edit = h("div", "reg-edit");
    edit.hidden = true;
    const toggle = h("button", "linklike", "edit");
    toggle.type = "button";
    toggle.addEventListener("click", () => { edit.hidden = !edit.hidden; });
    row.appendChild(toggle);

    const picked = new Set(cur.rules);
    const chips = h("div", "reg-chips");
    (REG.vocab || []).forEach((name) => {
      const c = h("button", "reg-chip" + (picked.has(name) ? " on" : ""), name);
      c.type = "button";
      c.addEventListener("click", () => {
        if (picked.has(name)) picked.delete(name); else picked.add(name);
        c.classList.toggle("on");
      });
      chips.appendChild(c);
    });
    edit.appendChild(chips);

    const acts = h("div", "reg-acts");
    const save = h("button", "primary", "Save");
    save.type = "button";
    save.addEventListener("click", () => saveRegional(region, [...picked]));
    const none = h("button", "ghost", "None / None");
    none.type = "button";
    none.addEventListener("click", () => saveRegional(region, []));
    const clr = h("button", "ghost", "Clear");
    clr.type = "button";
    clr.addEventListener("click", () => saveRegional(region, null));
    acts.appendChild(save); acts.appendChild(none); acts.appendChild(clr);
    edit.appendChild(acts);

    row.appendChild(edit);
    board.appendChild(row);
  }
}

async function saveRegional(region, rules) {
  // rules: array to record ([] = a real None/None reading); null = forget the region
  try {
    REG = await post("/api/regional", rules === null ? { region, clear: true } : { region, rules });
    BOOT.regional = REG;
    $("reg-ruleday").textContent = `— rule-day ${REG.ruleDay}, rolls 15:00 UTC`;
    renderRegToday();
    renderRegBoard();
    renderRegPattern();
    renderRegHistory();
  } catch (err) {
    $("reg-today").textContent = "regional update failed: " + err.message;
  }
}

function renderRegPattern() {
  const box = $("reg-pattern");
  box.innerHTML = "";
  const p = REG.pattern || {};
  if (!p.observations) { box.textContent = "no observations logged yet."; return; }

  box.appendChild(h("p", "reg-sub", `${p.observations} observation(s), ${p.ruleDays} rule-day(s)`
    + (p.span ? ` (${p.span[0]} to ${p.span[1]})` : "") + `, ${p.regions} region(s)`));

  const regs = Object.keys(p.frequency || {}).sort();
  box.appendChild(h("div", "reg-sub2", "per-region rule frequency"));
  if (!regs.length) box.appendChild(h("div", "hint", "—"));
  regs.forEach((r) => {
    const fr = p.frequency[r];
    const seen = fr.counts.map(([rule, c]) => `${rule} ×${c}`).join(", ") || "(none)";
    const line = h("div", "reg-freq");
    line.appendChild(h("span", "reg-freq-name", r));
    line.appendChild(h("span", null, seen));
    if (fr.days < p.minDaysPerRegion) {
      line.appendChild(h("span", "reg-caveat", ` (only ${fr.days} day(s) — not enough to read)`));
    }
    box.appendChild(line);
  });

  const rep = p.repeat || { same: 0, total: 0 };
  box.appendChild(h("div", "reg-sub2", "does a region keep yesterday's rules?"));
  box.appendChild(h("div", null, rep.total < p.minPairs
    ? `${rep.total} back-to-back day pair(s) so far — need ${p.minPairs}+ before this means anything`
      + (rep.total ? ` (repeated ${rep.same} of ${rep.total})` : "")
    : `repeated ${rep.same}/${rep.total} = ${Math.round(100 * rep.same / rep.total)}% of the time`));

  const xr = p.crossRegion || { same: 0, total: 0 };
  box.appendChild(h("div", "reg-sub2", "do two regions roll the same rules on the same day?"));
  box.appendChild(h("div", null, !xr.total
    ? "never logged two regions on one day — do that to test it"
    : `matched ${xr.same}/${xr.total} region pair(s) compared`
      + (xr.same === 0 ? "  (if this stays 0, each region rolls independently)" : "")));

  box.appendChild(h("div", "reg-sub2", "by weekday"));
  let anyWd = false;
  REG_WD.forEach((name, i) => {
    const c = (p.weekday && p.weekday[String(i)]) || [];
    if (!c.length) return;
    anyWd = true;
    box.appendChild(h("div", null, `${name}  ` + c.map(([r, n]) => `${r} ×${n}`).join(", ")));
  });
  if (!anyWd) box.appendChild(h("div", "hint", "—"));

  const thin = regs.filter((r) => p.frequency[r].days < p.minDaysPerRegion);
  if (thin.length) {
    box.appendChild(h("p", "reg-caveat", `note: ${thin.length} region(s) still under `
      + `${p.minDaysPerRegion} logged days. Frequencies above are indicative only — with a `
      + `handful of samples any ruleset can look 'favoured' by chance.`));
  }
}

function renderRegHistory() {
  const box = $("reg-history");
  box.innerHTML = "";
  const rows = (REG.history || []).slice().reverse();
  if (!rows.length) { box.textContent = "no observations logged yet."; return; }
  rows.forEach((rec) => {
    const line = h("div", "reg-hrow");
    line.appendChild(h("span", "reg-hday", `${rec.day} ${rec.weekday}`));
    line.appendChild(h("span", "reg-hreg", rec.region));
    line.appendChild(h("span", null, rec.rules.join(", ") || "(none)"));
    box.appendChild(line);
  });
}

function npcPayload() {
  return {
    npc: $("npc").value.trim(),
    rules: $("rules").value.trim() ? $("rules").value.split(",").map((s) => s.trim()) : null,
    npcCards: null,        // every roster NPC has a recorded deck now
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
  const ordered = (r.rules || []).some((x) => x.toLowerCase() === "order");
  if (ordered) {
    out.appendChild(h("div", "hint", "Order rule — the numbers are the play sequence; set your in-game deck in exactly this left-to-right order."));
  }
  const status = h("div", "hint");
  r.results.forEach((res) => {
    const row = h("div", "rec-row");
    row.appendChild(h("span", "rec-cards", ordered
      ? res.cards.map((n, i) => `${i + 1}. ${short(n)}`).join("   ")
      : res.cards.map(short).join(", ")));
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

// effective rule names for the pending match: the override field wins, else the NPC's
function activeRuleNames() {
  const ov = $("rules").value.trim();
  if (ov) return ov.split(",").map((s) => s.trim()).filter(Boolean);
  const n = npcByName($("npc").value);
  return n ? combineRuleNames(n.rules, regionalRulesFor(n)) : [];
}
const ruleHas = (names, rule) => (names || []).some((r) => r.toLowerCase() === rule);
const rulesHaveSwap = (names) => ruleHas(names, "swap");
const rulesHaveRoulette = (names) => ruleHas(names, "roulette");

// rules Roulette can roll (Same Wall is a Same sub-toggle; Combo is always on)
const RULE_CHOICES = [
  "All Open", "Three Open", "Same", "Plus", "Reverse", "Fallen Ace",
  "Ascension", "Descension", "Order", "Chaos", "Swap", "Sudden Death",
];

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
    baseRules: activeRuleNames(),   // pre-Roulette rule list, so a replay re-rolls
  };
  if (rulesHaveRoulette(G.pendingCfg.baseRules)) { openRouletteAsk(); return; }
  if (rulesHaveSwap(G.pendingCfg.baseRules)) { openSwapAsk(); return; }
  launchMatch($("setup-err"));
}

async function launchMatch(errBox) {
  try {
    const r = await post("/api/newgame", G.pendingCfg);
    $("swapask").hidden = true;
    $("rouletteask").hidden = true;
    enterGame(r);
  } catch (e) { errBox.textContent = e.message; }
}

// Roulette: tick the rules the game rolled, then launch (chaining to Swap if it rolled one).
function openRouletteAsk() {
  const fixed = (G.pendingCfg.baseRules || []).filter((r) => r.toLowerCase() !== "roulette");
  const grid = $("rule-grid");
  grid.innerHTML = "";
  for (const rule of RULE_CHOICES) {
    const locked = fixed.some((f) => f.toLowerCase() === rule.toLowerCase());
    const lab = h("label", "rule-box" + (locked ? " fixed" : ""));
    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.value = rule; cb.checked = locked; cb.disabled = locked;
    lab.append(cb, h("span", null, rule));
    grid.appendChild(lab);
  }
  const n = npcByName(G.pendingCfg.npc || G.npc);
  $("roulette-npcname").textContent = (n && n.name) || (G.pendingCfg.npc || "this NPC");
  $("roulette-err").textContent = "";
  showView("game");
  $("rouletteask").hidden = false;
}

function rouletteConfirm() {
  const picked = [...$("rule-grid").querySelectorAll("input:checked")].map((c) => c.value);
  G.pendingCfg = { ...G.pendingCfg, rules: picked };
  $("rouletteask").hidden = true;
  if (rulesHaveSwap(picked)) { openSwapAsk(); return; }   // Roulette rolled Swap -> chain
  launchMatch($("roulette-err"));
}

// Swap: pick the two traded cards from card art, then launch with swapOut/swapIn.
let SWAP_OUT = null;   // card id you gave the NPC
let SWAP_IN = null;    // card id you received

// every card the NPC could hold: their recorded fixed+pool, else the 5 you typed
function swapInCandidates() {
  const n = npcByName(G.pendingCfg.npc || G.npc);
  const d = n ? (BOOT.decks[n.name] || null) : null;
  if (d) return namesToIds([...(d.fixed || d.cards || []), ...(d.pool || [])]);
  return namesToIds(G.pendingCfg.npcCards || []);
}

function swapTile(id, selectedId, onPick) {
  const t = h("div", "swap-tile" + (id === selectedId ? " sel" : ""));
  const art = h("div", "swap-tile-art");
  art.appendChild(miniCard(id));
  t.append(art, h("div", "swap-tile-name", short(CARDS[id].name)));
  t.title = CARDS[id].name;
  t.addEventListener("click", () => onPick(id));
  return t;
}

function renderSwapGrids() {
  const og = $("swap-out-grid"); og.innerHTML = "";
  namesToIds(G.pendingCfg.deck || []).forEach((id) =>
    og.appendChild(swapTile(id, SWAP_OUT, (x) => { SWAP_OUT = x; renderSwapGrids(); })));
  const ig = $("swap-in-grid"); ig.innerHTML = "";
  const cands = swapInCandidates();
  if (!cands.length) {
    ig.appendChild(h("div", "swapask-sub", "record this NPC's deck (or type their 5 cards) to pick here"));
  }
  cands.forEach((id) =>
    ig.appendChild(swapTile(id, SWAP_IN, (x) => { SWAP_IN = x; renderSwapGrids(); })));
}

function openSwapAsk() {
  SWAP_OUT = null; SWAP_IN = null;
  const n = npcByName(G.pendingCfg.npc || G.npc);
  $("swap-npcname").textContent = (n && n.name) || (G.pendingCfg.npc || "the NPC");
  $("swap-err").textContent = "";
  renderSwapGrids();
  showView("game");
  $("swapask").hidden = false;
}

async function swapConfirm() {
  if (SWAP_OUT == null) { $("swap-err").textContent = "pick the card you gave up"; return; }
  if (SWAP_IN == null) { $("swap-err").textContent = "pick the card you received"; return; }
  G.pendingCfg = { ...G.pendingCfg, swapOut: CARDS[SWAP_OUT].name, swapIn: CARDS[SWAP_IN].name };
  launchMatch($("swap-err"));
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
  $("swapask").hidden = true;
  $("rouletteask").hidden = true;
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

// won the match — record the NPC as beaten (same list the NPCs tab / import fill)
async function markBeaten(btn) {
  if (btn) btn.disabled = true;
  try {
    const r = await post("/api/setbeaten", { npc: G.npc, beaten: true });
    BEATEN = new Set(r.beaten || []);
  } catch (e) {
    if (btn) { btn.disabled = false; btn.textContent = e.message; }
    return;
  }
  renderPostMatch();
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
  delete G.pendingCfg.swapOut;
  delete G.pendingCfg.swapIn;
  const base = G.pendingCfg.baseRules || activeRuleNames();
  if (rulesHaveRoulette(base)) { delete G.pendingCfg.rules; openRouletteAsk(); return; }
  if (rulesHaveSwap(base)) { openSwapAsk(); return; }
  launchMatch($("tip"));
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

  if (res === "win" && G.npc) {
    const bt = h("div", "pm-beaten");
    if (BEATEN.has(G.npc)) {
      bt.appendChild(h("span", "pm-beaten-on", `✓ ${G.npc} is marked as beaten`));
    } else {
      const b = h("button", "ghost", `Mark ${G.npc} as beaten`);
      b.addEventListener("click", () => markBeaten(b));
      bt.appendChild(b);
    }
    box.appendChild(bt);
  }

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
function cardTile(id) {
  const c = CARDS[id];
  const owned = OWNED.has(id);
  const t = h("div", "ctile" + (owned ? " owned" : "") + (EDIT.ids.includes(id) ? " in" : ""));
  t.title = `${short(c.name)} — ${c.sides.map(face).join("/")}` + (owned ? "" : "  (not owned)");

  const art = h("div", "mini");
  art.style.backgroundImage = `url(/card/${id}.png)`;
  art.appendChild(h("span", "num n-n", face(c.sides[0])));
  art.appendChild(h("span", "num n-e", face(c.sides[1])));
  art.appendChild(h("span", "num n-s", face(c.sides[2])));
  art.appendChild(h("span", "num n-w", face(c.sides[3])));
  t.appendChild(art);

  const own = h("input"); own.type = "checkbox"; own.className = "ctile-own"; own.checked = owned;
  if (STARTERS.has(id)) { own.disabled = true; own.title = "starter card — always owned"; }
  else own.title = "you own this card";
  own.addEventListener("click", (e) => e.stopPropagation());
  own.addEventListener("change", () => setOwned(id, own.checked));
  t.appendChild(own);

  t.appendChild(h("span", "ctile-stars", "★".repeat(c.stars)));
  t.appendChild(h("span", "ctile-name", short(c.name)));

  t.addEventListener("click", () => {
    const at = EDIT.ids.indexOf(id);
    if (at >= 0) EDIT.ids.splice(at, 1);
    else if (EDIT.ids.length < 5) EDIT.ids.push(id);
    renderManage();
  });
  return t;
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
    pick.appendChild(cardTile(id));
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
// Ascension / Descension modifier for any card of faction `kind`, given the
// current board: +N (Ascension) / -N (Descension), N = cards of that faction on
// the board. Applies to board cards (self-counted, they're on the board) and to
// hand cards alike (the rule hits cards in hand too) - the real game shows both.
function factionDelta(kind) {
  if (!kind || kind === "None" || !G.state) return 0;
  const rules = G.state.rules || [];
  const asc = rules.includes("Ascension");
  if (!asc && !rules.includes("Descension")) return 0;
  let n = 0;
  for (const s of G.state.board) if (s && CARDS[s.card].kind === kind) n++;
  return asc ? n : -n;
}

function cardEl(id, owner, delta) {
  const c = CARDS[id];
  const e = h("div", "card owner-" + owner);
  e.style.backgroundImage = `url(/card/${id}.png)`;
  if (delta) {
    e.appendChild(h("span", "asc-badge" + (delta < 0 ? " desc" : ""),
      (delta > 0 ? "+" : "") + delta));
    const capped = c.sides.map((v) => Math.max(1, Math.min(10, v + delta)));
    e.title = `${c.name} — ${c.sides.map(face).join("/")} → ${capped.map(face).join("/")}`;
  }
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
      slot.appendChild(cardEl(id, side, factionDelta(CARDS[id].kind)));
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
    if (s.board[i]) cell.appendChild(cardEl(s.board[i].card, s.board[i].owner, factionDelta(CARDS[s.board[i].card].kind)));
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
    autoPlayNpcFinalCard();
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

// the NPC's very last card is a forced move - one card, one empty cell, no
// choice. With auto-play on, place it for them so a solved match finishes
// without a pointless click. Only when the card is known: named outright, or
// the sole remaining pool card (determined by elimination).
function autoPlayNpcFinalCard() {
  const s = G.state;
  if (!G.autoplay || !s || s.terminal || s.to_move !== 1) return;
  let cell = -1, empties = 0;
  for (let i = 0; i < 9; i++) if (s.board[i] == null) { cell = i; empties++; }
  if (empties !== 1 || s.hands[1].length !== 1) return;
  let card = s.hands[1][0];
  if (card == null) {
    const pool = s.npcPool || [];
    if (pool.length !== 1) return;            // still ambiguous - the human names it
    card = pool[0];
  }
  $("tip").textContent = "playing the NPC's forced last card…";
  setTimeout(() => finishNpcFinalCard(s, card, cell), AUTOPLAY_DELAY);
}

async function finishNpcFinalCard(at, card, cell) {
  if (!G.autoplay || G.state !== at || at.terminal || at.to_move !== 1) return;
  let base = at, pushed = false;
  try {
    if (at.hands[1][0] == null) {             // name the elimination-known card first
      const rv = await post("/api/reveal", { state: at, card });
      if (!G.autoplay || G.state !== at) return;
      G.state = base = rv.state;
    }
    G.history.push(base); pushed = true;
    const r = await post("/api/apply", { state: base, card, cell });
    if (G.state !== base) { G.history.pop(); return; }   // superseded (undo, new game, manual entry)
    G.state = r.state; G.sel = null; G.analysis = null;
    await refresh();
  } catch (e) {
    if (pushed && G.history[G.history.length - 1] === base) G.history.pop();
    $("tip").textContent = "couldn't place the NPC's last card: " + e.message;
  }
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


// ---------- NPCs tab: who you have beaten, and who to take on next ----------

// FF expansions, oldest first, with the leading major patch number.  Kept in
// sync with tt/progress.py EXPANSIONS - the server sends the list in `boot`.
const EXP_ORDER = ["ARR", "HW", "SB", "ShB", "EW", "DT"];
const EXP_LABEL = {
  ARR: "A Realm Reborn", HW: "Heavensward", SB: "Stormblood",
  ShB: "Shadowbringers", EW: "Endwalker", DT: "Dawntrail",
};
let EXP_FILTER = new Set();            // selected expansions; empty = show all

function fillProgressSelect() {
  const sel = $("npc-progress");
  const cur = (BOOT.progress && BOOT.progress.expansion) || "";
  sel.innerHTML = "";
  const none = h("option"); none.value = ""; none.textContent = "not set"; sel.appendChild(none);
  for (const e of (BOOT.expansions || EXP_ORDER)) {
    const o = h("option"); o.value = e;
    o.textContent = `finished ${EXP_LABEL[e] || e}`;
    sel.appendChild(o);
  }
  sel.value = cur;
}

function renderExpFilter() {
  const box = $("exp-filter");
  box.innerHTML = "";
  const reached = (BOOT.progress && BOOT.progress.expansion) || null;
  const reachIdx = reached ? EXP_ORDER.indexOf(reached) : EXP_ORDER.length - 1;
  for (const [i, e] of EXP_ORDER.entries()) {
    const chip = h("button", "exp-chip" + (EXP_FILTER.has(e) ? " on" : ""), e);
    chip.type = "button";
    chip.title = EXP_LABEL[e] + (i > reachIdx && reached ? " (not reached yet)" : "");
    chip.dataset.exp = e;
    if (i > reachIdx && reached) chip.classList.add("locked");
    chip.addEventListener("click", () => {
      EXP_FILTER.has(e) ? EXP_FILTER.delete(e) : EXP_FILTER.add(e);
      renderExpFilter();
      renderNpcs();
    });
    box.appendChild(chip);
  }
  if (EXP_FILTER.size) {
    const clear = h("button", "exp-chip clear", "clear");
    clear.type = "button";
    clear.addEventListener("click", () => { EXP_FILTER.clear(); renderExpFilter(); renderNpcs(); });
    box.appendChild(clear);
  }
}

function npcRow(n) {
  const beaten = BEATEN.has(n.name);
  const row = h("div", "pick-row");
  if (beaten) row.classList.add("in");
  const box = h("input"); box.type = "checkbox"; box.className = "own"; box.checked = beaten;
  box.addEventListener("click", (e) => e.stopPropagation());
  box.addEventListener("change", () => setBeaten(n.name, box.checked));
  row.appendChild(box);
  row.appendChild(h("span", "pk-name", n.name));
  if (n.expansion) row.appendChild(h("span", "exp-tag exp-" + n.expansion, n.expansion));
  row.appendChild(h("span", "pk-sides", n.zone));
  row.appendChild(h("span", "pk-stars", (n.rules || []).join(", ") || "-"));
  row.appendChild(h("span", "pk-sides", n.mgp ? `${n.mgp} MGP` : ""));
  row.addEventListener("click", () => {           // row (not the box) -> solver, targeting them
    $("npc").value = n.name;
    showView("solver");
    renderSolver();
  });
  return row;
}

function renderNpcs() {
  const q = $("npc-filter").value.toLowerCase().trim();
  const unbeatenOnly = $("npc-unbeaten-only").checked;
  const list = BOOT.npcs || [];
  $("npc-count").textContent = `${BEATEN.size}/${list.length} beaten`;

  const box = $("npc-picker");
  const keepScroll = box.scrollTop;
  box.innerHTML = "";
  let shown = 0;
  for (const n of [...list].sort((a, b) => (a.mgp || 0) - (b.mgp || 0) || a.name.localeCompare(b.name))) {
    if (unbeatenOnly && BEATEN.has(n.name)) continue;
    if (EXP_FILTER.size && !EXP_FILTER.has(n.expansion)) continue;
    const hay = `${n.name} ${n.zone} ${(n.rules || []).join(" ")}`.toLowerCase();
    if (q && !hay.includes(q)) continue;
    shown++;
    box.appendChild(npcRow(n));
  }
  if (!shown) box.appendChild(h("div", "pick-more", "no NPCs match that filter"));
  box.scrollTop = keepScroll;
}

async function setBeaten(name, beaten) {
  try {
    const r = await post("/api/setbeaten", { npc: name, beaten });
    BEATEN = new Set(r.beaten || []);
    $("npc-msg").textContent = "";
  } catch (e) {
    $("npc-msg").textContent = e.message;
  }
  renderNpcs();
}

async function setProgress(value) {
  try {
    const r = await post("/api/setprogress", { progress: value || null });
    BOOT.progress = { value: r.value, label: r.label, expansion: r.expansion };
    $("npc-import-msg").textContent = value ? `progress: ${r.label}` : "progress cleared";
    renderExpFilter();
    renderNpcs();
  } catch (e) {
    $("npc-import-msg").textContent = e.message;
  }
}

function importCollectFile(file) {
  if (!file) return;
  const msg = $("npc-import-msg");
  msg.textContent = `reading ${file.name}…`;
  const reader = new FileReader();
  reader.onerror = () => { msg.textContent = "couldn't read that file"; };
  reader.onload = async () => {
    let data;
    try {
      data = JSON.parse(reader.result);
    } catch (e) {
      msg.textContent = "that file isn't valid JSON — is it the Collect export?";
      return;
    }
    try {
      const r = await post("/api/import", { export: data });
      OWNED = new Set(r.ownedIds || []);
      BEATEN = new Set(r.beaten || []);
      const bits = [`+${r.cards_added.length} card(s)`, `+${r.npcs_added.length} beaten NPC(s)`];
      if ((r.unknown_card_ids || []).length) bits.push(`${r.unknown_card_ids.length} card id(s) unmatched`);
      if ((r.unknown_npc_ids || []).length) bits.push(`${r.unknown_npc_ids.length} NPC id(s) unmatched`);
      msg.textContent = "imported: " + bits.join(", ");
      renderNpcs();
      renderPicker();
    } catch (e) {
      msg.textContent = e.message;
    }
  };
  reader.readAsText(file);
  $("npc-import").value = "";        // let the same file be re-picked later
}

const SUGGEST_BUCKET = {
  win:     { txt: "winnable",       cls: "sg-win" },
  likely:  { txt: "likely win",    cls: "sg-likely" },
  close:   { txt: "close",         cls: "sg-close" },
  notyet:  { txt: "not yet",       cls: "sg-notyet" },
  unknown: { txt: "no read",       cls: "sg-unknown" },
};

async function suggestNext() {
  const btn = $("npc-suggest");
  const out = $("npc-suggest-out");
  btn.disabled = true;
  out.innerHTML = "";
  out.appendChild(h("div", "pick-more", "screening the matchups, then re-checking the close ones…"));
  try {
    const r = await post("/api/suggest", { limit: 12 });
    out.innerHTML = "";
    if (!r.suggestions.length) {
      out.appendChild(h("div", "pick-more",
        BOOT.progress && BOOT.progress.value
          ? "nothing unbeaten and reachable — set progress further, or you've cleared them"
          : "every recorded NPC is already ticked as beaten"));
    }
    const prog = r.progress && r.progress.value ? `, reachable given ${r.progress.label}` : "";
    const rc = r.rechecked ? `; ${r.rechecked} re-checked exactly` : "";
    if (r.suggestions.length) out.appendChild(h("div", "pick-more",
      `best of ${r.consideredOf} unbeaten NPC(s)${prog}${rc}. `
      + `“screen” margins run ~4 low and never high — a small negative is usually `
      + `still a win; Chaos/Swap stay on the screen value (too slow to solve live).`));
    for (const s of r.suggestions) {
      const row = h("div", "pick-row");
      const b = SUGGEST_BUCKET[s.bucket] || SUGGEST_BUCKET.unknown;
      const num = s.edge == null ? ""
        : ` ${fmt(s.edge)}${s.edgeKind === "screen" ? " screen" : ""}`;
      row.appendChild(h("span", "pk-name", s.name));
      if (s.expansion) row.appendChild(h("span", "exp-tag exp-" + s.expansion, s.expansion));
      row.appendChild(h("span", "pk-sides", s.zone));
      row.appendChild(h("span", "pk-stars " + b.cls, b.txt + num));
      row.appendChild(h("span", "pk-sides", s.mgp ? `${s.mgp} MGP` : ""));
      row.addEventListener("click", () => { $("npc").value = s.name; showView("solver"); renderSolver(); });
      out.appendChild(row);
    }
  } catch (e) {
    out.innerHTML = "";
    out.appendChild(h("div", "pick-more", e.message));
  } finally {
    btn.disabled = false;
  }
}
