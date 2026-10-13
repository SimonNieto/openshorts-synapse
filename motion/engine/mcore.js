// Noyau du moteur « motion seul », v2b (13/10/2026, lot 2 de SPEC_V2) : outils, calage sur les mots, courbes, la grille
// du 9:16 selon le style de sous-titres du clip, et les primitives finies (designer direction_v2 V2-4, V2-7, V2-8).
// Repris du lot 1 (v2a) : le battement POSE · COMPTE · FRAPPE · TENUE (scénariste dramaturgie_v2 §2).
// Nouveau au lot 2 :
//   - la SCÈNE dépend de SPEC.cap (« oneword » : la scène s'arrête à 977 et un PLANCHER hors caméra reçoit UN élément,
//     le chiffre dit, sinon le verdict ; « premium » : la scène descend à 1153, pas de plancher) ; la bande HAUT-GAUCHE ;
//   - la TUILE (84 px, 64 px, puis 2 lignes) remplace la gélule ; plus aucun texte ambre ; une entrée par sorte
//     d'élément (tuile : le texte monte dans sa fenêtre ; héros et chiffre : la frappe ; cachet : un tampon) ;
//   - la COLONNE (verticale, volume, part perdue, repère de l'état d'avant) remplace les barres ; le MÉDAILLON remplace
//     la station ; voie, comète, anneau, barrage, balance, bulle et filets aux valeurs du designer (V2-8) ;
//   - l'anti-écho, derrière SPEC.anti_echo (éteint par défaut : la charte §2 ne change pas sans elle) : la forme se
//     cale sur le mot, et son texte se pose quand le sous-titre le quitte.
// Tout est fonction pure du temps (charte §6 bis) : aucune horloge, aucun hasard sans graine.
const $ = id => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const mk = (parent, tag, attrs = {}) => { const e = document.createElementNS(NS, tag); for (const k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };
const set = (e, attrs) => { for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
const hex = c => [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16));
const mix = (a, b, k) => { const A = hex(a), B = hex(b); k = clamp(k);
  return '#' + A.map((v, i) => Math.round(v + (B[i] - v) * k).toString(16).padStart(2, '0')).join(''); };
const rnd = s => { const x = Math.sin(s * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };

// ---- the curves (designer V2-11). Pure functions of progress x in [0, 1].
function bezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx, cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const fx = t => ((ax * t + bx) * t + cx) * t, fy = t => ((ay * t + by) * t + cy) * t, dx = t => (3 * ax * t + 2 * bx) * t + cx;
  return x => { x = clamp(x); if (x === 0 || x === 1) return x; let t = x;
    for (let i = 0; i < 8; i++) { const d = fx(t) - x; if (Math.abs(d) < 1e-5) break; const s = dx(t); if (Math.abs(s) < 1e-6) break; t -= d / s; }
    return fy(clamp(t)); }; }
const eIn = bezier(.2, 0, 0, 1), eOut = bezier(.3, 0, 1, 1);
const eSine = x => -(Math.cos(Math.PI * clamp(x)) - 1) / 2;
const eOver = x => { x = clamp(x); const c1 = .6, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };
const p3o = x => 1 - Math.pow(1 - clamp(x), 3);
const x4o = x => (x = clamp(x)) === 1 ? 1 : 1 - Math.pow(2, -10 * x);
const p2i = x => clamp(x) * clamp(x);
function spring(z, resp) {            // the closed form of a damped spring (skill hyperframes-animation, springEase)
  const w = 2 * Math.PI / resp;
  let pos;
  if (z < 1) { const wd = w * Math.sqrt(1 - z * z); pos = t => 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + (z * w / wd) * Math.sin(wd * t)); }
  else if (z > 1) { const wo = w * Math.sqrt(z * z - 1); pos = t => 1 - Math.exp(-z * w * t) * (Math.cosh(wo * t) + (z * w / wo) * Math.sinh(wo * t)); }
  else pos = t => 1 - Math.exp(-w * t) * (1 + w * t);
  const rate = z <= 1 ? z * w : (z - Math.sqrt(z * z - 1)) * w, SCAN = 12 / rate, N = 4800; let Tset = SCAN;
  for (let i = N; i >= 0; i--) { const t = i / N * SCAN; if (Math.abs(1 - pos(t)) > .001) { Tset = (i + 1) / N * SCAN; break; } }
  const xT = pos(Tset);
  return { dur: Tset, f: x => { x = clamp(x); return pos(x * Tset) + x * (1 - xT); } };
}
const SPR_HERO = spring(1, .45), SPR_BAL = spring(.8, .5);
const FAST = .18, STD = .30, SLOW = .60, HIT = .067, GHOST = .35;
const skel = t => GHOST + (1 - GHOST) * p3o(t / .30);

// ---- the colours (one colour = one meaning), charte §4 + the designer's derived tints (§3.1)
const C = { abyss: '#0B1226', nuit: '#141E37', crep: '#22305A', ardoise: '#3A4A7A', brume: '#8796C8', os: '#F4EDE0',
  ambre: '#FFB43F', coeur: '#FFF1CF', corail: '#FF6A4D', osHaut: '#F7F1E6', osOmbre: '#E2D7C3', bleuLum: '#1A2750', cadran: '#1A2547' };

// ---- words: SPEC roles carry word numbers {i}; WORDS = [{i, w, t, e}] in shot seconds, snapped on the heard voice
const S = window.SPEC, D = S.D || 5, R = S.roles || {};
const WORDS = window.WORDS || [];
const T = r => { if (r === null || r === undefined) return 99; const i = typeof r === 'object' ? r.i : r;
  const w = WORDS.find(x => x.i === i); return w ? w.t : 99; };
