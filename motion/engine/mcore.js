// Noyau du moteur « motion seul » : outils, calage sur les mots, et les primitives de la grammaire v0
// (motion-designer/grammaire_v0.md §3). Une primitive = un seul sens, une seule entrée (le « pop » depuis sa place),
// une seule courbe ; tout est fonction pure du temps.
const $ = id => document.getElementById(id);
const NS = 'http://www.w3.org/2000/svg';
const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const mk = (parent, tag, attrs = {}) => { const e = document.createElementNS(NS, tag); for (const k in attrs) if (attrs[k] !== undefined && attrs[k] !== null) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };
const set = (e, attrs) => { for (const k in attrs) e.setAttribute(k, attrs[k]); return e; };
const hex = c => [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16));
const mix = (a, b, k) => { const A = hex(a), B = hex(b); k = clamp(k);
  return '#' + A.map((v, i) => Math.round(v + (B[i] - v) * k).toString(16).padStart(2, '0')).join(''); };
const rnd = s => { const x = Math.sin(s * 127.1 + 311.7) * 43758.5453; return x - Math.floor(x); };

// ---- the house curve (decided, no bounce): cubic-bezier(0.2, 0, 0, 1) in, (0.3, 0, 1, 1) out
function bezier(x1, y1, x2, y2) {
  const cx = 3 * x1, bx = 3 * (x2 - x1) - cx, ax = 1 - cx - bx, cy = 3 * y1, by = 3 * (y2 - y1) - cy, ay = 1 - cy - by;
  const fx = t => ((ax * t + bx) * t + cx) * t, fy = t => ((ay * t + by) * t + cy) * t, dx = t => (3 * ax * t + 2 * bx) * t + cx;
  return x => { x = clamp(x); if (x === 0 || x === 1) return x; let t = x;
    for (let i = 0; i < 8; i++) { const d = fx(t) - x; if (Math.abs(d) < 1e-5) break; const s = dx(t); if (Math.abs(s) < 1e-6) break; t -= d / s; }
    return fy(clamp(t)); }; }
const eIn = bezier(.2, 0, 0, 1), eOut = bezier(.3, 0, 1, 1);
const eSine = x => -(Math.cos(Math.PI * clamp(x)) - 1) / 2;
const eOver = x => { x = clamp(x); const c1 = .6, c3 = c1 + 1; return 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2); };  // ≈ 3 % overshoot
const FAST = .18, STD = .30, SLOW = .60, HIT = .067;

// ---- the colours (one colour = one meaning)
const C = { abyss: '#0B1226', nuit: '#141E37', crep: '#22305A', ardoise: '#3A4A7A', brume: '#8796C8', os: '#F4EDE0',
  ambre: '#FFB43F', coeur: '#FFF1CF', corail: '#FF6A4D' };

// ---- words: SPEC roles carry word numbers {i}; WORDS = [{i, w, t, e}] in shot seconds, snapped on the heard voice
const S = window.SPEC, D = S.D || 5, R = S.roles || {};
const T = r => { if (r === null || r === undefined) return 99; const i = typeof r === 'object' ? r.i : r;
  const w = (window.WORDS || []).find(x => x.i === i); return w ? w.t : 99; };
const TE = r => { const i = typeof r === 'object' ? r.i : r; const w = (window.WORDS || []).find(x => x.i === i); return w ? w.e : 99; };
const L = r => (r && r.label ? String(r.label).toUpperCase() : '');

