// Le cadre v2b : construit la recette au premier seek (les polices sont chargées), puis, pour toutes les recettes :
//   la caméra (designer V2-2 : arrivée ×0,955 → 1 en 0,55 s, poussée de 1,8 %, accent de +3 % à FOCUS, poussée de
//   sortie de +1 %, centre fixe (540, 640), ≤ ×1,06) et le flou d'arrivée (5 → 0 px en 0,25 s) ;
//   le PLANCHER (V2-4 : un calque hors caméra, ×1,00 → ×1,02 autour de (500, 1380)), en sous-titres « oneword » ;
//   les temps secondaires et l'approche (lot 1) ; la tenue vivante (halos ≤ 0,45, respiration du héros ±1,2 %) ;
//   le fond vivant (V2-6) ;
//   le contrôle du code : zones de la charte §3 avec la bande du sous-titre DU CLIP (SPEC.cap), au plus 3 textes, aucun
//   chevauchement, l'image pleine à 0,10 s ; nouveaux au lot 2 (V2-7) : au plus un ambre visible hors comète, aucun
//   texte sur une forme (sauf son hôte déclaré), et l'écho quand l'anti-écho est allumé — puis son journal.
let SCN = null, FOCUS = 99, HERO = [0, 0, 0, 0], FORME = null, FLASH = [], APP = -1, NODES = [], LINKS = [], NEAR = [], GLOWS = [], WRAPS = [];
let GRAIN = null, GTILE = -1;
const CAM0 = [540, 640];
const camAt = t => (.955 + .045 * p3o(t / .55)) * (1 + .018 * clamp(t / D)) * (1 + .030 * eSine((t - FOCUS + .15) / .6))
                 * (1 + .010 * p2i((t - (D - .30)) / .30));
