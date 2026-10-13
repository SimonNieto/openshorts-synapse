// Les recettes v2b (lot 2 de SPEC_V2) : les gabarits du designer (direction_v2 V2-4), avec les formes finies (V2-8) et
// les tuiles (V2-7), sur le battement du lot 1 (POSE · COMPTE · FRAPPE · TENUE). Chaque recette rend
// { seek(t), events(), focus, hero, edge(k), beats, glow }. Aucun réglage à la main par scène.
//   COLONNE-SOLO (niveau, référence), COLONNES-DUO (contraste), RAIL-V (étapes, trajet, blocage, transformation),
//   ANNEAU (boucle), BALANCE (débat), BULLE (question), AFFICHE (mots-clés), CHAMP (gardé).
//   Le PLANCHER (sous-titres « oneword ») reçoit UN élément : le chiffre dit, sinon le verdict ; en « premium », cet
//   élément va au bas de la scène.
// Banc v2a (13/10) : plus aucune capsule vide ni ligne vide ; la perte d'une colonne laisse la piste vide avec le
// repère d'avant ; le repère d'une référence apparaît sur place ; la dernière station est un médaillon héros.
window.RECETTES = {};
const lvl = (x, d) => (x === undefined || x === null || isNaN(+x)) ? d : clamp(+x, 0, 1.05);
const first = (...ts) => Math.min(...ts.filter(x => x < 99), 99);
const beatsOf = (...ts) => ts.filter(x => x < 99).map(x => x - .1);
const amplitude = (f0, f1, down, said) => { if (said) return [f0, f1];
  if (down) { f0 = Math.max(f0, .5); f1 = Math.min(f1, f0 - .35); } else { f0 = Math.min(f0, .55); f1 = Math.max(f1, f0 + .35); }
  return [clamp(f0, .06, 1), clamp(f1, .06, 1)]; };
// V2-5 (lot 3): the picto of the thing named, from the closed lexicon (no AI). In a clip of OPINION (debate, question,
// key words) no organ at all: only things (person, doctor, document, phone…) — never a mechanism he did not state.
const ARG = ['debat', 'question', 'mots_cles'].includes(S.relation);
const ORGANES = new Set(['cerveau', 'oeil', 'oreille', 'coeur', 'poumons', 'estomac', 'muscle', 'corps', 'neurone']);
const cleOf = r => { if (!(window.pictoPour && r && r.label)) return null; const k = window.pictoPour(String(r.label));
  return k && ARG && ORGANES.has(k) ? null : k; };
// the register of what is said (V2-10.3: sans serif = a fact, serif = someone says it): the director's own words
const AVIS = /opinion|avis|selon (lui|elle)|il pense|elle pense|hypoth|peut-être|il croit|d'après (lui|elle)|il trouve/i.test(`${S.phrase_spectateur || ''} ${S.why || ''}`);
// THE FLOOR: ONE element (the number said, else the verdict); in « premium » it goes to the bottom of the scene
function auPlancher(kind, text, at) {
  const Z = FLOORSPOT.box, cx = (Z[0] + Z[2]) / 2, cy = (Z[1] + Z[3]) / 2;
  return kind === 'chiffre'
    ? chiffre(text, cx, cy, { zone: Z, layer: FLOORSPOT.layer, size: FLOORSPOT.size, maxw: Z[2] - Z[0], at })
    : verdict(text, cx, cy, { zone: Z, layer: FLOORSPOT.layer, size: FLOORSPOT.hero, maxw: Z[2] - Z[0], min: 84, at });
}
// the one amber of the image (V2-7.5): a 10 px line under the hero word, traced in 0,30 s once it has struck
function sousLe(V) { const b = V.box; return souligne(b[0] + 6, b[2] - 6, b[3] + 16, { layer: V.layer }); }
// a rail tile: beside its medallion, centred on it; never in the top band (the channel cartouche is on its right):
// pushed down just under the band when it would reach into it, then a little lower
const railCands = m => { const x = m.x + m.r + 40; return [[x, Math.max(m.y, 362), 'start'], [x, Math.max(m.y, 384), 'start'], [x, Math.max(m.y, 384) + 60, 'start']]; };
// RAIL-V: the medallions on x 270, the hero (the last, the arrival) r 120, the others r 100 / 84 / 64, equal gaps
function railV(n, heroAt = 'bas', x = 270) {
  // the top medallion's centre stays at y ≥ 350, so the tile beside it is under the top band (cartouche on the right)
  const rs = n <= 2 ? 100 : n === 3 ? 84 : 56, rH = n >= 4 ? 100 : 120, bot = 969;
  const rr = [...Array(n)].map((_, k) => (heroAt === 'bas' ? k === n - 1 : k === 0) ? rH : rs);
  const top = Math.max(172, 350 - rr[0]);
  const gap = (bot - top - rr.reduce((a, b) => a + 2 * b, 0)) / Math.max(1, n - 1);
  let y = top; const ys = rr.map(r => { const c = y + r; y += 2 * r + gap; return c; });
  return ys.map((yy, k) => ({ x, y: yy, r: rr[k] }));
}

// R1 · une quantité monte ou baisse (COLONNE-SOLO). POSE : la colonne à son niveau d'avant. FRAPPE : sur le verbe, la
// colonne bouge (75 % de la course en 0,25 s) ; le repère d'avant reste ; le verdict ou le chiffre frappe au plancher.
RECETTES.niveau = r => {
  const down = r.sens !== 'hausse', said = !!r.valeur;
  const [f0, f1] = amplitude(lvl(r.depart, down ? .82 : .3), lvl(r.arrivee, down ? .38 : .86), down, said);
  const col = colonne(160, 200, 380, 950), sol = filet(131, 949, 966), taken = [[132, 190, 408, 970]];
  const rm = cleOf(r.quantite) ? r.quantite : (r.cause && cleOf(r.cause) ? r.cause : null);
  const M = rm ? medaillon(690, 470, 130, { cle: cleOf(rm), at: T(rm) }) : null; if (M) taken.push(M.box);
  const tq = TL(r.quantite), tv = TL(r.verbe), tn = said ? TL(r.valeur, T(r.valeur)) : 99, tc = r.cause ? TL(r.cause) : 99;
  const F = focusAt(T(r.verbe));
  const PQ = placeTuile(L(r.quantite), M ? [[430, 742, 'start'], [430, 860, 'start']] : [[430, 470, 'start'], [430, 600, 'start'], [430, 742, 'start']], taken, { maxw: 519 });
  const PC = r.cause ? placeTuile(L(r.cause), [[430, 860, 'start'], [430, 742, 'start'], [430, 600, 'start'], [430, 360, 'start']], taken, { maxw: 519 }) : null;
  const N = said ? auPlancher('chiffre', L(r.valeur), tn) : null;
  const V = !said && r.verbe && r.verbe.label ? auPlancher('verdict', L(r.verbe), tv) : null, U = V ? sousLe(V) : null;
  const forme = union([col.box, M && M.box]);
  return { focus: F, hero: [col], edge: k => col.edge(k), beats: beatsOf(tq, tc, tn, M ? T(r.quantite) : 99),
    events: () => [{ name: 'verbe', t: F, box: col.box, forme }],
    seek(t) { col.show(t); sol.show(t); col.level(f0 + (f1 - f0) * eOver((t - F) / .6), f0, eIn((t - F) / .3));
      if (M) { M.pop(t); M.lit(eIn((t - T(rm) + HIT) / FAST)); M.pulse(t, T(rm) - HIT); M.idle(t); }
      PQ.show(t, tq); if (PC) PC.show(t, tc, F); if (N) N.show(t, tn); if (V) { V.show(t, tv); U.show(t, Math.max(tv, F + HIT) + .2); } } };
};