// ---- primitive 1 · PASTILLE: names a spoken thing; pops at word − 0.10 s; turns amber while active
function pastille(text, x, y, o = {}) {
  const g = mk($('labels'), 'g', { class: 'chk txt', opacity: 0 });
  const r = mk(g, 'rect', { rx: 43, ry: 43, height: 86, fill: C.abyss, 'fill-opacity': .82, stroke: C.ardoise, 'stroke-width': 3 });
  const tx = mk(g, 'text', { 'font-size': o.size || 64, fill: C.os, 'text-anchor': 'middle', 'letter-spacing': 1 });
  tx.textContent = text;
  const w = tx.getComputedTextLength() + 44, cx = o.anchor === 'start' ? x + w / 2 : o.anchor === 'end' ? x - w / 2 : x;
  set(r, { x: cx - w / 2, y: y - 43, width: w }); set(tx, { x: cx, y: y + 23 });
  Object.assign(g, { _t: tx, _r: r, _cx: cx, _cy: y, _w: w, box: [cx - w / 2, y - 43, cx + w / 2, y + 43] });
  g.show = (t, at, end = 99) => { const p = eIn((t - (at - .1)) / FAST), act = clamp(Math.min((t - at + .1) / .08 + 1, (end - t) / .08));
    set(g, { opacity: p, transform: `translate(${cx} ${y}) scale(${.9 + .1 * p}) translate(${-cx} ${-y})` });
    tx.setAttribute('fill', mix(C.os, C.ambre, act)); r.setAttribute('stroke', mix(C.ardoise, C.ambre, act)); };
  return g;
}
// a label that finds its own place: first candidate inside the scene and touching nothing already taken
// the safe area BEFORE the camera push (×1.05 about 540,640): once pushed, everything stays inside the charter's zones
const SCENE = [116, 300, 964, 984];
const hit = (a, b, pad = 16) => a[0] < b[2] + pad && a[2] > b[0] - pad && a[1] < b[3] + pad && a[3] > b[1] - pad;
// a pill at (x, y), slid sideways (never shrunk) until it is inside the safe area
function pillInside(text, x, y, anchor, o) {
  y = Math.max(SCENE[1] + 43, Math.min(SCENE[3] - 43, y));
  let g = pastille(text, x, y, Object.assign({}, o, { anchor })); const b = g.box;
  const dx = b[0] < SCENE[0] ? SCENE[0] - b[0] : b[2] > SCENE[2] ? SCENE[2] - b[2] : 0;
  if (dx) { g.remove(); g = pastille(text, x + dx, y, Object.assign({}, o, { anchor })); }
  return g;
}
function placeLabel(text, cands, taken, o = {}) {
  const more = [];                                   // when the planned places are taken: around them, never on top
  for (const [x, y, a] of cands) for (const dy of [110, -110, 220, -220]) more.push([x, y + dy, a]);
  for (const [x, y, a] of cands) for (const dx of [-230, 230]) more.push([x + dx, y, a]);
  for (const [x, y, anchor] of [...cands, ...more]) {
    const g = pillInside(text, x, y, anchor, o);
    if (!taken.some(c => hit(g.box, c))) { taken.push(g.box); return g; }
    g.remove(); }
  const [x, y, anchor] = cands[0]; const g = pillInside(text, x, y, anchor, o); taken.push(g.box); return g;
}

// ---- primitive 2 · VERDICT: the meaning word, big, the state after; rises 24 px at word − 0.10 s and stays
function verdict(text, x, y, o = {}) {
  const g = mk($('labels'), 'g', { class: 'chk txt', opacity: 0 });
  let size = o.size || 132;
  const tx = mk(g, 'text', { 'font-size': size, fill: o.color || C.os, 'text-anchor': 'middle', 'letter-spacing': 2, x, y: y + size * .36 });
  tx.textContent = text;
  const maxw = Math.min(o.maxw || 840, SCENE[2] - SCENE[0]);
  while (tx.getComputedTextLength() > maxw && size > 84) { size -= 6; set(tx, { 'font-size': size, y: y + size * .36 }); }
  let lines = 1;
  while (o.oneLine && tx.getComputedTextLength() > maxw && size > 64) { size -= 4; set(tx, { 'font-size': size, y: y + size * .36 }); }
  if (!o.oneLine && tx.getComputedTextLength() > maxw && text.includes(' ')) {          // two lines, cut at the middle space
    const ws = text.split(' '), cut = Math.max(1, Math.round(ws.length / 2)); tx.textContent = '';
    [ws.slice(0, cut).join(' '), ws.slice(cut).join(' ')].forEach((ln, k) => {
      const sp = mk(tx, 'tspan', { x, dy: k ? size * 1.02 : 0 }); sp.textContent = ln; });
    lines = 2; set(tx, { y: y + size * .36 - size * .51 });
    while (Math.max(...[...tx.children].map(c => c.getComputedTextLength())) > maxw && size > 72) {
      size -= 6; set(tx, { 'font-size': size, y: y + size * .36 - size * .51 }); [...tx.children].forEach((c, k) => k && c.setAttribute('dy', size * 1.02)); }
  }
  const w = lines > 1 ? Math.max(...[...tx.children].map(c => c.getComputedTextLength())) : tx.getComputedTextLength();
  const half = size * (lines > 1 ? .96 : .45);
  const dx = x - w / 2 < SCENE[0] ? SCENE[0] - (x - w / 2) : x + w / 2 > SCENE[2] ? SCENE[2] - (x + w / 2) : 0;
  const dy = y - half < SCENE[1] ? SCENE[1] - (y - half) : y + half > SCENE[3] ? SCENE[3] - (y + half) : 0;
  if (dx || dy) { tx.setAttribute('x', x + dx); [...tx.children].forEach(c => c.setAttribute('x', x + dx));
    tx.setAttribute('y', +tx.getAttribute('y') + dy); x += dx; y += dy; }
  Object.assign(g, { _t: tx, box: [x - w / 2, y - half, x + w / 2, y + half], size });
  g.show = (t, at) => { const p = eIn((t - (at - .1)) / STD); set(g, { opacity: p, transform: `translate(0 ${24 * (1 - p)})` }); };
  return g;
}