const TE = r => { const i = typeof r === 'object' ? r.i : r; const w = WORDS.find(x => x.i === i); return w ? w.e : 99; };
const L = r => (r && r.label ? String(r.label).toUpperCase() : '');
const FOCUS_W = S.focus ? T(S.focus) : 99;
const focusAt = d => FOCUS_W < 99 ? FOCUS_W - HIT : (d < 99 ? d - HIT : D * .6);
const atLabel = r => { if (!r) return 99; const t = T(r); if (!S.focus || typeof r !== 'object' || !r.label) return t;
  const n = String(r.label).trim().split(/\s+/).length, fi = S.focus.i;
  return fi >= r.i && fi <= r.i + n ? Math.max(t, FOCUS_W) : t; };
// THE ANTI-ECHO (V2-7.3, behind SPEC.anti_echo): the text of a label comes out when the caption leaves its words:
// max(end of its last word, end of the caption block that holds it) + 0,03 s. TL(role) = the time handed to show()
// (which comes out at that time − 0,10 s). Without the flag: on the word, as in the charter §2.
const AE = !!S.anti_echo, CAPCH = window.CAPCHUNKS || [];
const nw = s => String(s || '').toUpperCase().replace(/[^A-Z0-9%]/g, '');
const TL = (r, t) => { if (t === undefined) t = atLabel(r); if (!AE || !r || typeof r !== 'object' || t >= 99) return t;
  // the label's spoken span: from its word to the last spoken word that is one of its words (« TIME TO EXHAUSTION » is
  // said « time to physical exhaustion »: the span runs to « exhaustion »)
  const lt = String(r.label || '').toUpperCase().split(/[^A-Z0-9%']+/).map(nw).filter(Boolean);
  let j = r.i; for (let k = r.i; k <= r.i + lt.length + 3; k++) { const w = WORDS.find(x => x.i === k); if (w && lt.includes(nw(w.w))) j = k; }
  const ids = [...Array(j - r.i + 1)].map((_, k) => r.i + k);
  let end = Math.max(t - .1, ...ids.map(i => TE(i)).filter(x => x < 99));
  for (const [s, e, is] of CAPCH) if (is.some(i => ids.includes(i))) end = Math.max(end, e);
  return Math.max(t, end + .03 + .1); };
const LATE = D - .8;
const FRAPPES = [];

// ---- THE GRID (designer §3.2, V2-4), from the clip's caption style
const CAP = S.cap || { style: 'oneword', top: 1014, bottom: 1214 };
const PREMIUM = CAP.top > 1100;
const SCENE = [131, 306, 949, PREMIUM ? Math.floor(640 + (CAP.top - 16 - 640) / 1.06) : 977];
const HG = [131, 155, 657, 306];                 // top-left, beside the channel cartouche: the top of a column or a rail
const COLS = [131, 155, 657, SCENE[3]];          // the left band, scene + HG
const FLOOR = PREMIUM ? null : [100, CAP.bottom + 30, 900, 1516];        // ONE element, outside the camera
const FLOORSPOT = FLOOR ? { layer: 'plancher', box: FLOOR, size: 300, hero: 150 }
                        : { layer: 'labels', box: [131, 992, 917, SCENE[3]], size: 170, hero: 140 };
const inside = (b, Z) => b[0] >= Z[0] - .5 && b[1] >= Z[1] - .5 && b[2] <= Z[2] + .5 && b[3] <= Z[3] + .5;
// below y 980 (before the camera) the Shorts buttons start at x 940 once pushed ×1,06: the right edge stays ≤ 912
const LOW = 980, RIGHT_LOW = 912;
const fits = b => (inside(b, SCENE) || inside(b, COLS)) && (b[3] <= LOW || b[2] <= RIGHT_LOW);
const hit = (a, b, pad = 16) => a[0] < b[2] + pad && a[2] > b[0] - pad && a[1] < b[3] + pad && a[3] > b[1] - pad;
const grow = (b, k) => { const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2, hw = (b[2] - b[0]) / 2 * k, hh = (b[3] - b[1]) / 2 * k;
  return [cx - hw, cy - hh, cx + hw, cy + hh]; };
const union = bs => bs.filter(Boolean).reduce((u, b) => u ? [Math.min(u[0], b[0]), Math.min(u[1], b[1]), Math.max(u[2], b[2]), Math.max(u[3], b[3])] : b.slice(), null);
// the largest frappe scale (≤ 1,25) that keeps a box centred on (x, y) inside its zone: safe by construction
const kFit = (b, x, y, Z = SCENE) => { const hw = (b[2] - b[0]) / 2, hh = (b[3] - b[1]) / 2;
  return clamp(Math.min(1.25, (x - Z[0]) / hw, (Z[2] - x) / hw, (y - Z[1]) / hh, (Z[3] - y) / hh), 1, 1.25); };
let NID = 0;
function blurFilter(b) {
  const id = 'fb' + (NID++), m = 60, f = mk($('defs'), 'filter', { id, filterUnits: 'userSpaceOnUse', x: b[0] - m, y: b[1] - m, width: b[2] - b[0] + 2 * m, height: b[3] - b[1] + 2 * m });
  return { id, g: mk(f, 'feGaussianBlur', { stdDeviation: 0 }) }; }
function strike(g, t, t1, k, x, y, bl) {          // THE FRAPPE of a text: ×k → 1, blur 8 → 0, 0,35 s x4o
  if (t < t1) { set(g, { opacity: 0 }); g.removeAttribute('filter'); return 0; }
  const q = x4o((t - t1) / .35), s = k - (k - 1) * q, b = 8 * (1 - q);
  set(g, { opacity: q, transform: `translate(${x} ${y}) scale(${s}) translate(${-x} ${-y})` });
  if (b > .05) { g.setAttribute('filter', `url(#${bl.id})`); bl.g.setAttribute('stdDeviation', b.toFixed(2)); } else g.removeAttribute('filter');
  return q; }
const layerOf = o => $(o.layer || 'labels');

// ---- TUILE (V2-7.1): a spoken name. 84 px, then 64 px, then 2 lines (cut at a space); never shortened.
// Active: Crépuscule, outline Os 0,9, text Os. Passed: Nuit 0,94, outline Ardoise, text Brume. Never an amber text.
// Entrance: the text rises 36 px inside the tile's window (0,30 s p3o) while the tile opens ×0,92 → 1 (0,24 s).
function tuile(text, x, y, o = {}) {
  const g = mk(layerOf(o), 'g', { class: 'chk txt tuile', opacity: 0 });
  if (o.hote) g.setAttribute('data-hote', o.hote);
  const id = 'tc' + (NID++);
  const bg = mk(g, 'rect', { rx: 22, fill: C.crep, stroke: C.os, 'stroke-opacity': .9, 'stroke-width': 4 });
  const cp = mk(mk(g, 'defs'), 'clipPath', { id }); const cr = mk(cp, 'rect', { rx: 22 });
  const inner = mk(g, 'g', { 'clip-path': `url(#${id})` }), mover = mk(inner, 'g');
  const tx = mk(mover, 'text', { fill: C.os, 'text-anchor': 'middle' });
  const maxw = o.maxw || (SCENE[2] - SCENE[0]);
  let size = o.size0 || 84, lines = [text];
  if (o.font) tx.style.fontFamily = o.font;            // a style: the page's CSS (text { font-family: Mont }) beats an SVG attribute
  const measure = () => { tx.textContent = ''; lines.forEach((ln, k) => { const sp = mk(tx, 'tspan', { x: 0, dy: k ? size * 1.08 : 0 }); sp.textContent = ln; });
    return Math.max(...[...tx.children].map(c => c.getComputedTextLength())); };
  const style = () => set(tx, { 'font-size': size, 'letter-spacing': (-.01 * size).toFixed(2) });
  style(); let tw = measure();
  if (tw + .68 * size > maxw) { size = Math.min(size, 64); style(); tw = measure(); }
  // 2 lines, cut at a space or after a hyphen (PROBLEM- / SOLVING): a word is never shortened
  const cuts = []; for (let k = 1; k < text.length; k++) { if (text[k] === ' ') cuts.push([text.slice(0, k), text.slice(k + 1)]); if (text[k - 1] === '-' && k > 1) cuts.push([text.slice(0, k), text.slice(k)]); }
  if (tw + .68 * size > maxw && cuts.length) { let best = null;
    for (const c of cuts) { lines = c; const w2 = measure(); if (!best || w2 < best[0]) best = [w2, c]; }
    lines = best[1]; tw = measure(); }
  // a single word still too wide (TESTOSTERONE beside a column): smaller, never shortened, never slid onto a shape
  while (tw + .68 * size > maxw && size > 48) { size -= 4; style(); tw = measure(); }
  const w = tw + .68 * size, h = 1.32 * size + (lines.length - 1) * size * 1.08;
  const cx = o.anchor === 'start' ? x + w / 2 : o.anchor === 'end' ? x - w / 2 : x;
  set(bg, { x: cx - w / 2, y: y - h / 2, width: w, height: h }); set(cr, { x: cx - w / 2, y: y - h / 2, width: w, height: h });
  [...tx.children].forEach(c => c.setAttribute('x', cx));
  set(tx, { x: cx, y: y - h / 2 + .31 * size + .72 * size });
  Object.assign(g, { text, size, lines: lines.length, cx, cy: y, w, h, box: [cx - w / 2, y - h / 2, cx + w / 2, y + h / 2] });
  g.show = (t, at, end = 99) => { const t1 = at - .1 > LATE ? 99 : at - .1;
    if (t < t1) { g.setAttribute('opacity', 0); return; }
    const pb = p3o((t - t1) / .24), pt = p3o((t - t1) / .30), past = eIn((t - end) / FAST);
    set(g, { opacity: clamp((t - t1) / .08), transform: `translate(${cx} ${y}) scale(${.92 + .08 * pb}) translate(${-cx} ${-y})` });
    mover.setAttribute('transform', `translate(0 ${(36 * (1 - pt)).toFixed(2)})`);
    set(bg, { fill: mix(C.crep, C.nuit, past), 'fill-opacity': 1 - .06 * past, stroke: mix(C.os, C.ardoise, past), 'stroke-opacity': .9 + .1 * past });
    tx.setAttribute('fill', mix(C.os, C.brume, past)); };
  return g;
}
// a tile inside the scene: kept inside the scene (or the left band), slid sideways, never shrunk below its rule
function tuileInside(text, x, y, anchor, o) {
  let g = tuile(text, x, y, Object.assign({}, o, { anchor })); let b = g.box;
  const Z = (o.zone) || (b[0] < HG[2] && b[1] < SCENE[1] ? COLS : SCENE);
  const dy = b[1] < Z[1] ? Z[1] - b[1] : b[3] > Z[3] ? Z[3] - b[3] : 0;
  const dx = b[0] < Z[0] ? Z[0] - b[0] : b[2] > Z[2] ? Z[2] - b[2] : 0;
  if (dx || dy) { g.remove(); g = tuile(text, x + dx, y + dy, Object.assign({}, o, { anchor })); }
  return g;
}
// the first candidate that fits and touches nothing taken; the last resort is kept but flagged (g.force): the check
// then refuses it (text on a shape, or two texts) and the safety net replays the sheet on the safe recipe
function placeTuile(text, cands, taken, o = {}) {
  const more = [];
  for (const [x, y, a, mw] of cands) for (const dy of [120, -120]) more.push([x, y + dy, a, mw]);
  for (const [x, y, anchor, mw] of [...cands, ...(o.strict ? [] : more)]) {
    const g = tuileInside(text, x, y, anchor, mw ? Object.assign({}, o, { maxw: mw }) : o);
    if (!taken.some(c => hit(g.box, c)) && (o.zone ? inside(g.box, o.zone) : fits(g.box))) { taken.push(g.box); return g; }
    g.remove(); }
  const [x, y, anchor] = cands[0]; const g = tuileInside(text, x, y, anchor, o); g.force = true; taken.push(g.box); return g;
}

// the REAL box of a text group (getBBox: the font's line box, once, at setup): scaled down until it fits maxw and the
// zone's height, then centred on (x, y) and slid inside the zone. Returns { box, x, y } (the centre the frappe uses).
function fitText(g, texts, Z, x, y, maxw) {
  for (let it = 0; it < 5; it++) {
    const b = g.getBBox(), f = Math.min(1, maxw / Math.max(1, b.width), (Z[3] - Z[1]) / Math.max(1, b.height));
    if (f >= .995) break;
    const cy0 = b.y + b.height / 2;
    texts.forEach(t => { const s = +t.getAttribute('font-size') * f * .995; t.setAttribute('font-size', s.toFixed(2));
      if (t.getAttribute('letter-spacing')) t.setAttribute('letter-spacing', (+t.getAttribute('letter-spacing') * f).toFixed(2));
      t.setAttribute('y', (cy0 + (+t.getAttribute('y') - cy0) * f).toFixed(2));
      [...t.children].forEach(c => { if (c.getAttribute('dy')) c.setAttribute('dy', (+c.getAttribute('dy') * f).toFixed(2)); }); });
  }
  const b = g.getBBox(), w = b.width, h = b.height;
  const tx = clamp(x, Z[0] + w / 2, Z[2] - w / 2), ty = clamp(y, Z[1] + h / 2, Z[3] - h / 2);
  const dx = tx - (b.x + w / 2), dy = ty - (b.y + h / 2);
  texts.forEach(t => { t.setAttribute('x', (+t.getAttribute('x') + dx).toFixed(2)); t.setAttribute('y', (+t.getAttribute('y') + dy).toFixed(2));
    [...t.children].forEach(c => { if (c.getAttribute('x') !== null) c.setAttribute('x', (+c.getAttribute('x') + dx).toFixed(2)); }); });
  return { box: [tx - w / 2, ty - h / 2, tx + w / 2, ty + h / 2], x: tx, y: ty };
}

// ---- VERDICT (the meaning word, the hero: 150 px, −0,02 em). o.frappe: it strikes. o.zone: its box (scene or floor).
function verdict(text, x, y, o = {}) {
  const Z = o.zone || SCENE;
  const g = mk(layerOf(o), 'g', { class: 'chk txt verdict', opacity: 0 });
  if (o.hote) g.setAttribute('data-hote', o.hote);
  const s0 = o.size || 150, maxw = Math.min(o.maxw || 840, Z[2] - Z[0]), zh = Z[3] - Z[1];
  const tx = mk(g, 'text', { 'font-size': s0, fill: o.color || C.os, 'text-anchor': 'middle', 'letter-spacing': -.02 * s0, x, y: y + s0 * .36 });
  if (o.font) tx.style.fontFamily = o.font;            // a style: the page's CSS (text { font-family: Mont }) beats an SVG attribute
  tx.textContent = text;
  // the width scales with the size: one line at the largest size that fits; two lines (cut at the best space) only
  // when that is clearly larger (and still fits the zone's height)
  const w1 = tx.getComputedTextLength(), size1 = Math.min(s0, Math.floor(s0 * maxw / w1), Math.floor(zh / .92));
  let size = size1, lines = 1, best = null;
  if (!o.oneLine && text.includes(' ') && size1 < .85 * s0) {
    const ws = text.split(' ');
    for (let c = 1; c < ws.length; c++) { const parts = [ws.slice(0, c).join(' '), ws.slice(c).join(' ')]; tx.textContent = parts[0];
      const a = tx.getComputedTextLength(); tx.textContent = parts[1]; const b = tx.getComputedTextLength(); const wm = Math.max(a, b);
      if (!best || wm < best[0]) best = [wm, parts]; }
    tx.textContent = text;
    const size2 = Math.min(s0, Math.floor(s0 * maxw / best[0]), Math.floor(zh / 1.94));
    if (size2 > size1 * 1.12 && size2 >= 64) { size = size2; lines = 2; }
  }
  set(tx, { 'font-size': size, 'letter-spacing': -.02 * size, y: y + size * .36 });
  if (lines === 2) { tx.textContent = ''; best[1].forEach((ln, k) => { const sp = mk(tx, 'tspan', { x, dy: k ? size * 1.02 : 0 }); sp.textContent = ln; });
    set(tx, { y: y + size * .36 - size * .51 }); }
  const fb = fitText(g, [tx], Z, x, y, maxw), box = fb.box; x = fb.x; y = fb.y; size = +tx.getAttribute('font-size');
  Object.assign(g, { _t: tx, box, room: box, size, text, cx: x, cy: y, layer: o.layer || 'labels' });
  if (o.frappe !== false) {
    const k = kFit(box, x, y, Z), bl = blurFilter(grow(box, k)); g.room = grow(box, (1 + k) / 2);
    if (o.at !== undefined && o.at < 99) FRAPPES.push({ box, at: o.at - .1, layer: g.layer, el: g });
    g.show = (t, at) => strike(g, t, at - .1 > LATE ? 99 : at - .1, k, x, y, bl);
  } else g.show = (t, at) => { const p = at - .1 > LATE ? 0 : eIn((t - (at - .1)) / STD); set(g, { opacity: p, transform: `translate(0 ${24 * (1 - p)})` }); };
  return g;
}

// ---- CHIFFRE (V2-8): a spoken number, exactly as said, that strikes (300 px on the floor, 240 in the scene); its
// qualifier (« UP TO ») above it, 72 px Brume; never a count-up (it showed parasite numbers in v1)
function parseNum(label) { const m = String(label).replace(/\s/g, '').match(/^([^0-9]*)([0-9][0-9,\.]*)(.*)$/);
  if (!m) return null; const raw = m[2]; const val = parseFloat(raw.replace(/,/g, '')); if (!isFinite(val)) return null;
  const dec = raw.includes('.') ? raw.split('.')[1].length : 0;
  return { pre: m[1], val, dec, comma: raw.includes(','), post: m[3] }; }
function chiffre(label, x, y, o = {}) {
  const Z = o.zone || SCENE;
  const g = mk(layerOf(o), 'g', { class: 'chk txt chiffre', opacity: 0 });
  const mm = String(label).match(/^(.*?)(\d.*)$/), qual = mm && mm[1].trim() ? mm[1].trim() : '', num = mm ? mm[2].trim() : String(label);
  let size = o.size || 240;
  const q = qual ? mk(g, 'text', { 'font-size': 72, fill: C.brume, 'text-anchor': 'middle', x }) : null; if (q) q.textContent = qual;
  const tx = mk(g, 'text', { 'font-size': size, fill: C.os, 'text-anchor': 'middle', 'letter-spacing': -.02 * size, 'font-variant-numeric': 'tabular-nums', x });
  tx.textContent = num;
  const maxw = Math.min(o.maxw || 760, Z[2] - Z[0]);
  const qh = q ? 84 : 0, place = () => { const top = y - (size * .74 + qh) / 2; if (q) q.setAttribute('y', top + 60); tx.setAttribute('y', top + qh + size * .72); };
  place();
  const fb = fitText(g, q ? [q, tx] : [tx], Z, x, y, maxw), box = fb.box; x = fb.x; y = fb.y; size = +tx.getAttribute('font-size');
  const k = kFit(box, x, y, Z), bl = blurFilter(grow(box, k));
  Object.assign(g, { _t: tx, box, room: grow(box, (1 + k) / 2), size, text: label, cx: x, cy: y, layer: o.layer || 'labels' });
  if (o.at !== undefined && o.at < 99) FRAPPES.push({ box, at: o.at - .1, layer: g.layer, el: g });
  g.show = (t, at) => { const t1 = at - .1 > LATE ? 99 : at - .1; strike(g, t, t1, k, x, y, bl);
    tx.setAttribute('fill', mix(C.os, C.coeur, clamp(1 - Math.abs(t - t1 - .1) / .3))); };
  return g;
}
function pions(total, x, y, o = {}) {        // Isotype (V2-8): r 44, gap 30, rows of 5, never scaled
  const g = mk($('scene'), 'g', { class: 'chk', opacity: 0 }), r = o.r || 44, gap = o.gap || 30, per = 5;
  const rows = Math.ceil(total / per), W = Math.min(total, per) * 2 * r + (Math.min(total, per) - 1) * gap;
  const dots = [...Array(total)].map((_, k) => { const row = Math.floor(k / per), col = k % per;
    return mk(g, 'circle', { cx: x - W / 2 + r + col * (2 * r + gap), cy: y + row * (2 * r + gap), r, fill: C.os, stroke: C.os, 'stroke-width': 6 }); });
  Object.assign(g, { dots, box: [x - W / 2, y - r, x + W / 2, y + (rows - 1) * (2 * r + gap) + r] });
  g.show = t => g.setAttribute('opacity', skel(t));
  return g;
}

// ---- COLONNE (V2-8): the quantity, vertical, with volume. Track r 40 Nuit/Ardoise 6 px; fill Os-haut → Os-ombre with a
// 6 px highlight; the marker of the state BEFORE (10 px Brume, 28 px beyond each side) once it has changed; a gain is
// the fill itself (no more coeur). A LOSS leaves the track EMPTY above the fill, with the « before » marker: no light
// segment that reads as an extension (banc v2a, 0e9 c8 : « la part perdue se lit comme une extension »).
// POSE: at its level from frame 0.
function colonne(x0, y0, x1, y1, o = {}) {
  const g = mk($('scene'), 'g', { class: 'chk colonne', opacity: 0 }), id = 'cc' + (NID++);
  const trk = mk(g, 'rect', { x: x0, y: y0, width: x1 - x0, height: y1 - y0, rx: 40, fill: C.nuit, stroke: C.ardoise, 'stroke-width': 6 });
  const cp = mk(mk(g, 'defs'), 'clipPath', { id }); mk(cp, 'rect', { x: x0 + 14, y: y0 + 14, width: x1 - x0 - 28, height: y1 - y0 - 28, rx: 28 });
  const inner = mk(g, 'g', { 'clip-path': `url(#${id})` });
  const lost = { setAttribute() { } };                   // no lost veil any more (see above)
  const fill = mk(inner, 'rect', { x: x0 + 14, width: x1 - x0 - 28, fill: 'url(#colG)' });
  const shine = mk(inner, 'line', { x1: x0 + 30, x2: x1 - 30, stroke: '#FFFFFF', 'stroke-opacity': .45, 'stroke-width': 6, 'stroke-linecap': 'round' });
  const before = mk(g, 'line', { x1: x0 - 28, x2: x1 + 28, stroke: C.brume, 'stroke-width': 10, 'stroke-linecap': 'round', opacity: 0 });
  const h = y1 - y0, yOf = lv => y1 - 14 - (h - 28) * clamp(lv, 0, 1.04);
  Object.assign(g, { x0, y0, x1, y1, yOf, box: [x0, y0, x1, y1], xm: (x0 + x1) / 2 });
  g.show = t => g.setAttribute('opacity', skel(t));
  g.edge = k => set(trk, { stroke: mix(C.ardoise, C.os, .85 * k), 'stroke-width': 6 + 3 * k });
  g.level = (lv, base, mark = 0) => { const y = yOf(lv), yb = yOf(base), top = Math.min(y, yb);
    set(fill, { y, height: Math.max(0, y1 - 14 - y) }); set(shine, { y1: y + 9, y2: y + 9, opacity: y1 - 14 - y > 24 ? 1 : 0 });
    if (lv < base) set(lost, { y: yb, height: Math.max(0, y - yb), opacity: 1 }); else set(lost, { height: 0, opacity: 0 });
    set(before, { y1: yb, y2: yb, opacity: mark }); };
  return g;
}

// ---- MÉDAILLON (V2-8): replaces the station. Rest: Nuit / Brume 8 px. Lit (Os): Crépuscule / Os, halo Os r 2,1 r,
// peak 0,30. Signal: outline amber, halo amber 0,30. Out (S4a): Nuit, outline amber 0,45 (no more brown).
// Lighting 0,18 s eIn at HIT, with one pulse ring r → r + 46 (6 px Os, 0,5 → 0, 0,5 s p3o). o.cle: a picto (lot 3).
function medaillon(x, y, r, o = {}) {
  const g = mk($('scene'), 'g', { class: 'medaillon' });
  const halo = mk(g, 'circle', { cx: x, cy: y, r: r * 2.1, fill: 'url(#haloO)', opacity: 0 });
  const ring = mk(g, 'circle', { cx: x, cy: y, r, fill: 'none', stroke: C.os, 'stroke-width': 6, opacity: 0 });
  const c = mk(g, 'circle', { class: 'chk', cx: x, cy: y, r, fill: C.nuit, stroke: C.brume, 'stroke-width': 8 });
  if (o.id) c.setAttribute('data-id', o.id);
  let lk = 0, mode = 'os', ek = 0, pk = 0;
  // V2-5 (lot 3): the picto of the thing named, in its own wrapper; it pops on its word (×0,6 → 1, 0,40 s p3o): it is
  // the picto that carries the sync; nothing is drawn before its word
  const pw = mk(g, 'g', { class: 'pw', opacity: 0 });
  const pic = o.cle && window.picto ? window.picto(o.cle, pw, x, y, r, { tone: 0 }) : null;
  const paint = () => {
    if (mode === 'eteint') { set(c, { fill: C.nuit, stroke: C.ambre, 'stroke-opacity': .45, 'stroke-width': 8 }); halo.setAttribute('opacity', 0);
      if (pic) { pic.tone(.6); pic.setAttribute('opacity', .55); } return; }
    const col = mode === 'signal' ? C.ambre : C.os;
    set(c, { fill: mix(C.nuit, C.crep, lk), stroke: mix(mix(C.brume, col, lk), C.os, .85 * ek * (mode === 'signal' ? 0 : 1)), 'stroke-opacity': 1, 'stroke-width': 8 + 4 * ek });
    set(halo, { opacity: (.30 * lk).toFixed(3), fill: mode === 'signal' ? 'url(#haloA)' : 'url(#haloO)' });
    if (pic) { pic.tone(lk); pic.setAttribute('opacity', 1); } };
  Object.assign(g, { x, y, r, c, halo, pic, box: [x - r - 4, y - r - 4, x + r + 4, y + r + 4] });
  g.lit = (k, m = 'os') => { lk = clamp(k); mode = m; paint(); };
  g.edge = k => { ek = k; paint(); };
  g.pop = t => { g.setAttribute('opacity', skel(t)); if (!pic) return;
    const q = (o.at === undefined || o.at >= 99) ? 1 : p3o((t - (o.at - .1)) / .40);
    set(pw, { opacity: q.toFixed(3), transform: `translate(${x} ${y}) scale(${(.6 + .4 * q).toFixed(4)}) translate(${-x} ${-y})` }); };
  g.pulse = (t, at) => { const q = (t - at) / .5; if (q <= 0 || q >= 1) { ring.setAttribute('opacity', 0); return; }
    set(ring, { r: r + 46 * p3o(q), opacity: (.5 * (1 - p3o(q))).toFixed(3) }); };
  g.grow = s => g.setAttribute('transform', `translate(${x} ${y}) scale(${s}) translate(${-x} ${-y})`);
  g.idle = t => { if (pic) pic.idle(t); };
  return g;
}

// ---- VOIE (V2-8): 18 px Brume 0,70, round caps, stopping 16 px from each medallion; its ghost (0,35) from frame 0,
// traced over it in 0,45 s. voieEntre(a, b): the straight path between two medallions.
function voie(d, o = {}) {
  const g = mk($('scene'), 'g', { class: 'chk voie' }), col = o.color || C.brume, w0 = o.w || 18, al = o.alpha || .7;
  if (o.id) g.setAttribute('data-id', o.id);
  const ghost = mk(g, 'path', { d, fill: 'none', stroke: col, 'stroke-width': w0, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', opacity: GHOST * al });
  const p = mk(g, 'path', { d, fill: 'none', stroke: col, 'stroke-opacity': al, 'stroke-width': w0, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
  const L0 = p.getTotalLength(), bb = p.getBBox();
  let wk = 0, ck = 0, ek = 0;
  const paint = () => { const c = mix(mix(col, C.os, ck), C.os, .8 * ek); set(p, { stroke: c, 'stroke-width': w0 + wk, 'stroke-opacity': al + (1 - al) * Math.max(ck, ek) });
    set(ghost, { stroke: c, 'stroke-width': w0 + wk }); };
  Object.assign(g, { p, L: L0, box: [bb.x, bb.y, bb.x + bb.width, bb.y + bb.height], at: u => p.getPointAtLength(L0 * clamp(u)) });
  g.draw = (t, at = .05, dur = .45) => { const q = eIn((t - at) / dur); p.style.strokeDasharray = L0; p.style.strokeDashoffset = L0 * (1 - q); };
  g.thick = (dw, dc) => { wk = dw; ck = dc; paint(); };
  g.edge = k => { ek = k; paint(); };
  return g;
}
const voieEntre = (a, b, o = {}) => { const dx = b.x - a.x, dy = b.y - a.y, L0 = Math.hypot(dx, dy), ux = dx / L0, uy = dy / L0;
  const p0 = [a.x + ux * (a.r + 16), a.y + uy * (a.r + 16)], p1 = [b.x - ux * (b.r + 16), b.y - uy * (b.r + 16)];
  return voie(`M${p0[0].toFixed(1)} ${p0[1].toFixed(1)} L ${p1[0].toFixed(1)} ${p1[1].toFixed(1)}`, o); };
// ---- COMÈTE (V2-8): trails 14 / 20 / 26 px at 0,3 / 0,6 / 1, head r 18 coeur, halo r 56 (class « comete »: the one
// amber that never counts in the budget)
function impulsion(v, o = {}) {
  const g = mk($('scene'), 'g', { class: 'comete', opacity: 0 }), col = o.color || C.ambre;
  const trail = [[150, 14, .3], [90, 20, .6], [44, 26, 1]].map(([len, w, a]) =>
    ({ len, a, el: mk(g, 'path', { d: v.p.getAttribute('d'), fill: 'none', stroke: col, 'stroke-width': w, 'stroke-linecap': 'round', opacity: a, filter: 'url(#glow)' }) }));
  const halo = mk(g, 'circle', { r: 56, fill: col === C.ambre ? 'url(#haloA)' : 'url(#haloO)' });
  const head = mk(g, 'circle', { r: o.r || 18, fill: col === C.ambre ? C.coeur : '#FFFFFF' });
  g.at = (u, a = 1, lk = 1) => { const s = v.L * clamp(u), q = v.p.getPointAtLength(s);
    trail.forEach(T0 => { const l = Math.min(T0.len * lk, s); T0.el.style.strokeDasharray = `${l} ${v.L + T0.len * lk}`; T0.el.style.strokeDashoffset = -(s - l); });
    set(halo, { cx: q.x, cy: q.y }); set(head, { cx: q.x, cy: q.y }); g.setAttribute('opacity', a); return q; };
  g.hide = () => g.setAttribute('opacity', 0);
  return g;
}
// ---- BARRAGE (V2-8): 48 × 360, r 16, flat coral, falls in 0,18 s with 3 % overshoot. o.horiz: across a vertical path
function barrage(x, y, o = {}) {
  const g = mk($('scene'), 'g', { class: 'chk', opacity: 0 }), L0 = o.l || 360, W = 48;
  const w = o.horiz ? L0 : W, h = o.horiz ? W : L0;
  mk(g, 'rect', { x: x - w / 2, y: y - h / 2, width: w, height: h, rx: 16, fill: C.corail });
  Object.assign(g, { box: [x - w / 2, y - h / 2, x + w / 2, y + h / 2] });
  g.show = (t, at) => { const q = eOver((t - (at - HIT) + FAST) / FAST); g.setAttribute('opacity', clamp(q * 3));
    g.setAttribute('transform', o.horiz ? `translate(${-80 * (1 - clamp(q, 0, 1.2))} 0)` : `translate(0 ${-80 * (1 - clamp(q, 0, 1.2))})`); };
  g.edge = k => { };
  return g;
}

// ---- the empty places of the POSE: a frame (the place of a number), the FILETS of the poster (V2-10.3, 4 px Ardoise
// 0,5), the BULLE (V2-10.1: 780 × 400, r 52, Nuit 0,92, outline Os 6 px 0,85, a small tail at the bottom left that
// points at nobody), and the amber underline (V2-7.5: 10 px, traced left to right in 0,30 s, never under an opinion)
function cadre(b, o = {}) {
  const g = mk($('scene'), 'g', { class: 'chk', opacity: 0 });
  const r = mk(g, 'rect', { x: b[0], y: b[1], width: b[2] - b[0], height: b[3] - b[1], rx: 40, fill: C.nuit, 'fill-opacity': .5, stroke: C.ardoise, 'stroke-width': 6 });
  if (o.id) r.setAttribute('data-id', o.id);
  Object.assign(g, { box: b });
  g.show = t => g.setAttribute('opacity', skel(t));
  g.edge = k => set(r, { stroke: mix(C.ardoise, C.os, .85 * k), 'stroke-width': 6 + 3 * k });
  return g;
}
function filet(x0, x1, y) {
  const g = mk($('scene'), 'g', { class: 'chk filet', opacity: 0 });
  const ln = mk(g, 'line', { x1: x0, x2: x1, y1: y, y2: y, stroke: C.ardoise, 'stroke-opacity': .5, 'stroke-width': 4, 'stroke-linecap': 'round' });
  Object.assign(g, { box: [x0, y - 2, x1, y + 2], y });
  let fk = 0, ek = 0; const paint = () => set(ln, { stroke: mix(mix(C.ardoise, C.brume, fk), C.os, .85 * ek), 'stroke-opacity': .5 + .4 * Math.max(fk, ek), 'stroke-width': 4 + 3 * ek });
  g.show = t => g.setAttribute('opacity', skel(t));
  g.filled = k => { fk = k; paint(); };
  g.edge = k => { ek = k; paint(); };
  return g;
}
function bulle(b, o = {}) {
  const g = mk($('scene'), 'g', { class: 'bulle', opacity: 0 }), [x0, y0, x1, y1] = b, r = 52, tx0 = x0 + 90, tip = o.tip || 58;
  const d = `M${x0 + r} ${y0} H${x1 - r} Q${x1} ${y0} ${x1} ${y0 + r} V${y1 - r} Q${x1} ${y1} ${x1 - r} ${y1} H${tx0 + 70} L${tx0 - 10} ${y1 + tip} L${tx0 + 10} ${y1} H${x0 + r} Q${x0} ${y1} ${x0} ${y1 - r} V${y0 + r} Q${x0} ${y0} ${x0 + r} ${y0} Z`;
  const p = mk(g, 'path', { class: 'chk', d, fill: C.nuit, 'fill-opacity': .92, stroke: C.os, 'stroke-opacity': .85, 'stroke-width': 6, 'data-id': o.id || 'bulle' });
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  Object.assign(g, { box: [x0, y0, x1, y1 + tip], inner: [x0 + 40, y0 + 40, x1 - 40, y1 - 40], cx, cy, id: o.id || 'bulle' });
  g.show = (t, F) => { const s = .96 + .04 * SPR_HERO.f((t - F) / SPR_HERO.dur);
    set(g, { opacity: skel(t), transform: `translate(${cx} ${cy}) scale(${s.toFixed(4)}) translate(${-cx} ${-cy})` }); };
  g.edge = k => set(p, { 'stroke-opacity': .85 + .15 * k, 'stroke-width': 6 + 3 * k });
  return g;
}
function souligne(x0, x1, y, o = {}) {
  const ln = mk(o.layer ? $(o.layer) : $('labels'), 'line', { x1: x0, x2: x0, y1: y, y2: y, stroke: C.ambre, 'stroke-width': 10, 'stroke-linecap': 'round', opacity: 0 });
  ln.show = (t, at) => { const q = eIn((t - at) / .30); set(ln, { x2: (x0 + (x1 - x0) * q).toFixed(1), opacity: q > 0 ? 1 : 0 }); };
  return ln;
}
// ---- CACHET (V2-7.4 / V2-10.1): the status said (« I THINK », « PERHAPS »): a small stamp, ×1,15 → 1 in 0,18 s x4o
function cachet(text, x, y, o = {}) {
  const g = mk(layerOf(o), 'g', { class: 'chk txt cachet', opacity: 0 });
  if (o.hote) g.setAttribute('data-hote', o.hote);
  const size = o.size || 56, bg = mk(g, 'rect', { rx: 12, fill: C.nuit, stroke: C.brume, 'stroke-width': 3 });
  const tx = mk(g, 'text', { 'font-size': size, fill: C.brume, 'text-anchor': 'middle', 'letter-spacing': .06 * size, x, y: y + size * .36 }); tx.style.fontFamily = o.font || 'JBMono';
  tx.textContent = text;
  const w = tx.getComputedTextLength() + size * .9, h = size * 1.35;
  if (o.anchor === 'start') { x += w / 2; tx.setAttribute('x', x); }
  set(bg, { x: x - w / 2, y: y - h / 2, width: w, height: h });
  Object.assign(g, { text, box: [x - w / 2, y - h / 2, x + w / 2, y + h / 2] });
  g.show = (t, at) => { const t1 = at - .1 > LATE ? 99 : at - .1; if (t < t1) { g.setAttribute('opacity', 0); return; }
    const q = x4o((t - t1) / .18); set(g, { opacity: clamp((t - t1) / .06), transform: `translate(${x} ${y}) scale(${1.15 - .15 * q}) translate(${-x} ${-y})` }); };
  return g;
}

// ---- what is SAID (V2-10): sentence case (« Interesting tool »), acronyms kept, « I » kept
const ACRO = /^(AI|MRI|MRIS|REM|DNA|ADHD|CEO|US|UK|EEG|FMRI|CBT|PTSD|IQ|ER|ICU)$/;
const phrase = s => { const ws = String(s).toLowerCase().split(' ').map(w => { const b = w.toUpperCase().replace(/[^A-Z]/g, '');
    return ACRO.test(b) ? w.toUpperCase() : b === 'I' ? w.toUpperCase() : w; }).join(' ');
  return ws.replace(/^([^a-zà-ÿ]*)([a-zà-ÿ])/, (m, a, b) => a + b.toUpperCase()); };

// ---- the invisible path a comet travels on (through the medallions' centres; the visible voies stop 16 px short)
function chemin(pts) { const d = 'M' + pts.map(p => `${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(' L ');
  const g = mk($('scene'), 'g', { opacity: 0 }); const p = mk(g, 'path', { d, fill: 'none', stroke: 'none' });
  return { p, L: p.getTotalLength(), box: null }; }
// ---- the REFERENCE line (V2-8, banc v2a b8e c1): 10 px Brume across the scene at the reference level; it appears IN
// PLACE (fade, ×0,96 → 1 about its centre), never traced or sliding (traced left to right, it read « a marker that
// moves right »)
function ligneRef(x0, x1, y) {
  const g = mk($('scene'), 'g', { class: 'chk ligneref', opacity: 0 }), cx = (x0 + x1) / 2;
  mk(g, 'line', { x1: x0, x2: x1, y1: y, y2: y, stroke: C.brume, 'stroke-width': 10, 'stroke-linecap': 'round' });
  Object.assign(g, { box: [x0 - 5, y - 5, x1 + 5, y + 5], y });
  g.show = (t, at) => { const q = eIn((t - at + .1) / STD); set(g, { opacity: q.toFixed(3), transform: `translate(${cx} ${y}) scale(${.96 + .04 * q} 1) translate(${-cx} ${-y})` }); };
  return g;
}
// ---- the text SAID inside a bubble (V2-10.1; Montserrat in lot 2): revealed from below in 0,30 s, inside the bubble
function dit(text, Z, o = {}) {
  const v = verdict(text, (Z[0] + Z[2]) / 2, (Z[1] + Z[3]) / 2, Object.assign({ zone: Z, size: o.size || 110, min: 64,
    maxw: Z[2] - Z[0] - (o.question ? 80 : 0), frappe: false, hote: o.hote, at: 99 }, o, { frappe: false }));
  const id = 'dc' + (NID++), cp = mk(mk(v, 'defs'), 'clipPath', { id, clipPathUnits: 'userSpaceOnUse' });
  mk(cp, 'rect', { x: Z[0], y: Z[1], width: Z[2] - Z[0], height: Z[3] - Z[1] });
  const inner = mk(v, 'g', { 'clip-path': `url(#${id})` }); inner.appendChild(v._t);
  let q2 = null;
  if (o.question) { q2 = mk(v._t, 'tspan', { fill: C.brume }); q2.textContent = '?'; }
  v.show = (t, at, tq = 99) => { const t1 = at - .1 > LATE ? 99 : at - .1; if (t < t1) { v.setAttribute('opacity', 0); return; }
    const p = p3o((t - t1) / .30); set(v, { opacity: clamp((t - t1) / .1) });
    v._t.setAttribute('transform', `translate(0 ${(40 * (1 - p)).toFixed(2)})`);
    if (q2) q2.setAttribute('fill-opacity', clamp((t - (tq - .1)) / .15)); };
  return v;
}

// ---- primitive 14 · VOILE: the rest fades (attention, perception); never a full black
function voile() { const r = mk($('scene'), 'rect', { width: 1080, height: 1920, fill: C.abyss, opacity: 0 }); return r; }