// R10 · comparaison à une référence (COLONNE-SOLO + la ligne du repère sur toute la scène). POSE : la colonne. COMPTE :
// sur le verbe d'équivalence, la ligne APPARAÎT SUR PLACE, sans nom. FRAPPE : sur le mot du repère, la quantité
// descend (ou monte) jusqu'à elle, et son nom sort.
RECETTES.reference = r => {
  const pos = r.position || 'atteint', ref = .58, down = r.sens === 'baisse' || pos === 'sous', said = !!r.valeur;
  let f0 = lvl(r.depart, down ? .95 : .2);
  const f1 = pos === 'depasse' ? (down ? .3 : .95) : pos === 'sous' ? ref - .16 : ref;
  if (!said) f0 = f1 < f0 ? Math.min(1, Math.max(f0, f1 + .35)) : Math.max(.05, Math.min(f0, f1 - .35));
  const col = colonne(160, 200, 380, 950), sol = filet(131, 949, 966), yr = col.yOf(ref), rp = ligneRef(131, 949, yr);
  const taken = [[132, 190, 408, 970], rp.box];
  const cle = cleOf(r.quantite), M = cle ? medaillon(510, 742, 80, { cle, at: T(r.quantite) }) : null; if (M) taken.push(M.box);
  const tq = TL(r.quantite), tr = TL(r.reference), tv = T(r.verbe), tn = said ? TL(r.valeur, T(r.valeur)) : 99;
  const F = focusAt(T(r.reference)), tLine = Math.max(.3, Math.min(tv < 99 ? tv : F - .6, F - .5));
  const PR = placeTuile(L(r.reference), [[949, yr - 72, 'end'], [949, yr - 98, 'end'], [949, yr - 120, 'end'], [949, yr + 72, 'end'], [949, yr + 98, 'end']], taken, { maxw: 519, strict: true });
  const PQ = placeTuile(L(r.quantite), M ? [[610, 742, 'start', 339], [430, 880, 'start', 519], [430, 360, 'start', 519]]
    : [[430, 742, 'start'], [430, 860, 'start'], [430, 360, 'start'], [430, 600, 'start']], taken, { maxw: 519 });
  const N = said ? auPlancher('chiffre', L(r.valeur), tn) : null;
  const forme = union([col.box, rp.box]);
  return { focus: F, hero: [col], edge: k => col.edge(k), beats: beatsOf(tq, tn).concat([tLine - .1]),
    events: () => [{ name: 'contact', t: F, box: col.box, forme }],
    seek(t) { col.show(t); sol.show(t); col.level(f0 + (f1 - f0) * eOver((t - F) / .6), f0, eIn((t - F) / .3)); rp.show(t, tLine);
      if (M) { M.pop(t); M.lit(eIn((t - T(r.quantite) + HIT) / FAST)); M.pulse(t, T(r.quantite) - HIT); M.idle(t); }
      PR.show(t, tr); PQ.show(t, tq); if (N) N.show(t, tn); } };
};

// R2 · cause → effet : la cause en médaillon, la voie, l'effet en colonne ; sur le lien, la comète part et ACCÉLÈRE ;
// elle touche l'effet au HIT, qui change dans l'image qui suit.
RECETTES.cause_effet = r => {
  const up = r.sens_effet === 'hausse';
  const s = medaillon(270, 420, 110, { cle: cleOf(r.cause), at: T(r.cause) }), col = colonne(620, 320, 840, 950);
  const v = voie('M396 420 L 604 420'), imp = impulsion(v, { color: C.os }), taken = [s.box, [592, 310, 868, 960], v.box];
  const tc = TL(r.cause), tl = T(r.lien), te = TL(r.effet), tn = r.valeur ? TL(r.valeur, T(r.valeur)) : 99;
  const F = focusAt(first(T(r.effet), tl + .7)), tArr = F;
  const tGo = tl < tArr - .3 ? Math.max(tl, tArr - 1.2, .3) : Math.max(tArr - .7, .3);
  const PC = placeTuile(L(r.cause), [[270, 600], [131, 600, 'start'], [131, 742, 'start']], taken, { maxw: 440 });
  const PE = placeTuile(L(r.effet), [[580, 742, 'end'], [580, 860, 'end'], [580, 600, 'end']], taken, { maxw: 440 });
  const N = r.valeur ? auPlancher('chiffre', L(r.valeur), tn) : null;
  const f0 = up ? .3 : .82, f1 = up ? .88 : .36;
  return { focus: F, hero: [col], edge: k => col.edge(k), beats: beatsOf(tc, te < F ? te : 99, tn).concat([tGo]),
    events: () => [{ name: 'effet', t: F, box: col.box, forme: union([s.box, col.box]) }],
    seek(t) { s.pop(t); s.lit(eIn((t - T(r.cause) + .1) / FAST)); s.idle(t); v.draw(t); col.show(t);
      if (t >= tGo && t < tArr + .18) imp.at(eOut((t - tGo) / Math.max(.2, tArr - tGo)), t < tArr ? 1 : 1 - (t - tArr) / .18); else imp.hide();
      col.level(f0 + (f1 - f0) * eOver((t - tArr - .033) / .6), f0, eIn((t - tArr) / .3));
      PC.show(t, tc, tGo + .3); PE.show(t, first(te, tArr + HIT)); if (N) N.show(t, tn); } };
};

// R3 · contraste A / B (COLONNES-DUO) : les deux colonnes au même niveau dès la pose ; sur la bascule, SEULE la colonne
// qui gagne bouge ; l'autre reste le repère de l'écart. Les noms au-dessus ; ce qu'on compare au plancher.
const EMO = new RegExp('^(' + ['scared|scare|scares|scary|afraid|fear|fears|feared|frightened|frighten|frightens|terrified|terrify',
  'anxious|anxiety|worried|worry|worries|nervous|love|loves|hate|hates|dislike|prefer|prefers|enjoy|enjoys',
  'happy|happier|sad|angry|upset|comfortable|uncomfortable|disgust|disgusted|panic|panics'].join('|') + ')$', 'i');