// ---- primitive 3 · CHIFFRE: a spoken number, counted up and landing at HIT; pions for small counts
function parseNum(label) { const m = String(label).replace(/\s/g, '').match(/^([^0-9]*)([0-9][0-9,\.]*)(.*)$/);
  if (!m) return null; const raw = m[2]; const val = parseFloat(raw.replace(/,/g, '')); if (!isFinite(val)) return null;
  const dec = raw.includes('.') ? raw.split('.')[1].length : 0;
  return { pre: m[1], val, dec, comma: raw.includes(','), post: m[3] }; }
const fmtNum = (n, p) => { let s = n.toFixed(p.dec); if (p.comma) s = Number(s).toLocaleString('en-US', { minimumFractionDigits: p.dec, maximumFractionDigits: p.dec }); return p.pre + s + p.post; };
function chiffre(label, x, y, o = {}) {
  const p = parseNum(label);
  const g = mk($('labels'), 'g', { class: 'chk txt', opacity: 0 });
  let size = o.size || 270;
  const tx = mk(g, 'text', { 'font-size': size, fill: C.os, 'text-anchor': 'middle', 'letter-spacing': 0, x, y: y + size * .36, 'font-variant-numeric': 'tabular-nums' });
  tx.textContent = label;
  while (tx.getComputedTextLength() > (o.maxw || 760) && size > 110) { size -= 10; set(tx, { 'font-size': size, y: y + size * .36 }); }
  let w = tx.getComputedTextLength();
  const dx = x - w / 2 < SCENE[0] ? SCENE[0] - (x - w / 2) : x + w / 2 > SCENE[2] ? SCENE[2] - (x + w / 2) : 0;
  if (dx) { x += dx; tx.setAttribute('x', x); }                    // slid back inside the safe area, never cut
  Object.assign(g, { _t: tx, box: [x - w / 2, y - size * .45, x + w / 2, y + size * .45], size });
  const from = o.from !== undefined ? o.from : 0;
  g.show = (t, at) => { // pops at its word, exactly as said (a count-up showed parasite numbers: "3%" before "30%")
    const t1 = at - HIT, p2 = eIn((t - t1 + .12) / FAST);
    set(g, { opacity: p2, transform: `translate(${x} ${y}) scale(${.86 + .14 * p2}) translate(${-x} ${-y})` });
    tx.textContent = label;
    tx.setAttribute('fill', mix(C.os, C.coeur, clamp(1 - Math.abs(t - t1) / .3))); };
  return g;
}
function pions(total, x, y, o = {}) {        // Isotype: rows of 5, same size, never scaled
  const g = mk($('scene'), 'g', { class: 'chk', opacity: 0 }), r = o.r || 40, gap = o.gap || 34, per = 5;
  const rows = Math.ceil(total / per), W = Math.min(total, per) * 2 * r + (Math.min(total, per) - 1) * gap;
  const dots = [...Array(total)].map((_, k) => { const row = Math.floor(k / per), col = k % per;
    return mk(g, 'circle', { cx: x - W / 2 + r + col * (2 * r + gap), cy: y + row * (2 * r + gap), r, fill: C.os, stroke: C.os, 'stroke-width': 6 }); });
  Object.assign(g, { dots, box: [x - W / 2, y - r, x + W / 2, y + (rows - 1) * (2 * r + gap) + r] });
  g.show = (t, at, lit, litAt) => { set(g, { opacity: eIn((t - at + .1) / FAST) });
    dots.forEach((d, k) => { const on = k < lit ? 1 : 1 - eIn((t - (litAt - HIT) - .06 * (total - 1 - k) * 0 - .04 * (k - lit)) / FAST);
      set(d, { fill: on > .5 ? C.os : mix(C.nuit, C.os, on), 'fill-opacity': .15 + .85 * on }); }); };
  return g;
}