const CAPS = WORDS.map(x => [x.t, String(x.w).toUpperCase().replace(/[^A-Z0-9'%$.,]/g, '').replace(/[.,]+$/, '')]);
const ENERGY = window.ENERGY || [];
const energyAt = t => ENERGY.length ? ENERGY[Math.max(0, Math.min(ENERGY.length - 1, Math.round(t * 30)))] : 0;
const mid = b => [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2];
const hash = s => { let h = 2166136261; for (const ch of String(s)) { h ^= ch.charCodeAt(0); h = Math.imul(h, 16777619); } return h >>> 0; };
const inter = (a, b) => Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
const area = a => Math.max(1, (a[2] - a[0]) * (a[3] - a[1]));

function build() {
  SCN = (RECETTES[S.relation] || RECETTES.mots_cles)(R);
  FOCUS = SCN.focus < 99 ? SCN.focus : D * .6;
  const ev0 = SCN.events()[0]; HERO = ev0.box; FORME = ev0.forme || ev0.box;
  (SCN.hero || []).filter(Boolean).forEach(el => { const w = document.createElementNS(NS, 'g'); w.setAttribute('class', 'amb souffle');
    el.parentNode.insertBefore(w, el); w.appendChild(el); WRAPS.push(w); });
  // the glows: behind what changed (in the camera), and behind a verdict or a number that strikes (in its own layer:
  // the floor is outside the camera); two at most, amplitudes / √2, periods 3,4 and 2,9 s
  const gl = [];
  if (SCN.glow !== false) gl.push({ box: HERO, at: FOCUS, layer: 'labels' });
  FRAPPES.forEach(fp => { if (gl.length < 2 && fp.at < 99 && !gl.some(g => g.layer === fp.layer && inter(g.box, fp.box) / Math.min(area(g.box), area(fp.box)) > .5)) gl.push(fp); });
  const amp = 1 / Math.sqrt(Math.max(1, gl.length)), per = [3.4, 2.9];
  GLOWS = gl.map((g, k) => { const [cx, cy] = mid(g.box), host = g.layer === 'plancher' ? $('plancherLueurs') : $('lueurs');
    return { at: g.at, amp, per: per[k], of: g.el || null, el: mk(host, 'ellipse', { class: 'amb', cx, cy, rx: (g.box[2] - g.box[0]) / 2 + 110, ry: (g.box[3] - g.box[1]) / 2 + 110, fill: 'url(#lueurG)', opacity: 0 }) }; });
  // COMPTE: the approach, then a secondary beat in every gap of more than 1,5 s between the pose and the frappe
  APP = FOCUS - .7 > .3 ? FOCUS - .7 : -1;
  const end = APP > 0 ? APP : FOCUS, pts = [0, ...(SCN.beats || []).filter(x => x > .05 && x < end - .2)].sort((a, b) => a - b);
  pts.push(end);
  for (let it = 0; it < 10; it++) { let added = false;
    for (let k = 0; k + 1 < pts.length; k++) { const a = pts[k], b = pts[k + 1]; if (b - a <= 1.5) continue;
      let best = (a + b) / 2, be = -1;
      for (let x = a + .45; x <= b - .45 + 1e-9; x += 1 / 30) { const e = energyAt(x); if (e > be + 1e-6) { be = e; best = x; } }
      FLASH.push(best); pts.splice(k + 1, 0, best); added = true; break; }
    if (!added) break; }
  FLASH.sort((a, b) => a - b);
  // the living background: 16 filaments sown by SPEC.id, away from the shape (+40 px), the caption band and the floor
  const seed = hash(S.id || 'x') % 100000; let q = 0; const r2 = () => rnd(seed + (q++) * 1.618);
  const avoid = [union([HERO, FORME]), ...FRAPPES.filter(f => f.layer === 'plancher').map(f => f.box)].filter(Boolean).map(b => [b[0] - 40, b[1] - 40, b[2] + 40, b[3] + 40]);
  for (let k = 0; k < 16; k++) { let x = 540, y = 1500, ok = false;
    for (let tr = 0; tr < 60 && !ok; tr++) { y = k < 10 ? 1240 + 620 * r2() : 120 + 880 * r2(); x = 60 + 960 * r2();
      ok = !avoid.some(H => x > H[0] && x < H[2] && y > H[1] && y < H[3]) && !(y > CAP.top - 30 && y < CAP.bottom + 30) && NODES.every(n => Math.hypot(n.x - x, n.y - y) > 95); }
    NODES.push({ x, y, r: r2() < .6 ? 5 : 8, ph: 2 * Math.PI * r2() }); }
  const deg = NODES.map(() => 0), pairs = [];
  NODES.forEach((a, i) => NODES.forEach((b, j) => { if (j > i) { const d = Math.hypot(a.x - b.x, a.y - b.y); if (d < 300) pairs.push([d, i, j]); } }));
  pairs.sort((a, b) => a[0] - b[0]).forEach(([d, i, j]) => { if (deg[i] < 2 && deg[j] < 2) { deg[i]++; deg[j]++;
    LINKS.push({ i, j, el: mk($('fil'), 'line', { stroke: C.brume, 'stroke-width': 2.5, opacity: .13, 'stroke-linecap': 'round' }) }); } });
  NODES.forEach(n => { n.el = mk($('fil'), 'circle', { r: n.r, fill: C.brume, opacity: .22 }); });
  const [hx, hy] = mid(HERO);
  NEAR = NODES.map((n, k) => [Math.hypot(n.x - hx, n.y - hy), k]).sort((a, b) => a[0] - b[0]).slice(0, 2).map(x => x[1]);
  const cv = $('grain'); if (cv && cv.getContext) { const gx = cv.getContext('2d');
    const tiles = [0, 1, 2, 3].map(k => { const c = document.createElement('canvas'); c.width = c.height = 512; const x = c.getContext('2d');
      const im = x.createImageData(512, 512); let s = ((hash(S.id || 'x') ^ Math.imul(k + 1, 2654435761)) | 1);
      for (let i = 0; i < im.data.length; i += 4) { s ^= s << 13; s ^= s >>> 17; s ^= s << 5; const v = s & 255; im.data[i] = im.data[i + 1] = im.data[i + 2] = v; im.data[i + 3] = 255; }
      x.putImageData(im, 0, 0); return gx.createPattern(c, 'repeat'); });
    GRAIN = { gx, tiles }; }
}

window.seek = t => {
  if (!SCN) build();
  const s = camAt(t), [ox, oy] = CAM0;
  $('cam').setAttribute('transform', `translate(${ox} ${oy}) scale(${s}) translate(${-ox} ${-oy})`);
  if (t < .25) { $('cam').setAttribute('filter', 'url(#arrive)'); $('arriveB').setAttribute('stdDeviation', (5 * (1 - p3o(t / .25))).toFixed(2)); }
  else $('cam').removeAttribute('filter');
  const fs = 1 + .02 * clamp(t / D);                                   // the floor: ×1,00 → ×1,02 about (500, 1380)
  $('plancher').setAttribute('transform', `translate(500 1380) scale(${fs.toFixed(4)}) translate(-500 -1380)`);
  const [hx, hy] = mid(HERO), pl = eIn(t / 1.2), lx = 540 + (hx - 540) * pl, ly = 640 + (hy - 640) * pl;
  set($('light'), { cx: lx, cy: ly, opacity: (.95 * (1 + .05 * Math.sin(2 * Math.PI * t / 4.2))).toFixed(3) });
  const bs = Math.min(1.15, 1 + .03 * t);
  $('bg').setAttribute('transform', `translate(${lx} ${ly}) scale(${bs}) translate(${-lx} ${-ly})`);
  const bump = clamp(Math.sin(Math.PI * clamp((t - FOCUS) / .6)), 0, 1);
  NODES.forEach((n, k) => { n.cx = n.x + 10 * Math.sin(2 * Math.PI * t / 9 + n.ph); n.cy = n.y + 7 * Math.sin(2 * Math.PI * t / 11.7 + n.ph);
    const b = NEAR.includes(k) ? bump : 0;
    set(n.el, { cx: n.cx.toFixed(1), cy: n.cy.toFixed(1), fill: mix(C.brume, C.os, b), opacity: (.22 + .18 * b).toFixed(3) }); });
  LINKS.forEach(l => { const a = NODES[l.i], b = NODES[l.j]; set(l.el, { x1: a.cx.toFixed(1), y1: a.cy.toFixed(1), x2: b.cx.toFixed(1), y2: b.cy.toFixed(1) }); });
  if (GRAIN) { const k = Math.floor(t * 12) % 4; if (k !== GTILE) { GRAIN.gx.fillStyle = GRAIN.tiles[k]; GRAIN.gx.fillRect(0, 0, 1080, 1920); GTILE = k; } }
  SCN.seek(t);
  let ek = 0;
  FLASH.forEach(tf => { if (t > tf && t < tf + .3) ek = Math.max(ek, .8 * Math.sin(Math.PI * (t - tf) / .3)); });
  if (APP > 0) ek = Math.max(ek, t < FOCUS ? .6 * eOut((t - APP) / .7) : .6 * (1 - p3o((t - FOCUS) / .4)));
  if (SCN.edge) SCN.edge(ek);
  GLOWS.forEach(g => { const x = t - g.at;
    const ko = g.of ? clamp(+(g.of.getAttribute('opacity') || 0)) : 1;   // a glow fades with its text (champ: the old state's name)
    g.el.setAttribute('opacity', x <= 0 ? 0 : (ko * g.amp * (.28 * p3o(x / .35) + (x > .35 ? .03 * Math.sin(2 * Math.PI * (x - .35) / g.per) : 0))).toFixed(3)); });
  const tl = FOCUS + .6, sc = t > tl ? 1 + .012 * Math.sin(2 * Math.PI * (t - tl) / 3.2) : 1;
  WRAPS.forEach(w => w.setAttribute('transform', `translate(${hx} ${hy}) scale(${sc.toFixed(5)}) translate(${-hx} ${-hy})`));
  if (S.caption) { let w = ''; for (const [a, x] of CAPS) if (t >= a) w = x; $('cap').textContent = w; }
};

const effOp = el => { let o = 1; for (let n = el; n && n.nodeType === 1 && n.tagName !== 'svg'; n = n.parentNode) {
  if (n.getAttribute('display') === 'none') return 0; const a = n.getAttribute('opacity'); if (a !== null) o *= +a; } return o; };
const ZONES = b => { const v = [];
  if (b.top < 110) v.push('top');
  if (b.right > 680 && b.top < 270 && b.bottom > 110) v.push('channel box');
  if (b.top < 1000 && (b.left < 90 || b.right > 990)) v.push('margin');
  if (b.bottom > 1000 && b.top < 1700 && b.right > 940) v.push('buttons');
  if (b.bottom > CAP.top && b.top < CAP.bottom) v.push('caption band');
  if (b.bottom > 1536) v.push('bottom 20%');
  return v; };
const unionChk = th => { let u = null;
  document.querySelectorAll('.chk').forEach(el => { if (effOp(el) < th) return; const b = el.getBoundingClientRect(); if (!b.width && !b.height) return;
    u = u ? [Math.min(u[0], b.left), Math.min(u[1], b.top), Math.max(u[2], b.right), Math.max(u[3], b.bottom)] : [b.left, b.top, b.right, b.bottom]; });
  return u || [0, 0, 0, 0]; };
// the amber budget (V2-7.5): the visible leaf shapes painted amber (fill or stroke), outside the comet
const AMB = hex(C.ambre), isAmb = c => { if (!c || c[0] !== '#' || c.length !== 7) return false; const v = hex(c); return v.every((x, i) => Math.abs(x - AMB[i]) <= 24); };
const ambers = () => [...document.querySelectorAll('#scene *, #labels *, #plancher *')].filter(e => !e.closest('.comete') && !['g', 'defs', 'clipPath', 'linearGradient', 'radialGradient', 'stop', 'filter'].includes(e.tagName)
  && (isAmb(e.getAttribute('fill')) || isAmb(e.getAttribute('stroke'))) && effOp(e) >= .3 && (() => { const b = e.getBoundingClientRect(); return b.width + b.height > 0; })());
// text on a shape (V2-7): a visible text never covers a visible shape by more than 4 px, except its declared host
const surForme = () => { const out = [];
  const txts = [...document.querySelectorAll('.txt')].filter(g => effOp(g) > .5);
  const shapes = [...document.querySelectorAll('.chk')].filter(e => !e.classList.contains('txt') && !e.closest('.txt') && effOp(e) >= .05);
  for (const tx of txts) { const a = tx.getBoundingClientRect(), host = tx.getAttribute('data-hote');
    for (const sh of shapes) { if (sh.contains(tx) || tx.contains(sh)) continue;
      if (host && (sh.getAttribute('data-id') === host || (sh.closest && sh.closest(`[data-id="${host}"]`)) || sh.querySelector && sh.querySelector(`[data-id="${host}"]`))) continue;
      const b = sh.getBoundingClientRect(); if (!b.width && !b.height) continue;
      const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left), oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (ox > 4 && oy > 4) out.push(`${tx.text || tx.textContent} sur ${sh.tagName}.${sh.getAttribute('class')}`); } }
  return out; };
const capWordsAt = t => { for (const [s, e, is] of CAPCH) if (t >= s && t < e) return is.map(i => { const w = WORDS.find(x => x.i === i); return w ? norm(w.w) : ''; }); return []; };
window.check = () => { const out = new Set(), r = x => x.toFixed(0);
  for (let k = 0; k <= 9; k++) { const t = Math.min(D - .001, k * D / 9); window.seek(t);
    document.querySelectorAll('.chk').forEach(el => { if (effOp(el) < .05) return; const b = el.getBoundingClientRect();
      if (!b.width && !b.height) return;
      ZONES(b).forEach(z => out.add(`${el.tagName}.${el.getAttribute('class')} ${z} @${t.toFixed(1)}s (${r(b.left)},${r(b.top)})-(${r(b.right)},${r(b.bottom)})`)); });
    const vis = [...document.querySelectorAll('.txt')].filter(g => effOp(g) > .5);
    if (vis.length > 3) out.add(`${vis.length} textes à l'écran @${t.toFixed(1)}s (3 au plus)`);
    const bx = vis.map(g => g.getBoundingClientRect());
    for (let i = 0; i < bx.length; i++) for (let j = i + 1; j < bx.length; j++) {
      const a = bx[i], b = bx[j]; if (a.left < b.right - 4 && a.right > b.left + 4 && a.top < b.bottom - 4 && a.bottom > b.top + 4)
        out.add(`textes qui se chevauchent @${t.toFixed(1)}s`); }
    const am = ambers(); if (am.length > 1) out.add(`${am.length} ambres à l'écran @${t.toFixed(1)}s (1 au plus hors comète)`);
    surForme().forEach(x => out.add(`texte sur une forme @${t.toFixed(1)}s : ${x}`)); }
  // V2-5 (lot 3): every picto drawn comes from the validated library
  const lib = (window.PICTOS && window.PICTOS.cles) || [];
  document.querySelectorAll('[data-picto]').forEach(p => { if (!lib.includes(p.getAttribute('data-picto'))) out.add(`picto hors bibliothèque : ${p.getAttribute('data-picto')}`); });
  window.seek(.10); const u = unionChk(.05), W = u[2] - u[0], Hh = u[3] - u[1];
  if (Math.max(W, Hh) < 500 || Math.min(W, Hh) < 180) out.add(`image trop vide @0.10s : union des formes ${r(W)}×${r(Hh)} (il faut 500×180)`);
  if (AE) echos().forEach(x => out.add(`écho : ${x}`));
  return [...out]; };
const norm = s => String(s || '').toUpperCase().replace(/[^A-Z0-9%]/g, '');
const appear = () => { const txts = [...document.querySelectorAll('.txt')], seen = new Map();
  for (let f = 0; f <= Math.round(D * 30); f++) { const t = Math.min(D - .001, f / 30); window.seek(t);
    txts.forEach(g => { if (!seen.has(g) && effOp(g) > .5) seen.set(g, t); }); }
  return seen; };
// the echo (V2-7.3): when a text appears, the caption on screen shows none of its words of 4 letters or more
const echos = () => { const out = []; appear().forEach((t, g) => { const mine = String(g.text || g.textContent || '').toUpperCase().split(/[^A-Z0-9%']+/).map(norm).filter(w => w.length >= 4);
    const cw = capWordsAt(t); const hitw = mine.filter(w => cw.includes(w)); if (hitw.length) out.push(`${g.text || g.textContent} @${t.toFixed(2)}s (${hitw.join(', ')})`); });
  window.seek(0); return out; };
const wordOfText = txt => { const n = norm(txt); let best = 99;
  for (const v of Object.values(R)) for (const x of (Array.isArray(v) ? v : [v])) if (x && typeof x === 'object' && x.label && norm(x.label) === n) best = Math.min(best, T(x));
  return best; };
window.journal = () => { if (!SCN) window.seek(0);
  const pts = [0, ...(SCN.beats || []), ...FLASH, ...(APP > 0 ? [APP] : [])].filter(x => x >= 0 && x < FOCUS).sort((a, b) => a - b); pts.push(FOCUS);
  let gap = 0; for (let k = 1; k < pts.length; k++) gap = Math.max(gap, pts[k] - pts[k - 1]);
  const seen = appear(), avant = [];
  seen.forEach((tv, g) => { const tw = wordOfText(g.text || (g.textContent || '')); if (tw < 99 && tv < tw - .12) avant.push(`${g.text} ${(tw - tv).toFixed(2)} s avant`); });
  // the rule of thirds (V2-9.4): at most a third of the shapes in main motion at once (> 10 px or > 1,5 % in 1/30 s)
  const shapes = [...document.querySelectorAll('.chk')]; let prev = null, tiers = 0, amb = 0;
  for (let f = 0; f <= Math.round(D * 30); f += 1) { const t = Math.min(D - .001, f / 30); window.seek(t);
    $('cam').removeAttribute('transform'); $('plancher').removeAttribute('transform');   // the camera moves everything: not counted
    WRAPS.forEach(w => w.removeAttribute('transform'));                              // nor the breathing (secondary)
    const bs = shapes.map(e => effOp(e) >= .05 ? e.getBoundingClientRect() : null);
    if (prev) { let mv = 0, vis = 0; bs.forEach((b, k) => { if (!b) return; vis++; const p = prev[k]; if (!p) { mv++; return; }
        // a main motion moves an edge by more than 1,5 px in one frame (45 px/s): the breathing, the drift and the
        // background stay far below it
        const d = Math.max(Math.abs(b.left - p.left), Math.abs(b.top - p.top), Math.abs(b.right - p.right), Math.abs(b.bottom - p.bottom));
        if (d > 1.5) mv++; });
      if (vis) tiers = Math.max(tiers, mv / vis); }
    prev = bs; amb = Math.max(amb, ambers().length); }
  window.seek(0);
  const tw = FOCUS_W < 99 ? FOCUS_W : FOCUS + HIT;
  return { focus_t: +FOCUS.toFixed(3), mot_t: +tw.toFixed(3), part: +(tw / D).toFixed(3), plus_long_trou: +gap.toFixed(2), tenue: +(D - FOCUS).toFixed(2),
    etiquettes_avant: avant, heros_px: Math.round(Math.max(FORME[2] - FORME[0], FORME[3] - FORME[1])), change_px: Math.round(Math.max(HERO[2] - HERO[0], HERO[3] - HERO[1])),
    eclats: FLASH.map(x => +x.toFixed(2)), approche: APP > 0 ? +APP.toFixed(2) : null, lueurs: GLOWS.length, ambre_max: amb, tiers_max: +tiers.toFixed(2),
    pictos: [...document.querySelectorAll('[data-picto]')].map(p => p.getAttribute('data-picto')), avis: typeof AVIS !== 'undefined' ? AVIS : null,
    cap: CAP.style || null, plancher: !!FLOOR, anti_echo: AE, echos: AE ? echos() : null, decoupe: S.decoupe || null }; };
window.gateEvents = () => { window.seek(0); return SCN && SCN.events ? SCN.events() : []; };
Promise.all(['64px Mont'].concat(window.FONTS_EXTRA || []).map(f => document.fonts.load(f))).then(() => window.seek(0));