const said = i => { const w = WORDS.find(x => x.i === i); return w ? String(w.w).replace(/[^A-Za-z'-]/g, '') : ''; };
RECETTES.contraste = r => {
  const be = r.bascule && typeof r.bascule === 'object' ? said(r.bascule.i) : '';
  if (EMO.test(be)) return contrasteEmotion(r, be);
  const win = r.gagnant === 'a' ? 0 : 1, more = r.sens !== 'moins';
  const ca = colonne(190, 470, 390, 960), cb = colonne(600, 470, 800, 960), sol = filet(131, 949, 970), taken = [[162, 460, 418, 975], [572, 460, 828, 975]];
  const ta = TL(r.a), tb = TL(r.b), tq = r.quoi ? TL(r.quoi) : 99, tk = first(T(r.bascule), T(r.b) + .4);
  const F = focusAt(tk), W = win === 0 ? ca : cb, O = win === 0 ? cb : ca;
  // the two names: each above its own column, or slid; A may climb into the top-left band to leave room for B
  let PA = null, PB = null;
  for (const ca0 of [[290, 380, null, 404], [131, 380, 'start', 818], [131, 262, 'start', 526]]) {
    const tk0 = taken.slice(); const a0 = placeTuile(L(r.a), [ca0], tk0, { maxw: 818, strict: true });
    if (a0.force) { a0.remove(); continue; }
    const b0 = placeTuile(L(r.b), [[700, 380, null, 498], [949, 380, 'end', 818]], tk0, { maxw: 818, strict: true });
    if (b0.force) { a0.remove(); b0.remove(); continue; }
    PA = a0; PB = b0; taken.splice(0, taken.length, ...tk0); break; }
  if (!PA) { PA = placeTuile(L(r.a), [[290, 380]], taken, { maxw: 818 }); PB = placeTuile(L(r.b), [[700, 380]], taken, { maxw: 818 }); }
  const Q = r.quoi ? auPlancher('verdict', L(r.quoi), tq) : null;
  const base = .5, hi = more ? .94 : .12;
  return { focus: F, hero: [W], edge: k => W.edge(k), beats: beatsOf(ta, tb, tq < F ? tq : 99),
    events: () => [{ name: 'bascule', t: F, box: W.box, forme: union([ca.box, cb.box]) }],
    seek(t) { ca.show(t); cb.show(t); sol.show(t);
      W.level(base + (hi - base) * eOver((t - F) / .6), base, eIn((t - F) / .3)); O.level(base, base, 0);
      PA.show(t, ta, win === 0 ? 99 : F); PB.show(t, tb, win === 1 ? 99 : F); if (Q) Q.show(t, tq); } };
};

// R3 bis · contraste d'une ÉMOTION : deux médaillons côte à côte (le picto de la chose quand elle en a un), au même repos ;
// sur la bascule, SEUL le côté qui gagne s'allume, grandit (ressort) et pulse ; l'autre reste au repos. L'émotion dite
// frappe au plancher (au plus 3 textes : ce qu'on compare n'est pas montré, c'est noté au journal).
function contrasteEmotion(r, be) {
  const win = r.gagnant === 'a' ? 0 : 1, F = focusAt(T(r.bascule));
  const A = medaillon(300, 560, 140, { cle: cleOf(r.a), at: T(r.a) }), B = medaillon(780, 560, 140, { cle: cleOf(r.b), at: T(r.b) });
  const W = win === 0 ? A : B, taken = [A.box, B.box];
  const ta = TL(r.a), tb = TL(r.b);
  const PA = placeTuile(L(r.a), [[300, 795], [131, 795, 'start']], taken, { maxw: 380 }), PB = placeTuile(L(r.b), [[780, 795], [912, 795, 'end']], taken, { maxw: 360 });
  const V = auPlancher('verdict', be.toUpperCase(), TL(r.bascule, Math.max(T(r.bascule), F + HIT)));
  return { focus: F, hero: [W], edge: k => W.edge(k), beats: beatsOf(ta, tb), quoi_non_montre: !!r.quoi,
    events: () => [{ name: 'bascule', t: F, box: W.box, forme: union([A.box, B.box]) }],
    seek(t) { [A, B].forEach(m => { m.pop(t); m.idle(t); });
      A.lit(.35 * eIn((t - T(r.a) + HIT) / FAST) * (win === 0 ? 1 : 1 - .5 * eIn((t - F) / .3)) + (win === 0 ? .65 * eIn((t - F) / FAST) : 0));
      B.lit(.35 * eIn((t - T(r.b) + HIT) / FAST) * (win === 1 ? 1 : 1 - .5 * eIn((t - F) / .3)) + (win === 1 ? .65 * eIn((t - F) / FAST) : 0));
      W.grow(1 + .12 * SPR_HERO.f((t - F) / SPR_HERO.dur)); W.pulse(t, F);
      PA.show(t, ta, win === 0 ? 99 : F); PB.show(t, tb, win === 1 ? 99 : F); V.show(t, Math.max(T(r.bascule), F + HIT)); } };
}

// R4 · étapes, séquence (RAIL-V) : le rail entier et toutes les stations vides dès la pose (on voit combien viennent) ;
// chaque station s'allume sur son mot ; la DERNIÈRE est un médaillon héros (r 120) : elle reçoit le signal (ambre),
// grandit (ressort) et son nom FRAPPE au plancher. Au plus 3 textes : le sujet, l'avant-dernière et la dernière.
RECETTES.etapes = r => {
  const st = (r.etapes || []).slice(0, 4), n = st.length, P0 = railV(n, 'bas');
  const M = P0.map((p, k) => medaillon(p.x, p.y, p.r, { cle: cleOf(st[k]), at: T(st[k]) }));
  const V0 = M.slice(1).map((m, k) => voieEntre(M[k], m)), path = chemin(P0.map(p => [p.x, p.y]));
  const imp = impulsion(path, { color: C.ambre }), taken = M.map(m => m.box);
  const ts = st.map(s => T(s)), F = focusAt(ts[n - 1]);
  const lab = n === 4 ? [0, 2] : st.map((_, k) => k).slice(0, n - 1);
  const P = lab.map(k => placeTuile(L(st[k]), railCands(P0[k]), taken, { maxw: 949 - (P0[k].x + P0[k].r + 40), strict: true }));
  const tl = TL(st[n - 1], Math.max(ts[n - 1], F + HIT)), V = auPlancher('verdict', L(st[n - 1]), tl);
  const H = M[n - 1];
  return { focus: F, hero: [H], edge: k => H.edge(k), beats: beatsOf(...ts.slice(0, n - 1)),
    events: () => [{ name: 'derniere', t: F, box: H.box, forme: union(M.map(m => m.box)) }],
    seek(t) { V0.forEach(v => v.draw(t)); M.forEach(m => { m.pop(t); m.idle(t); });
      M.forEach((m, k) => { if (k < n - 1) { m.lit(eIn((t - ts[k] + HIT) / FAST)); m.pulse(t, ts[k] - HIT); }
        else { m.lit(eIn((t - F) / FAST), 'signal'); m.pulse(t, F); } });
      H.grow(1 + .12 * SPR_HERO.f((t - F) / SPR_HERO.dur));
      let u = -1; for (let k = 1; k < n; k++) { const a = ts[k - 1], b = k === n - 1 ? F : ts[k] - HIT;
        if (t >= a && t < b) u = ((k - 1) + (k === n - 1 ? eOut : eIn)((t - a) / Math.max(.2, b - a))) / (n - 1); }
      if (u >= 0) imp.at(u); else imp.hide();
      P.forEach((p, j) => { const k = lab[j]; p.show(t, TL(st[k]), k < n - 2 ? ts[k + 1] : F); }); V.show(t, tl); } };
};

// R5 · boucle, cycle (ANNEAU) : l'anneau entier et la comète qui tourne déjà, calme (« ça tourne » est l'état
// d'avant) ; chaque pensée allume son médaillon sur son mot, et son mot s'écrit au centre, un à la fois ; FRAPPE : la
// comète s'emballe (600°/s), sa traînée s'allonge, l'anneau s'épaissit (30 px, Os 0,40). Une boucle ne s'arrête pas.
RECETTES.boucle = r => {
  const st = (r.stations || []).slice(0, 3), n = st.length, cx = 540, cy = 620, R0 = 280;
  const ang = st.map((_, k) => -Math.PI / 2 + 2 * Math.PI * k / n);
  const v = voie(`M ${cx} ${cy - R0} A ${R0} ${R0} 0 1 1 ${cx - .1} ${cy - R0} Z`, { w: 22, alpha: .6, id: 'anneau' });
  const M = ang.map((a, k) => medaillon(cx + R0 * Math.cos(a), cy + R0 * Math.sin(a), 74, { cle: cleOf(st[k]), at: T(st[k]) }));
  const imp = impulsion(v, { color: C.ambre });
  const ts = st.map(s => T(s)), te = r.emballement ? T(r.emballement) : 99, tAcc = r.accent ? TL(r.accent) : 99;
  const F = focusAt(first(te, r.accent ? T(r.accent) : 99, ts[n - 1] + .3));
  const P = st.map(s => verdict(L(s), cx, cy, { size: 110, min: 64, maxw: 380, oneLine: true, frappe: false, hote: 'anneau' }));
  const V = r.accent && r.accent.label ? auPlancher('verdict', L(r.accent), tAcc) : null;
  const t00 = .1, base = 1 / 1.6, a = 600 / 225 - 1, ramp = .3;
  const turns = t => { const x = Math.max(0, t - t00), y = Math.max(0, t - F);
    return base * (x + a * (y < ramp ? y * y / (2 * ramp) : y - ramp / 2)); };
  return { focus: F, hero: [v, ...M, imp], edge: k => v.edge(k), beats: beatsOf(...ts.filter(x => x < F)),
    events: () => [{ name: 'emballe', t: F, box: [cx - R0, cy - R0, cx + R0, cy + R0], forme: [cx - R0 - 74, cy - R0 - 74, cx + R0 + 74, cy + R0 + 74] }],
    seek(t) { v.draw(t, .05, .6); M.forEach((m, k) => { m.pop(t); m.lit(eIn((t - ts[k] + HIT) / FAST)); m.pulse(t, ts[k] - HIT); m.idle(t); });
      const q = eIn((t - F) / .3); v.thick(8 * q, .4 * q);
      imp.at(((turns(t) % 1) + 1) % 1, 1, 1 + 1.5 * q);
      let on = -1; ts.forEach((x, k) => { if (t >= TL(st[k]) - .1) on = k; });
      if (t > F && on >= n - 1) { const f = ((turns(t) % 1) + 1) % 1; on = Math.floor(f * n + .02) % n; }
      P.forEach((p, k) => { if (k !== on) { p.setAttribute('opacity', 0); return; }
        if (t <= F) p.show(t, TL(st[k])); else p.show(t, t - 1); });
      if (V) V.show(t, tAcc); } };
};

// R6 · blocage, échec (RAIL-V) : la source héros (r 130), la voie intacte et la cible prête dès la pose. (a) un bloqueur
// nommé tombe en travers ; (b) sans bloqueur, l'ordre part, cale et s'étouffe dans la source (S4a) ; la cible attend,
// intacte. La relation écrite (CAN'T SEND) frappe en héros à côté de la voie, là où l'ordre échoue.
RECETTES.blocage = r => {
  const s = medaillon(300, 400, 130, { cle: cleOf(r.source), at: T(r.source) }), c = medaillon(300, 880, 90, { cle: cleOf(r.cible), at: T(r.cible) });
  const v = voieEntre(s, c), imp = impulsion(v, { color: C.ambre }), taken = [s.box, c.box, v.box];
  const ts = TL(r.source), tc = TL(r.cible), tv = TL(r.verbe), tb = r.bloqueur ? TL(r.bloqueur) : 99;
  const F = focusAt(first(r.bloqueur ? T(r.bloqueur) : 99, T(r.verbe))), tKill = F;
  const tGo = Math.max(.35, tKill - .75), stop = r.bloqueur ? .5 : .28;
  const B = r.bloqueur ? barrage(300, 640, { horiz: true, l: 320 }) : null; if (B) taken.push(B.box);
  const PS = placeTuile(L(r.source), [[470, 400, 'start'], [470, 250, 'start']], taken, { maxw: 479 });
  const PC = placeTuile(L(r.cible), [[430, 880, 'start'], [430, 760, 'start']], taken, { maxw: 519 });
  const third = r.bloqueur ? placeTuile(L(r.bloqueur), [[470, 640, 'start']], taken, { maxw: 479 })
    : (r.verbe && r.verbe.label ? verdict(L(r.verbe), 690, 640, { size: 150, min: 96, maxw: 500, zone: [440, 520, 949, 790], at: tv }) : null);
  const H = r.bloqueur ? B : s;
  return { focus: F, hero: [H], glow: false, edge: k => (r.bloqueur ? c : s).edge(k), beats: beatsOf(ts, tc < F ? tc : 99).concat([tGo]),
    events: () => [{ name: 'echec', t: F, box: H.box, forme: union([s.box, c.box]) }],
    seek(t) { s.pop(t); c.pop(t); v.draw(t); s.idle(t); c.idle(t);
      const on = eIn((t - first(T(r.source), tGo) + .1) / FAST), dead = r.bloqueur ? 0 : eIn((t - tKill) / .3);
      if (!r.bloqueur && dead > .5) s.lit(1, 'eteint'); else s.lit(on * (1 - .8 * dead), 'signal');
      c.lit(.25 + .25 * Math.max(0, 1 - Math.abs(t - tKill - .3) / .2));
      if (B) B.show(t, tKill + HIT);
      if (t >= tGo && t < tKill + .3) { const u = stop * eIn((t - tGo) / Math.max(.2, tKill - tGo)), fade = t < tKill ? 1 : 1 - (t - tKill) / .3;
        imp.at(u, fade); } else imp.hide();
      PS.show(t, ts, tKill); PC.show(t, tc); if (third) third.show(t, r.bloqueur ? tb : tv); } };
};

// R7 · transformation, A devient B (RAIL-V) : A, le lieu et B (vide) dès la pose ; sur le verbe, la comète ambre accélère
// vers le lieu ; au HIT elle en ressort sous la forme B (signal ambre → chose Os).
RECETTES.transformation = r => {
  const a = medaillon(270, 290, 90, { cle: cleOf(r.a), at: T(r.a) }), m = medaillon(270, 590, 110, { cle: cleOf(r.lieu), at: T(r.lieu) }), b = medaillon(270, 880, 90, { cle: cleOf(r.b), at: T(r.b) });
  const v1 = voieEntre(a, m), v2 = voieEntre(m, b);
  const i1 = impulsion(v1, { color: C.ambre }), i2 = impulsion(v2, { color: C.os }), taken = [a.box, m.box, b.box, v1.box, v2.box];
  const ta = TL(r.a), tb = TL(r.b), tv = T(r.verbe), tl = r.lieu ? TL(r.lieu) : 99;
  const F = focusAt(first(tv, T(r.b) - .5)), tM = F, t1 = Math.max(.35, tM - .6), tOut = first(T(r.b), tM + .6 + HIT) - HIT;
  const PA = placeTuile(L(r.a), [[400, 290, 'start']], taken, { maxw: 549 }), PB = placeTuile(L(r.b), [[400, 880, 'start']], taken, { maxw: 549 });
  const PL = r.lieu ? placeTuile(L(r.lieu), [[420, 590, 'start']], taken, { maxw: 529 }) : null;
  return { focus: F, hero: [m], edge: k => m.edge(k), beats: beatsOf(ta, tl < F ? tl : 99).concat([t1]),
    events: () => [{ name: 'mue', t: F, box: m.box, forme: union([a.box, m.box, b.box]) }],
    seek(t) { [a, m, b].forEach(s => { s.pop(t); s.idle(t); }); v1.draw(t); v2.draw(t, .1);
      if (t < tM) a.lit(eIn((t - T(r.a) + .1) / FAST), 'signal'); else a.lit(.4);
      m.lit(clamp(1 - Math.abs(t - tM) / .3) + .2 * (t > tM)); m.pulse(t, tM);
      if (t >= t1 && t < tM) i1.at(eOut((t - t1) / (tM - t1))); else i1.hide();
      if (t >= tM && t < tOut + .2) i2.at(eIn((t - tM) / Math.max(.3, tOut - tM)), t < tOut ? 1 : 1 - (t - tOut) / .2); else i2.hide();
      b.lit(eIn((t - tOut) / FAST)); PA.show(t, ta, tM); PB.show(t, first(tb, tOut + HIT)); if (PL) PL.show(t, tl, tM + .4); } };
};

// R8 · chiffre, statistique : le contenant du nombre dès la pose (les N pions égaux, ou sa place) ; le nombre FRAPPE sur
// son mot, exactement tel qu'il est dit (au plancher) ; les pions basculent en cascade (0,04 s) sur le même temps.
RECETTES.chiffre = r => {
  const tn = TL(r.valeur, T(r.valeur)), tq = r.quoi ? TL(r.quoi) : 99, p = parseNum(L(r.valeur)), tot = r.total ? parseNum(L(r.total)) : null;
  const F = focusAt(T(r.valeur)), taken = [];
  if (tot && p && tot.val <= 10 && p.val <= tot.val && Number.isInteger(tot.val)) {
    const G = pions(tot.val, 540, 560), N = auPlancher('chiffre', L(r.valeur), tn); taken.push(G.box);
    const PQ = r.quoi ? placeTuile(L(r.quoi), [[540, 380], [540, 860]], taken) : null;
    return { focus: F, hero: [G], edge: k => { }, beats: beatsOf(tq < F ? tq : 99), events: () => [{ name: 'valeur', t: F, box: G.box, forme: G.box }],
      seek(t) { G.show(t);
        G.dots.forEach((d, k) => { const off = k >= p.val ? eIn((t - F - .04 * (k - p.val)) / FAST) : 0;
          set(d, { fill: mix(C.os, C.nuit, off), 'fill-opacity': 1 - .75 * off, stroke: mix(C.os, C.ardoise, off) }); });
        N.show(t, tn); if (PQ) PQ.show(t, tq); } };
  }
  const place = cadre([190, 420, 890, 800], { id: 'place' }); taken.push(place.box);
  const N = chiffre(L(r.valeur), 540, 610, { size: 240, maxw: 640, zone: [210, 440, 870, 780], at: tn }); N.setAttribute('data-hote', 'place');
  const PQ = r.quoi ? placeTuile(L(r.quoi), [[540, 360], [540, 900]], taken) : null;
  return { focus: F, hero: [N], glow: false, edge: k => place.edge(k), beats: beatsOf(tq < F ? tq : 99), events: () => [{ name: 'valeur', t: F, box: N.box, forme: place.box }],
    seek(t) { place.show(t); N.show(t, tn); if (PQ) PQ.show(t, tq); } };
};

// R9 · trajet dans le corps (RAIL-V) : la voie entière et les médaillons vides dès la pose ; le signal allume chaque
// médaillon sur son mot, dans le sens dit ; il arrive au dernier (l'organe, héros r 120) au HIT : il reçoit le signal,
// grandit, et son nom frappe au plancher.
RECETTES.trajet = r => {
  const st = (r.etapes || []).slice(0, 3), n = st.length, up = r.sens === 'monte';
  const P0 = railV(n, up ? 'haut' : 'bas'), order = up ? P0.slice().reverse() : P0;          // order[k] = the k-th place said
  const M = order.map((p, k) => medaillon(p.x, p.y, p.r, { cle: cleOf(st[k]), at: T(st[k]) }));
  const V0 = M.slice(1).map((m, k) => voieEntre(M[k], m)), path = chemin(order.map(p => [p.x, p.y]));
  const imp = impulsion(path, { color: C.ambre }), taken = M.map(m => m.box);
  const ts = st.map(s => T(s)), F = focusAt(ts[n - 1]);
  const P = st.slice(0, n - 1).map((s, k) => placeTuile(L(s), railCands(order[k]), taken, { maxw: 949 - (order[k].x + order[k].r + 40), strict: true }));
  const tl = TL(st[n - 1], Math.max(ts[n - 1], F + HIT)), V = auPlancher('verdict', L(st[n - 1]), tl), H = M[n - 1];
  return { focus: F, hero: [H], edge: k => H.edge(k), beats: beatsOf(...ts.slice(0, n - 1)),
    events: () => [{ name: 'arrivee', t: F, box: H.box, forme: union(M.map(m => m.box)) }],
    seek(t) { V0.forEach(v => v.draw(t)); M.forEach(m => { m.pop(t); m.idle(t); });
      M.forEach((m, k) => { if (k < n - 1) { m.lit(eIn((t - ts[k] + HIT) / FAST)); m.pulse(t, ts[k] - HIT); } else { m.lit(eIn((t - F) / FAST), 'signal'); m.pulse(t, F); } });
      H.grow(1 + .12 * SPR_HERO.f((t - F) / SPR_HERO.dur));
      let u = -1; for (let k = 1; k < n; k++) { const a = ts[k - 1], b = k === n - 1 ? F : ts[k] - HIT;
        if (t >= a && t < b) u = ((k - 1) + (k === n - 1 ? eOut : eIn)((t - a) / Math.max(.2, b - a))) / (n - 1); }
      if (u >= 0) imp.at(u); else imp.hide();
      P.forEach((p, k) => p.show(t, TL(st[k]), k < n - 2 ? ts[k + 1] : F)); V.show(t, tl); } };
};

// R11 · débat (BALANCE, V2-8) : pivot (540, 440), fléau 760 × 20 Os, pied et socle, ficelles, plateaux 280 × 80 ;
// chaque thèse est montrée DITE (entre guillemets) DANS son plateau, sur son mot ; FRAPPE : sur la bascule, le fléau
// penche (±11°, ressort) du côté défendu ; « ouvert » : il se balance (±2,5°). Le côté perdant passe en Brume, jamais
// barré. Une thèse trop large pour son plateau se pose sur la rangée de son côté (en haut à gauche, en bas à droite).
RECETTES.debat = r => {
  const cote = r.cote || 'ouvert', cx = 540, py = 440, hang = 230, drop = 230;
  const t1 = TL(r.these), t2 = TL(r.contre), F = focusAt(first(T(r.bascule), T(r.contre) + .5));
  const g = mk($('scene'), 'g', { opacity: 0 });
  const foot = mk(g, 'path', { class: 'chk', d: `M${cx} 452 L 470 600 L 610 600 Z`, fill: C.crep, stroke: C.brume, 'stroke-width': 8, 'stroke-linejoin': 'round' });
  mk(g, 'rect', { x: cx - 110, y: 600, width: 220, height: 16, rx: 8, fill: C.brume });
  const beam = mk(g, 'g');
  mk(beam, 'line', { class: 'chk', x1: 160, x2: 920, y1: py, y2: py, stroke: C.os, 'stroke-width': 20, 'stroke-linecap': 'round' });
  mk(beam, 'circle', { cx, cy: py, r: 18, fill: C.os });
  const pans = [-1, 1].map((sd, k) => { const pg = mk(g, 'g'), hx = cx + sd * hang, top = py + drop;
    mk(pg, 'line', { x1: hx, x2: hx - 120, y1: py, y2: top, stroke: C.brume, 'stroke-width': 8, 'stroke-linecap': 'round' });
    mk(pg, 'line', { x1: hx, x2: hx + 120, y1: py, y2: top, stroke: C.brume, 'stroke-width': 8, 'stroke-linecap': 'round' });
    mk(pg, 'path', { class: 'chk', 'data-id': 'plateau' + k, d: `M${hx - 140} ${top} Q ${hx} ${top + 110} ${hx + 140} ${top} Z`, fill: C.crep, stroke: C.os, 'stroke-width': 8, 'stroke-linejoin': 'round' });
    return { pg, hx, top }; });
  const taken = [[131, 300, 949, 800]];
  // in the pans (the words are the weights) if they fit; else on their side's row
  const inPan = (txt, k) => { const P = pans[k], pz = [P.hx - 179, P.top - 70, P.hx + 179, P.top + 60];
    const tl = tuile(txt, P.hx, P.top - 8, { layer: 'scene', maxw: 312, hote: 'plateau' + k, font: 'ISerif', size0: 96 });
    if (tl.w <= 312 && tl.size >= 64) { P.pg.appendChild(tl); return tl; } tl.remove(); return null; };
  let PT = inPan('“' + phrase(L(r.these)) + '”', 0), PC = inPan('“' + phrase(L(r.contre)) + '”', 1);
  if (!PT || !PC) { if (PT) PT.remove(); if (PC) PC.remove();
    // under the swinging pans (their lowest point is y ≈ 775), each on its own row and on its own side
    PC = placeTuile('“' + phrase(L(r.contre)) + '”', [[949, 935, 'end']], [[131, 300, 949, 789]], { maxw: 818, strict: true, size0: 64, font: 'ISerif' });
    PT = placeTuile('“' + phrase(L(r.these)) + '”', [[131, PC.box[1] - 16 - 42, 'start']], [[131, 300, 949, 789], PC.box], { maxw: 818, strict: true, size0: 64, font: 'ISerif' }); }
  const tilt = cote === 'these' ? -11 : cote === 'contre' ? 11 : 0;
  return { focus: F, hero: [g], edge: k => set(foot, { stroke: mix(C.brume, C.os, .85 * k) }), beats: beatsOf(t1, t2 < F ? t2 : 99),
    events: () => [{ name: 'penche', t: F, box: [131, 300, 949, 800], forme: [160, 420, 920, 800] }],
    seek(t) { g.setAttribute('opacity', skel(t));
      const a = tilt * SPR_BAL.f((t - F) / SPR_BAL.dur) + (cote === 'ouvert' ? 2.5 * Math.sin(Math.max(0, t - F) * 2.4) * (t > F) : 0);
      beam.setAttribute('transform', `rotate(${a} ${cx} ${py})`);
      pans.forEach((P, k) => { const sd = k ? 1 : -1, rad = a * Math.PI / 180, ex = cx + sd * hang * Math.cos(rad), ey = py + sd * hang * Math.sin(rad);
        P.pg.setAttribute('transform', `translate(${(ex - P.hx).toFixed(2)} ${(ey - py).toFixed(2)})`); });
      PT.show(t, t1, cote === 'these' ? 99 : F); PC.show(t, t2, cote === 'contre' ? 99 : F); } };
};

// R12 · question, hypothèse (BULLE, V2-4 / V2-10) : la bulle dès la pose ; le nom concret au-dessus (tuile) ; le statut
// dit (PERHAPS, I THINK, ONE CASE) en cachet à cheval sur le bord ; le texte dit dans la bulle, révélé par le bas ; un
// « ? » de ponctuation seulement si la phrase dite est une question. FRAPPE : sur le mot de la question ou du statut,
// la bulle s'ouvre (×0,96 → 1, ressort), le cachet tamponne ou le « ? » se pose. La bulle ne contient jamais de réponse.
const STATUT = /^(PERHAPS|MAYBE|POSSIBLY|PROBABLY|I THINK|WE THINK|THINK|I BELIEVE|I GUESS|I SUSPECT|THEORY|HYPOTHESIS|ONE CASE|NO EVIDENCE)$/;
const INTERROG = /^(what|why|how|who|whom|which|where|when|is|are|does|do|did|can|could|should|would|will)$/i;
const wordAt = i => WORDS.find(w => w.i === i);
RECETTES.question = r => {
  const ms = (r.mots || []).slice(0, 2), tq = T(r.question), F = focusAt(first(tq, ...ms.map(m => T(m))));
  const B0 = PREMIUM ? [168, 640, 912, 1060] : [150, 500, 930, 900], bu = bulle(B0, { id: 'bulle', tip: 58 });   // premium: left of the buttons
  // the status, from a label or from the question word itself (« think » after « I »)
  let statut = ms.find(m => STATUT.test(L(m)));
  let cachetTxt = statut ? L(statut) : '', tStat = statut ? TL(statut) : 99;
  const qw = r.question && wordAt(r.question.i), qtxt = qw ? String(qw.w).toLowerCase().replace(/[^a-z']/g, '') : '';
  if (!statut && qw && /^(think|believe|guess|suspect)$/.test(qtxt)) { const pw = wordAt(r.question.i - 1);
    cachetTxt = ((pw && /^(i|we)$/i.test(String(pw.w).replace(/[^a-z]/gi, ''))) ? String(pw.w).replace(/[^a-z]/gi, '').toUpperCase() + ' ' : '') + qtxt.toUpperCase(); tStat = TL(r.question, tq); }
  if (!statut && qw && /^(perhaps|maybe|possibly|probably)$/.test(qtxt)) { cachetTxt = qtxt.toUpperCase(); tStat = TL(r.question, tq); }
  const others = ms.filter(m => m !== statut), said = others[others.length - 1], above = others.length > 1 ? others[0] : null;
  // a real question said: « ? » as punctuation after the said text (or the question's own words when nothing else)
  let isQ = false, qWords = '';
  if (qw && INTERROG.test(qtxt)) { for (let k = 0; k < 6; k++) { const w = wordAt(r.question.i + k); if (!w) break;
      qWords += (k ? ' ' : '') + String(w.w).replace(/[?.,!]+$/, ''); if (/\?$/.test(w.w)) { isQ = true; break; } } }
  const sayTxt = said ? L(said) : (isQ ? qWords.toUpperCase() : '');
  const inner = [B0[0] + 50, B0[1] + 70, B0[2] - 50, B0[3] - 40];
  const DIT = sayTxt ? dit(phrase(sayTxt), inner, { size: 136, min: 72, font: 'ISerif', hote: 'bulle', question: isQ }) : null;
  const tSay = said ? TL(said) : TL(r.question, tq);
  const CA = cachetTxt ? cachet(cachetTxt, B0[0] + 60, B0[1], { hote: 'bulle', anchor: 'start' }) : null;   // astride the top edge
  const taken = [bu.box];
  const yA = PREMIUM ? 470 : 395, cA = above && cleOf(above), MA = cA ? medaillon(B0[0] + 80, yA, 80, { cle: cA, at: T(above) }) : null; if (MA) taken.push(MA.box);
  const PA = above ? placeTuile(L(above), MA ? [[B0[0] + 190, yA, 'start']] : [[540, yA], [540, PREMIUM ? 360 : 395]], taken, { maxw: MA ? 818 - 200 : 818 }) : null;
  const tA = above ? TL(above) : 99;
  return { focus: F, hero: [bu], edge: k => bu.edge(k), beats: beatsOf(tA, tStat < F ? tStat : 99, tSay < F ? tSay : 99),
    events: () => [{ name: 'question', t: F, box: bu.box, forme: bu.box }],
    seek(t) { bu.show(t, F); if (MA) { MA.pop(t); MA.lit(eIn((t - T(above) + HIT) / FAST)); MA.pulse(t, T(above) - HIT); MA.idle(t); } if (PA) PA.show(t, tA, F); if (CA) CA.show(t, tStat); if (DIT) DIT.show(t, tSay, isQ ? Math.max(F + HIT, tSay) + .1 : 99); } };
};

// R13 · champ de vision (CHAMP, gardé ; traits 12 px) : l'œil et le champ large dès la pose ; sur le mot du stress, il se
// resserre (la tension) ; FRAPPE : sur le mot du retour, il se rouvre d'un coup et les points redeviennent nets. Le
// nom de l'état va au plancher, un à la fois (l'ancien s'efface au retour).
RECETTES.champ = r => {
  const ex = 250, ey = 600, len = 600, wide = 34, narrow = 5, down = (r.sens || 'resserre') === 'resserre';
  const eye = mk($('scene'), 'g', { class: 'chk', opacity: 0 });
  mk(eye, 'path', { d: `M${ex - 95} ${ey} Q ${ex} ${ey - 70} ${ex + 95} ${ey} Q ${ex} ${ey + 70} ${ex - 95} ${ey} Z`, fill: C.nuit, stroke: C.os, 'stroke-width': 12 });
  mk(eye, 'circle', { cx: ex + 18, cy: ey, r: 34, fill: C.os }); mk(eye, 'circle', { cx: ex + 22, cy: ey, r: 15, fill: C.abyss });
  const g = mk($('scene'), 'g', { opacity: 0 }), ox = ex + 100;
  const veil = mk(g, 'path', { fill: C.os, 'fill-opacity': .16 });
  const e1 = mk(g, 'path', { fill: 'none', stroke: C.os, 'stroke-width': 12, 'stroke-dasharray': '18 12', 'stroke-linecap': 'round' });
  const e2 = mk(g, 'path', { fill: 'none', stroke: C.os, 'stroke-width': 12, 'stroke-dasharray': '18 12', 'stroke-linecap': 'round' });
  const arc = mk(g, 'path', { fill: 'none', stroke: C.os, 'stroke-width': 12, 'stroke-linecap': 'round', opacity: .8 });
  const pts = [...Array(9)].map((_, i) => { const a = (-wide + 2 * wide * (i + .5) / 9) * Math.PI / 180, rr = len * (.6 + .3 * rnd(i + 4));
    return { a, sharp: mk($('scene'), 'circle', { class: 'chk', cx: ox + rr * Math.cos(a), cy: ey + rr * Math.sin(a), r: 13, fill: C.os, opacity: 0 }),
      soft: mk($('scene'), 'circle', { class: 'chk', cx: ox + rr * Math.cos(a), cy: ey + rr * Math.sin(a), r: 20, fill: C.brume, filter: 'url(#soft)', opacity: 0 }) }; });
  const hasRet = !!r.retour, F0 = focusAt(hasRet ? T(r.retour) : T(r.mot));
  const tm = hasRet ? T(r.mot) - HIT : F0, tb = hasRet ? Math.max(F0, tm + .8) : 99, F = hasRet ? tb : tm;
  // the state's name on the floor, one at a time: the narrow state, then (after the return) the wide one
  const PR = r.resultat ? auPlancher('verdict', L(r.resultat), TL(r.resultat)) : null;
  const t2 = r.resultat2 ? Math.max(TL(r.resultat2), tb + .45) : 99;
  const PR2 = r.resultat2 ? auPlancher('verdict', L(r.resultat2), t2) : null;
  const PC = r.cause && !PR ? auPlancher('verdict', L(r.cause), TL(r.cause)) : null;
  const a0 = down ? wide : narrow, a1 = down ? narrow : wide;
  return { focus: F, hero: [eye, g, ...pts.map(p => p.sharp), ...pts.map(p => p.soft)], edge: k => arc.setAttribute('stroke-width', 12 + 5 * k),
    beats: beatsOf(r.resultat ? T(r.resultat) : 99, r.cause ? T(r.cause) : 99).filter(x => x < F - .2).concat(hasRet ? [tm] : []),
    events: () => [{ name: 'champ', t: F, box: [ox, ey - 340, ox + len, ey + 340], forme: [ex - 100, ey - 340, ox + len, ey + 340] }],
    seek(t) { eye.setAttribute('opacity', skel(t)); const vis = skel(t); g.setAttribute('opacity', vis);
      const q = eIn((t - tm) / .5) * (1 - eIn((t - tb) / .6)), half = (a0 + (a1 - a0) * q) * Math.PI / 180;
      const P1 = [ox + len * Math.cos(-half), ey + len * Math.sin(-half)], P2 = [ox + len * Math.cos(half), ey + len * Math.sin(half)];
      e1.setAttribute('d', `M${ox} ${ey} L${P1[0]} ${P1[1]}`); e2.setAttribute('d', `M${ox} ${ey} L${P2[0]} ${P2[1]}`);
      arc.setAttribute('d', `M${P1[0]} ${P1[1]} A ${len} ${len} 0 0 1 ${P2[0]} ${P2[1]}`);
      veil.setAttribute('d', `M${ox} ${ey} L${P1[0]} ${P1[1]} A ${len} ${len} 0 0 1 ${P2[0]} ${P2[1]} Z`);
      pts.forEach(p => { const inside = clamp(1 - (Math.abs(p.a) - half) / (5 * Math.PI / 180));
        p.sharp.setAttribute('opacity', vis * .95 * inside); p.soft.setAttribute('opacity', vis * .55 * (1 - inside)); });
      if (PR) { PR.show(t, TL(r.resultat)); if (tb < 99) PR.setAttribute('opacity', +PR.getAttribute('opacity') * (1 - eIn((t - tb) / .3))); }
      if (PR2) PR2.show(t, t2); if (PC) PC.show(t, TL(r.cause)); } };
};

// R0 · mots-clés (AFFICHE, le repli sûr) : dès la pose, deux filets pleins encadrent le bloc (jamais une ligne vide par
// mot : le banc v2a les lisait comme un quiz à trous) ; chaque mot s'y pose sur son mot ; le mot-sens FRAPPE en héros
// (150 px Os) ; les autres reculent (Brume). Lot 3 : le médaillon d'un nom concret en haut à gauche.
RECETTES.mots_cles = r => {
  const ms = (r.mots || []).slice(0, 3), n = ms.length;
  let fi = S.focus ? ms.findIndex(m => m.i === S.focus.i) : -1; if (fi < 0) fi = n - 1;
  const cle = ms.map(m => cleOf(m)).find(Boolean), mC = ms.find(m => cleOf(m) === cle), M = cle ? medaillon(240, 250, 80, { cle, at: T(mC) }) : null;
  // a status marker SAID in the shot (never invented) becomes the stamp of the register (V2-10.3) — when the 3 texts
  // allow it (2 words at most), and never in the last 0,8 s
  let CA = null, tCA = 99;
  if (n <= 2) { for (const w of WORDS) { if (w.t < .1 || w.t - .1 > LATE) continue; const x = String(w.w).toLowerCase().replace(/[^a-z']/g, '');
      const pw = WORDS.find(y => y.i === w.i - 1), pre = pw && /^(i|we)$/i.test(String(pw.w).replace(/[^a-z]/gi, '')) ? String(pw.w).replace(/[^a-z]/gi, '').toUpperCase() + ' ' : '';
      if (/^(perhaps|maybe|possibly|probably|apparently|theoretically)$/.test(x) || (pre && /^(think|believe|guess|suspect)$/.test(x))) {
        CA = cachet(pre + x.toUpperCase(), M ? 340 : 160, M ? 250 : 290, { anchor: 'start' }); tCA = TL({ i: w.i, label: pre + x }, w.t); break; } } }
  const top = filet(160, 920, M ? 360 : 340), bot = filet(160, 920, 905);
  const ys = n === 1 ? [622] : n === 2 ? [530, 735] : [455, 625, 805];
  const ts = ms.map(m => TL(m));
  // the meaning word first: the others stay at most 0,72 × its size (a long focus word never ends up the smallest)
  const VF = verdict(L(ms[fi]), 540, ys[fi], { size: 150, min: 64, maxw: 760, oneLine: true, frappe: true, at: ts[fi] });
  const V = ms.map((m, k) => k === fi ? VF : verdict(AVIS ? phrase(L(m)) : L(m), 540, ys[k], { size: Math.round(Math.min(AVIS ? 120 : 104, Math.max(.72 * VF.size, Math.min(64, .85 * VF.size)) * (AVIS ? 1.15 : 1))),
    min: 48, maxw: 760, oneLine: true, frappe: false, at: ts[k], font: AVIS ? 'ISerif' : undefined }));
  const U = AVIS ? null : sousLe(VF);
  const F = focusAt(T(ms[fi]));
  return { focus: F, hero: [V[fi]], edge: k => { top.edge(k); bot.edge(k); }, beats: beatsOf(...ts.filter((x, k) => k !== fi && x < F)),
    events: () => [{ name: 'mot', t: F, box: V[fi].box, forme: [160, 340, 920, 905] }],
    seek(t) { top.show(t); bot.show(t); if (CA) CA.show(t, tCA); if (M) { M.pop(t); M.idle(t); const k0 = ms.findIndex(m => cleOf(m) === cle); M.lit(eIn((t - T(ms[k0]) + HIT) / FAST)); M.pulse(t, T(ms[k0]) - HIT); }
      if (U) U.show(t, ts[fi] + .25);
      V.forEach((v, k) => { v.show(t, ts[k]); const nx = k === fi ? 99 : (k < n - 1 ? ts[k + 1] : 99);
        v._t.setAttribute('fill', mix(C.os, C.brume, k === fi ? 0 : eIn((t - nx) / FAST))); }); } };
};