// ---- primitive 4 · JAUGE: a quantity (rises, drops, spills); the before stays visible ≥ 0.8 s
function jauge(x, top, h, o = {}) {
  const w = o.w || 150, g = mk($('scene'), 'g', { class: 'chk', opacity: 0 }), bot = top + h;
  mk(g, 'rect', { x: x - w / 2, y: top, width: w, height: h, rx: 26, fill: C.nuit, stroke: C.ardoise, 'stroke-width': 6 });
  const cp = mk(mk(g, 'defs'), 'clipPath', { id: 'jc' + Math.round(x) + Math.round(top) });
  mk(cp, 'rect', { x: x - w / 2 + 12, y: top + 12, width: w - 24, height: h - 24, rx: 16 });
  const inner = mk(g, 'g', { 'clip-path': `url(#jc${Math.round(x)}${Math.round(top)})` });
  const lost = mk(inner, 'rect', { x: x - w / 2 + 12, width: w - 24, fill: C.os, 'fill-opacity': .14 });
  const fill = mk(inner, 'rect', { x: x - w / 2 + 12, width: w - 24, fill: C.os });
  const gain = mk(inner, 'rect', { x: x - w / 2 + 12, width: w - 24, fill: C.coeur });
  const yOf = lv => bot - 12 - (h - 24) * clamp(lv, 0, 1.08);
  Object.assign(g, { x, top, h, w, bot, yOf, box: [x - w / 2, top, x + w / 2, bot] });
  g.show = (t, at) => set(g, { opacity: eIn((t - at) / STD), transform: `translate(${x} ${bot}) scale(1 ${.9 + .1 * eIn((t - at) / STD)}) translate(${-x} ${-bot})` });
  g.level = (lv, base) => { const y = yOf(lv), yb = yOf(base);       // base = level before the change
    if (lv < base) { set(lost, { y: yb, height: Math.max(0, y - yb) }); set(fill, { y, height: Math.max(0, bot - y) }); set(gain, { height: 0 }); }
    else { set(lost, { height: 0 }); set(fill, { y: yb, height: Math.max(0, bot - yb) }); set(gain, { y, height: Math.max(0, yb - y) }); } };
  return g;
}
// ---- primitive 4 bis · BARRE: the same quantity, laid flat across the screen (it fills from the left)
function barre(x0, y, w, h, o = {}) {
  const g = mk($('scene'), 'g', { class: 'chk', opacity: 0 }), id = 'bc' + Math.round(x0) + Math.round(y);
  mk(g, 'rect', { x: x0, y, width: w, height: h, rx: 28, fill: C.nuit, stroke: C.ardoise, 'stroke-width': 6 });
  const cp = mk(mk(g, 'defs'), 'clipPath', { id }); mk(cp, 'rect', { x: x0 + 12, y: y + 12, width: w - 24, height: h - 24, rx: 18 });
  const inner = mk(g, 'g', { 'clip-path': `url(#${id})` });
  const lost = mk(inner, 'rect', { y: y + 12, height: h - 24, fill: C.os, 'fill-opacity': .14 });
  const fill = mk(inner, 'rect', { x: x0 + 12, y: y + 12, height: h - 24, fill: C.os });
  const gain = mk(inner, 'rect', { y: y + 12, height: h - 24, fill: C.coeur });
  const xOf = lv => x0 + 12 + (w - 24) * clamp(lv, 0, 1.04);
  Object.assign(g, { x0, y, w, h, xOf, box: [x0, y, x0 + w, y + h] });
  g.show = (t, at) => { const p = eIn((t - at) / STD); set(g, { opacity: p, transform: `translate(${x0} ${y + h / 2}) scale(${.9 + .1 * p} 1) translate(${-x0} ${-y - h / 2})` }); };
  g.level = (lv, base) => { const x = xOf(lv), xb = xOf(base);
    if (lv < base) { set(lost, { x, width: Math.max(0, xb - x) }); set(fill, { width: Math.max(0, x - x0 - 12) }); set(gain, { width: 0 }); }
    else { set(lost, { width: 0 }); set(fill, { width: Math.max(0, xb - x0 - 12) }); set(gain, { x: xb, width: Math.max(0, x - xb) }); } };
  return g;
}
function repereH(b, lv, o = {}) {
  const x = b.xOf(lv), g = mk($('scene'), 'g', { class: 'chk', opacity: 0 });
  const ln = mk(g, 'line', { x1: x, x2: x, y1: b.y - 34, y2: b.y + b.h + 34, stroke: o.color || C.brume, 'stroke-width': 10, 'stroke-linecap': 'round' });
  Object.assign(g, { x, box: [x - 5, b.y - 34, x + 5, b.y + b.h + 34] });
  g.draw = (t, at) => { const q = eIn((t - at + .1) / STD); g.setAttribute('opacity', q > 0 ? 1 : 0);
    const L0 = b.h + 68; ln.style.strokeDasharray = L0; ln.style.strokeDashoffset = L0 * (1 - q); };
  return g;
}

