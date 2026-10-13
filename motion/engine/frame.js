// Le cadre : construit la recette au premier seek (les polices sont chargées), caméra (poussée linéaire + accent sur
// le mot-sens, ≤ ×1,05), fond vivant (≤ 0,5 % de dérive), sous-titre simulé si demandé, et le contrôle du code
// (zones de la charte §3 sur 10 images, au plus 3 textes à l'écran) — le seul contrôle qui tourne en prod.
let SCN = null, FOCUS = 99;
const CAM0 = [540, 640];
const camAt = t => 1 + .022 * clamp(t / D) + .025 * eSine((t - FOCUS + .15) / .6);
const CAPS = (window.WORDS || []).map(x => [x.t, String(x.w).toUpperCase().replace(/[^A-Z0-9'%$.,]/g, '').replace(/[.,]+$/, '')]);
window.seek = t => {
  if (!SCN) { const f = RECETTES[S.relation] || RECETTES.mots_cles; SCN = f(R); FOCUS = SCN.focus < 99 ? SCN.focus : D * .5; }
  const s = camAt(t), [ox, oy] = CAM0;
  $('cam').setAttribute('transform', `translate(${ox} ${oy}) scale(${s}) translate(${-ox} ${-oy})`);
  $('pool').setAttribute('transform', `translate(${8 * Math.sin(t * .7)} ${6 * Math.cos(t * .5)})`);
  $('grainT').setAttribute('seed', 1 + Math.floor(t * 12));
  SCN.seek(t);
  if (S.caption) { let w = ''; for (const [a, x] of CAPS) if (t >= a) w = x; $('cap').textContent = w; }
};
const effOp = el => { let o = 1; for (let n = el; n && n.nodeType === 1 && n.tagName !== 'svg'; n = n.parentNode) {
  if (n.getAttribute('display') === 'none') return 0; const a = n.getAttribute('opacity'); if (a !== null) o *= +a; } return o; };
const ZONES = b => { const v = [];
  if (b.top < 110) v.push('top');
  if (b.right > 680 && b.top < 270 && b.bottom > 110) v.push('channel box');
  if (b.top < 1000 && (b.left < 90 || b.right > 990)) v.push('margin');
  if (b.bottom > 1000 && b.top < 1700 && b.right > 940) v.push('buttons');
  if (b.bottom > 1014 && b.top < 1214) v.push('caption band');
  if (b.bottom > 1536) v.push('bottom 20%');
  return v; };
window.check = () => { const out = new Set(), r = x => x.toFixed(0);
  for (let k = 0; k <= 9; k++) { const t = Math.min(D - .001, k * D / 9); window.seek(t);
    document.querySelectorAll('.chk').forEach(el => { if (effOp(el) < .05) return; const b = el.getBoundingClientRect();
      if (!b.width && !b.height) return;
      ZONES(b).forEach(z => out.add(`${el.tagName}.${el.getAttribute('class')} ${z} @${t.toFixed(1)}s (${r(b.left)},${r(b.top)})-(${r(b.right)},${r(b.bottom)})`)); });
    const vis = [...document.querySelectorAll('.txt')].filter(g => effOp(g) > .5);
    if (vis.length > 3) out.add(`${vis.length} textes à l'écran @${t.toFixed(1)}s (3 au plus)`);
    const bx = vis.map(g => g.getBoundingClientRect());              // two texts never overlap
    for (let i = 0; i < bx.length; i++) for (let j = i + 1; j < bx.length; j++) {
      const a = bx[i], b = bx[j]; if (a.left < b.right - 4 && a.right > b.left + 4 && a.top < b.bottom - 4 && a.bottom > b.top + 4)
        out.add(`textes qui se chevauchent @${t.toFixed(1)}s`); } }
  return [...out]; };
window.gateEvents = () => { window.seek(0); return SCN && SCN.events ? SCN.events() : []; };
document.fonts.load('64px Mont').then(() => window.seek(0));