// ---- primitive 5 · REPÈRE: the reference (normal, the other, « like… »): a line drawn once, never moving
function repere(j, lv, o = {}) {
  const y = j.yOf(lv), g = mk($('scene'), 'g', { class: 'chk', opacity: 0 });
  const ln = mk(g, 'line', { x1: j.x - j.w / 2 - 34, x2: j.x + j.w / 2 + 34, y1: y, y2: y, stroke: o.color || C.brume, 'stroke-width': 10, 'stroke-linecap': 'round' });
  Object.assign(g, { y, box: [j.x - j.w / 2 - 34, y - 5, j.x + j.w / 2 + 34, y + 5] });
  g.show = t => { };
  g.draw = (t, at) => { const q = eIn((t - at + .1) / STD); g.setAttribute('opacity', q > 0 ? 1 : 0);
    const L0 = j.w + 68; ln.style.strokeDasharray = L0; ln.style.strokeDashoffset = L0 * (1 - q); };
  return g;
}

// ---- primitive 6 · VOIE (a path that exists, at rest) and 7 · IMPULSION (something travels along it)
function voie(d, o = {}) {
  const g = mk($('scene'), 'g', { class: 'chk' });
  const p = mk(g, 'path', { d, fill: 'none', stroke: o.color || C.brume, 'stroke-width': o.w || 14, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' });
  const L0 = p.getTotalLength(), bb = p.getBBox();
  Object.assign(g, { p, L: L0, box: [bb.x, bb.y, bb.x + bb.width, bb.y + bb.height], at: u => p.getPointAtLength(L0 * clamp(u)) });
  g.draw = (t, at, dur = .4) => { const q = eIn((t - at) / dur); p.style.strokeDasharray = L0; p.style.strokeDashoffset = L0 * (1 - q); g.setAttribute('opacity', q > 0 ? 1 : 0); };
  return g;
}
function impulsion(v, o = {}) {
  const g = mk($('scene'), 'g', { opacity: 0 }), col = o.color || C.ambre;
  const trail = [[150, 10, .3], [90, 14, .6], [44, 18, 1]].map(([len, w, a]) =>
    ({ len, a, el: mk(g, 'path', { d: v.p.getAttribute('d'), fill: 'none', stroke: col, 'stroke-width': w, 'stroke-linecap': 'round', opacity: a, filter: 'url(#glow)' }) }));
  const halo = mk(g, 'circle', { r: 46, fill: col === C.ambre ? 'url(#haloA)' : 'url(#haloO)' });
  const head = mk(g, 'circle', { r: o.r || 16, fill: col === C.ambre ? C.coeur : '#FFFFFF' });
  g.at = (u, a = 1) => { const s = v.L * clamp(u), q = v.p.getPointAtLength(s);
    trail.forEach(T0 => { const l = Math.min(T0.len, s); T0.el.style.strokeDasharray = `${l} ${v.L + T0.len}`; T0.el.style.strokeDashoffset = -(s - l); });
    set(halo, { cx: q.x, cy: q.y }); set(head, { cx: q.x, cy: q.y }); g.setAttribute('opacity', a); return q; };
  g.hide = () => g.setAttribute('opacity', 0);
  return g;
}

// ---- primitive 8 · BARRAGE: a named thing blocks; a coral bar falls across the path at HIT of the verb
function barrage(x, y, o = {}) {
  const g = mk($('scene'), 'g', { class: 'chk', opacity: 0 }), h = o.h || 300;
  const b = mk(g, 'rect', { x: x - 20, y: y - h / 2, width: 40, height: h, rx: 14, fill: C.corail });
  Object.assign(g, { box: [x - 20, y - h / 2, x + 20, y + h / 2] });
  g.show = (t, at) => { const q = eOver((t - (at - HIT) + FAST) / FAST); g.setAttribute('opacity', clamp(q * 3));
    g.setAttribute('transform', `translate(0 ${-80 * (1 - clamp(q, 0, 1.2))})`); };
  return g;
}

// ---- station: a node of a rail or a ring (empty at rest, lit Os when its word is said)
function station(x, y, r = 46, o = {}) {
  const g = mk($('scene'), 'g');                    // the halo is light, not a shape: only the node is checked
  const halo = mk(g, 'circle', { cx: x, cy: y, r: r * 2.4, fill: 'url(#haloO)', opacity: 0 });
  const c = mk(g, 'circle', { class: 'chk', cx: x, cy: y, r, fill: C.nuit, stroke: C.brume, 'stroke-width': 10 });
  Object.assign(g, { x, y, r, c, halo, box: [x - r - 5, y - r - 5, x + r + 5, y + r + 5] });
  g.lit = (k, col = C.os) => { set(c, { fill: mix(C.nuit, col, k), stroke: mix(C.brume, col, k) }); halo.setAttribute('opacity', .8 * k);
    halo.setAttribute('fill', col === C.ambre ? 'url(#haloA)' : 'url(#haloO)'); };
  g.pop = (t, at) => { const p = eIn((t - at) / FAST); set(g, { opacity: p, transform: `translate(${x} ${y}) scale(${.9 + .1 * p}) translate(${-x} ${-y})` }); };
  return g;
}

// ---- primitive 14 · VOILE: the rest fades (attention, perception); never a full black
function voile() { const r = mk($('scene'), 'rect', { width: 1080, height: 1920, fill: C.abyss, opacity: 0 }); return r; }

// ---- the « said » marks for an opinion (a claim is shown as SAID, never as a fact) and the open question mark
function guillemets(box) {
  const g = mk($('scene'), 'g', { opacity: 0 });
  const a = mk(g, 'text', { x: box[0] - 18, y: box[1] + 40, 'font-size': 170, fill: C.brume, 'text-anchor': 'end' }); a.textContent = '“';
  const b = mk(g, 'text', { x: box[2] + 18, y: box[3] + 110, 'font-size': 170, fill: C.brume, 'text-anchor': 'start' }); b.textContent = '”';
  g.show = (t, at) => g.setAttribute('opacity', .75 * eIn((t - at + .1) / FAST));
  return g;
}
function pointQ(x, y, o = {}) {
  const g = mk($('scene'), 'g', { class: 'chk', opacity: 0 });
  const tx = mk(g, 'text', { x, y: y + 150, 'font-size': o.size || 420, fill: 'none', stroke: C.os, 'stroke-width': 12, 'text-anchor': 'middle' }); tx.textContent = '?';
  const bb = { w: (o.size || 420) * .5 }; Object.assign(g, { box: [x - bb.w / 2, y - 160, x + bb.w / 2, y + 180] });
  g.show = (t, at) => { const p = eIn((t - at + .1) / STD); set(g, { opacity: p, transform: `translate(${x} ${y}) scale(${(.9 + .1 * p) * (1 + .02 * Math.sin(Math.max(0, t - at) * 3.2))}) translate(${-x} ${-y})` }); };
  return g;
}
