// Les recettes : une relation = une composition de primitives (grammaire v0 §4), placées par gabarit (SOLO, DUO,
// RAIL), calées sur les mots. Chaque recette rend { seek(t), events(), focus }. Aucun réglage à la main par scène.
window.RECETTES = {};
const lvl = (x, d) => (x === undefined || x === null || isNaN(+x)) ? d : clamp(+x, 0, 1.05);
const first = (...ts) => Math.min(...ts.filter(x => x < 99), 99);

// R1 · une quantité monte ou baisse (SOLO) : la jauge est là, à son niveau d'avant ; elle bouge sur le verbe.
RECETTES.niveau = r => {
  const down = r.sens !== 'hausse', f0 = lvl(r.depart, down ? .82 : .3), f1 = lvl(r.arrivee, down ? .38 : .86);
  const j = barre(150, 560, 780, 130), taken = [j.box];
  const tq = T(r.quantite), tv = T(r.verbe), tn = r.valeur ? T(r.valeur) : 99, tc = r.cause ? T(r.cause) : 99;
  const PQ = placeLabel(L(r.quantite), [[150, 470, 'start'], [540, 470]], taken);
  const N = r.valeur ? chiffre(L(r.valeur), 540, 830, { maxw: 760, size: 230 }) : null; if (N) taken.push(N.box);
  const V = !r.valeur && r.verbe && r.verbe.label ? verdict(L(r.verbe), 540, 820, { maxw: 760, size: 140 }) : null; if (V) taken.push(V.box);
  const PC = r.cause ? placeLabel(L(r.cause), [[930, 470, 'end'], [540, 370]], taken) : null;
  const tchg = tv - .7 + .2;                                   // arrives at verb + 0.2 s, moves in 0.7 s
  return { focus: tv, events: () => [{ name: 'verbe', t: tv, box: j.box }],
    seek(t) { j.show(t, .1); j.level(f0 + (f1 - f0) * eIn((t - tchg) / .7), f0);
      PQ.show(t, Math.min(tq, tv - .3)); if (N) N.show(t, tn); if (V) V.show(t, tv); if (PC) PC.show(t, tc, tv); } };
};

// R10 · comparaison à une référence (SOLO) : la barre rejoint, dépasse ou reste sous le repère, qui ne bouge jamais.
RECETTES.reference = r => {
  const pos = r.position || 'atteint', ref = .7, down = r.sens === 'baisse' || pos === 'sous';
  const f0 = lvl(r.depart, down ? .95 : .22);                         // lower / older: it comes DOWN to the line
  const f1 = pos === 'depasse' ? (down ? .42 : .95) : pos === 'sous' ? .42 : ref;
  const j = barre(150, 560, 780, 130), taken = [j.box], rp = repereH(j, ref); taken.push(rp.box);
  const tq = T(r.quantite), tr = T(r.reference), tv = T(r.verbe), tn = r.valeur ? T(r.valeur) : 99;
  const PR = placeLabel(L(r.reference), [[rp.x, 465], [rp.x, 790]], taken);
  const PQ = placeLabel(L(r.quantite), [[150, 790, 'start'], [150, 465, 'start'], [540, 900]], taken);
  const N = r.valeur ? chiffre(L(r.valeur), 540, 880, { maxw: 600, size: 170 }) : null;
  const tchg = tv - .5;
  return { focus: tv, events: () => [{ name: 'verbe', t: tv, box: j.box }],
    seek(t) { j.show(t, .1); j.level(f0 + (f1 - f0) * eIn((t - tchg) / .7), f0); rp.draw(t, Math.min(tr, tchg));
      PR.show(t, Math.min(tr, tchg), tv + .6); PQ.show(t, Math.min(tq, tchg - .2)); if (N) N.show(t, tn); } };
};

// R2 · cause → effet (RAIL) : la cause est nommée ; l'impulsion part sur le lien, touche l'effet, qui change juste après.
RECETTES.cause_effet = r => {
  const up = r.sens_effet === 'hausse';
  const s = station(240, 620, 80), j = jauge(800, 330, 560, { w: 190 }), v = voie('M330 620 L 695 620');
  const imp = impulsion(v, { color: C.os }), taken = [s.box, j.box, v.box];
  const tc = T(r.cause), tl = T(r.lien), te = T(r.effet), tn = r.valeur ? T(r.valeur) : 99;
  const tArr = first(te, tl + .7) - HIT, tGo = Math.max(tArr - .7, first(tc, 99) + .1, .3);
  const PC = placeLabel(L(r.cause), [[240, 790], [240, 450]], taken);
  const PE = placeLabel(L(r.effet), [[800, 935], [600, 935]], taken);
  const N = r.valeur ? chiffre(L(r.valeur), 480, 420, { maxw: 420, size: 170 }) : null;
  const f0 = up ? .3 : .82, f1 = up ? .88 : .36;
  return { focus: tArr + HIT, events: () => [{ name: 'effet', t: tArr + HIT, box: j.box }],
    seek(t) { s.pop(t, .1); s.lit(eIn((t - tc + .1) / FAST)); v.draw(t, .15); j.show(t, .2);
      if (t >= tGo && t < tArr + .18) imp.at(eIn((t - tGo) / (tArr - tGo)), t < tArr ? 1 : 1 - (t - tArr) / .18); else imp.hide();
      j.level(f0 + (f1 - f0) * eIn((t - tArr - .033) / .6), f0);       // the effect changes in the frame after the contact
      PC.show(t, tc, tGo + .3); PE.show(t, first(te, tArr)); if (N) N.show(t, tn); } };
};

// R3 · contraste A / B (DUO) : la même jauge des deux côtés, à la même échelle ; une seule chose diffère, sur le mot.
RECETTES.contraste = r => {
  const win = r.gagnant === 'a' ? 0 : 1, more = r.sens !== 'moins';
  const ja = barre(150, 450, 780, 110), jb = barre(150, 700, 780, 110), taken = [ja.box, jb.box];
  const ta = T(r.a), tb = T(r.b), tq = r.quoi ? T(r.quoi) : 99, tk = first(T(r.bascule), tb + .4);
  const PA = placeLabel(L(r.a), [[150, 392, 'start'], [930, 392, 'end']], taken), PB = placeLabel(L(r.b), [[150, 642, 'start'], [930, 642, 'end']], taken);
  const PQ = r.quoi ? placeLabel(L(r.quoi), [[540, 925], [540, 330]], taken) : null;
  const base = .5, hi = more ? .94 : .12;
  return { focus: tk, events: () => [{ name: 'bascule', t: tk, box: [ja.box[0], ja.box[1], jb.box[2], jb.box[3]] }],
    seek(t) { ja.show(t, Math.min(ta - .2, .3)); jb.show(t, Math.min(tb - .2, .4));
      const q = eIn((t - tk + HIT) / .6), lo = more ? .2 : .86;          // the other side moves the other way
      ja.level(base + ((win === 0 ? hi : lo) - base) * q, base); jb.level(base + ((win === 1 ? hi : lo) - base) * q, base);
      PA.show(t, ta, win === 0 ? 99 : tk); PB.show(t, tb, win === 1 ? 99 : tk); if (PQ) PQ.show(t, tq); } };
};

// R4 · étapes, séquence (RAIL) : l'impulsion va de station en station ; chaque station s'allume sur son mot.
RECETTES.etapes = r => {
  const st = (r.etapes || []).slice(0, 4), n = st.length, x0 = 190, x1 = 890, y = 640;
  const xs = st.map((_, k) => n === 1 ? 540 : x0 + (x1 - x0) * k / (n - 1));
  const v = voie(`M${xs[0]} ${y} L ${xs[n - 1]} ${y}`), S0 = xs.map(x => station(x, y, 50));
  const imp = impulsion(v, { color: C.ambre }), taken = [v.box, ...S0.map(s => s.box)];
  const ts = st.map(s => T(s));
  const P = st.slice(0, 3).map((s, k) => placeLabel(L(s), k % 2 ? [[xs[k], 780], [xs[k], 500], [xs[k], 890], [xs[k], 385]]
    : [[xs[k], 500], [xs[k], 780], [xs[k], 385], [xs[k], 890]], taken));
  return { focus: ts[n - 1], events: () => [{ name: 'derniere', t: ts[n - 1], box: S0[n - 1].box }],
    seek(t) { v.draw(t, .1, .45); S0.forEach((s, k) => { s.pop(t, .1 + .06 * k); s.lit(eIn((t - ts[k] + HIT) / FAST), k === n - 1 ? C.ambre : C.os); });
      let u = -1; for (let k = 1; k < n; k++) { const a = ts[k - 1], b = ts[k] - HIT; if (t >= a && t < b) u = ((k - 1) + eIn((t - a) / Math.max(.2, b - a))) / (n - 1); }
      if (u >= 0) imp.at(u); else imp.hide();
      P.forEach((p, k) => p.show(t, ts[k], k < n - 1 ? ts[k + 1] : 99)); } };
};

// R5 · boucle, cycle (SOLO) : l'impulsion tourne sur l'anneau ; elle s'emballe sur le mot ; l'anneau reste.
RECETTES.boucle = r => {
  const st = (r.stations || []).slice(0, 3), n = st.length, cx = 540, cy = 620, R0 = 260;
  const ang = st.map((_, k) => -Math.PI / 2 + 2 * Math.PI * k / n);
  const v = voie(`M ${cx} ${cy - R0} A ${R0} ${R0} 0 1 1 ${cx - .1} ${cy - R0} Z`);
  const S0 = ang.map(a => station(cx + R0 * Math.cos(a), cy + R0 * Math.sin(a), 34));
  const imp = impulsion(v, { color: C.ambre });
  const ts = st.map(s => T(s)), te = r.emballement ? T(r.emballement) : 99, tAcc = r.accent ? T(r.accent) : 99;
  const P = st.map(s => pastille(L(s), cx, cy - (r.accent && r.accent.label ? 40 : 0)));      // all at the centre, one shown
  const V = r.accent && r.accent.label ? verdict(L(r.accent), cx, cy + 110, { size: 88, maxw: 420, oneLine: true }) : null;
  const tStart = first(ts[0], .5), ta = first(te, tAcc);
  const u = t => { const base = (t - tStart) / 1.6, fast = t > ta ? (t - ta) * (600 / 360) : 0; return base + fast; };
  return { focus: ta, events: () => [{ name: 'emballe', t: ta, box: [cx - R0, cy - R0, cx + R0, cy + R0] }],
    seek(t) { v.draw(t, .1, .6); S0.forEach((s, k) => { s.pop(t, .15); s.lit(eIn((t - ts[k] + HIT) / FAST)); });
      if (t >= tStart) imp.at(u(t) % 1); else imp.hide();
      // which thought is on: the last one said; once it loops, the station the pulse has just passed
      let on = -1; ts.forEach((x, k) => { if (t >= x - .1) on = k; });
      if (t > ta && on >= n - 1) { const f = ((u(t) % 1) + 1) % 1; on = Math.floor(f * n + .02) % n; }
      P.forEach((p, k) => { if (k !== on) { p.setAttribute('opacity', 0); return; }
        if (t <= ta) p.show(t, ts[k]); else p.show(t, t - 1); });       // before: pops on its word; looping: just on
      if (V) V.show(t, tAcc); } };
};

// R6 · blocage, échec (RAIL) : (a) un bloqueur nommé tombe en travers ; (b) sans bloqueur, l'ordre s'étouffe dans la
// source (S4a, son choix) : la source s'allume, l'ordre part, cale, s'éteint ; la cible attend, intacte, et rien n'arrive.
RECETTES.blocage = r => {
  const s = station(220, 640, 70), c = station(860, 640, 70), v = voie('M298 640 L 782 640');
  const imp = impulsion(v, { color: C.ambre }), taken = [s.box, c.box, v.box];
  const ts = T(r.source), tc = T(r.cible), tv = T(r.verbe), tb = r.bloqueur ? T(r.bloqueur) : 99;
  const tKill = first(tb < 99 ? tb : 99, tv) - HIT, tGo = Math.max(.35, tKill - .75), stop = r.bloqueur ? .5 : .28;
  const B = r.bloqueur ? barrage(540, 640) : null;
  const PS = placeLabel(L(r.source), [[220, 790], [220, 490], [220, 890]], taken), PC = placeLabel(L(r.cible), [[860, 790], [860, 490], [860, 890]], taken);
  const third = r.bloqueur ? placeLabel(L(r.bloqueur), [[540, 430], [540, 935]], taken)
    : (r.verbe && r.verbe.label ? verdict(L(r.verbe), 540, 440, { size: 110, maxw: 760 }) : null);
  return { focus: tKill + HIT, events: () => [{ name: 'echec', t: tKill + HIT, box: r.bloqueur ? B.box : s.box }],
    seek(t) { s.pop(t, .1); c.pop(t, .15); v.draw(t, .15, .45);
      // the source lights on its word (signal), goes out when the order dies; the target stays calm Os, intact
      const on = eIn((t - first(ts, tGo) + .1) / FAST), dead = r.bloqueur ? 0 : eIn((t - tKill) / .3);
      s.lit(on * (1 - .8 * dead), C.ambre); c.lit(.25 + .25 * Math.max(0, 1 - Math.abs(t - tKill - .3) / .2));
      if (B) B.show(t, tb);
      if (t >= tGo && t < tKill + .3) { const u = stop * eIn((t - tGo) / Math.max(.2, tKill - tGo)), fade = t < tKill ? 1 : 1 - (t - tKill) / .3;
        const q = imp.at(u, fade); if (t > tKill && B) imp.setAttribute('transform', `translate(${q.x} ${q.y}) scale(${1 - .5 * fade} 1) translate(${-q.x} ${-q.y})`);
        else imp.removeAttribute('transform'); } else imp.hide();
      PS.show(t, ts, tKill); PC.show(t, tc); if (third) third.show(t, r.bloqueur ? tb : tv); } };
};

// R7 · transformation, A devient B (RAIL) : A arrive au lieu ; il en ressort sous la forme B (signal ambre → chose Os).
RECETTES.transformation = r => {
  const a = station(200, 640, 52), m = station(540, 640, 64), b = station(880, 640, 52);
  const v1 = voie('M258 640 L 470 640'), v2 = voie('M610 640 L 822 640');
  const i1 = impulsion(v1, { color: C.ambre }), i2 = impulsion(v2, { color: C.os }), taken = [a.box, m.box, b.box, v1.box, v2.box];
  const ta = T(r.a), tb = T(r.b), tv = T(r.verbe), tl = r.lieu ? T(r.lieu) : 99;
  const tM = first(tv, tb - .5) - HIT, t1 = Math.max(.35, tM - .6), tOut = first(tb, tM + .6) - HIT;
  const PA = placeLabel(L(r.a), [[200, 780], [200, 500], [200, 890]], taken), PB = placeLabel(L(r.b), [[880, 780], [880, 500], [880, 890]], taken);
  const PL = r.lieu ? placeLabel(L(r.lieu), [[540, 500], [540, 385], [540, 935]], taken) : null;
  return { focus: tM + HIT, events: () => [{ name: 'mue', t: tM + HIT, box: m.box }],
    seek(t) { [a, m, b].forEach((s, k) => s.pop(t, .1 + .05 * k)); v1.draw(t, .15); v2.draw(t, .2);
      a.lit(eIn((t - ta + .1) / FAST) * (t < tM ? 1 : .4), C.ambre);
      m.lit(clamp(1 - Math.abs(t - tM) / .3) + .2 * (t > tM), C.os);
      if (t >= t1 && t < tM) i1.at(eIn((t - t1) / (tM - t1))); else i1.hide();
      if (t >= tM && t < tOut + .2) i2.at(eIn((t - tM) / Math.max(.3, tOut - tM)), t < tOut ? 1 : 1 - (t - tOut) / .2); else i2.hide();
      b.lit(eIn((t - tOut) / FAST)); PA.show(t, ta, tM); PB.show(t, first(tb, tOut)); if (PL) PL.show(t, tl, tM + .4); } };
};

// R8 · chiffre, statistique (SOLO) : le compteur se pose sur le mot du nombre ; en pions s'il y a « n sur N » (N ≤ 10).
RECETTES.chiffre = r => {
  const tn = T(r.valeur), tq = r.quoi ? T(r.quoi) : 99, p = parseNum(L(r.valeur)), tot = r.total ? parseNum(L(r.total)) : null;
  const taken = [];
  if (tot && p && tot.val <= 10 && p.val <= tot.val && Number.isInteger(tot.val)) {
    const G = pions(tot.val, 540, 560), ttot = T(r.total), N = verdict(L(r.valeur), 540, 370, { size: 150 }); taken.push(G.box, N.box);
    const PQ = r.quoi ? placeLabel(L(r.quoi), [[540, 935], [540, 840]], taken) : null;
    return { focus: tn, events: () => [{ name: 'valeur', t: tn, box: G.box }],
      seek(t) { G.setAttribute('opacity', eIn((t - Math.min(ttot, tn) + .3) / FAST));
        G.dots.forEach((d, k) => { const off = k >= p.val ? eIn((t - tn + HIT - .05 * (k - p.val)) / FAST) : 0;
          set(d, { fill: mix(C.os, C.nuit, off), 'fill-opacity': 1 - .75 * off, stroke: mix(C.os, C.ardoise, off) }); });
        N.show(t, tn); if (PQ) PQ.show(t, tq); } };
  }
  const N = chiffre(L(r.valeur), 540, 590, { size: 330, from: r.avant ? (parseNum(L(r.avant)) || { val: 0 }).val : 0 }); taken.push(N.box);
  const PQ = r.quoi ? placeLabel(L(r.quoi), [[540, 860], [540, 935], [540, 340]], taken) : null;
  const PA = r.avant ? placeLabel(L(r.avant), [[540, 340], [540, 935]], taken) : null;
  return { focus: tn, events: () => [{ name: 'valeur', t: tn, box: N.box }],
    seek(t) { N.show(t, tn); if (PQ) PQ.show(t, Math.min(tq, tn - .2)); if (PA) PA.show(t, T(r.avant), tn); } };
};

// R9 · trajet dans le corps (RAIL vertical) : les étapes s'allument dans l'ordre dit, dans le bon sens.
RECETTES.trajet = r => {
  const st = (r.etapes || []).slice(0, 3), n = st.length, up = r.sens === 'monte';
  const ys = st.map((_, k) => n === 1 ? 600 : 360 + (880 - 360) * (up ? (n - 1 - k) : k) / (n - 1)), x = 400;
  const v = voie(`M${x} ${ys[0]} L ${x} ${ys[n - 1]}`), S0 = ys.map(y => station(x, y, 46));
  const imp = impulsion(v, { color: C.ambre }), taken = [v.box, ...S0.map(s => s.box)];
  const ts = st.map(s => T(s));
  const P = st.map((s, k) => placeLabel(L(s), [[490, ys[k], 'start'], [x, ys[k] - 100]], taken));
  return { focus: ts[n - 1], events: () => [{ name: 'arrivee', t: ts[n - 1], box: [x - 60, Math.min(...ys) - 60, x + 60, Math.max(...ys) + 60] }],
    seek(t) { v.draw(t, .1, .45); S0.forEach((s, k) => { s.pop(t, .1 + .06 * k); s.lit(eIn((t - ts[k] + HIT) / FAST), C.ambre); });
      let u = -1; for (let k = 1; k < n; k++) { const a = ts[k - 1], b = ts[k] - HIT; if (t >= a && t < b) u = ((k - 1) + eIn((t - a) / Math.max(.2, b - a))) / (n - 1); }
      if (u >= 0) imp.at(u); else imp.hide();
      P.forEach((p, k) => p.show(t, ts[k], k < n - 1 ? ts[k + 1] : 99)); } };
};

// R11 · débat, thèse et contre-thèse (DUO de paroles) : chaque thèse est montrée DITE (entre guillemets), jamais comme
// un fait ; le côté que l'orateur défend s'allume ; « ouvert » = les deux restent et le point d'interrogation pose la question.
RECETTES.debat = r => {
  const cote = r.cote || 'ouvert', cx = 540, py = 470, half = 300, drop = 170, taken = [];
  const t1 = T(r.these), t2 = T(r.contre), tk = first(T(r.bascule), t2 + .5);
  const g = mk($('scene'), 'g', { opacity: 0 });
  mk(g, 'path', { d: `M${cx} ${py + 8} L ${cx - 46} ${py + 96} L ${cx + 46} ${py + 96} Z`, fill: C.nuit, stroke: C.brume, 'stroke-width': 8, 'stroke-linejoin': 'round' });
  const beam = mk(g, 'g');
  mk(beam, 'line', { x1: cx - half, x2: cx + half, y1: py, y2: py, stroke: C.os, 'stroke-width': 12, 'stroke-linecap': 'round' });
  mk(beam, 'circle', { cx, cy: py, r: 14, fill: C.os });
  const pans = [-1, 1].map(sd => { const pg = mk(g, 'g');
    mk(pg, 'line', { x1: cx + sd * half, x2: cx + sd * half - 70, y1: py, y2: py + drop, stroke: C.brume, 'stroke-width': 5 });
    mk(pg, 'line', { x1: cx + sd * half, x2: cx + sd * half + 70, y1: py, y2: py + drop, stroke: C.brume, 'stroke-width': 5 });
    mk(pg, 'path', { d: `M${cx + sd * half - 110} ${py + drop} Q ${cx + sd * half} ${py + drop + 60} ${cx + sd * half + 110} ${py + drop} Z`, fill: C.crep, stroke: C.os, 'stroke-width': 7 });
    return pg; });
  taken.push([cx - half - 120, py - 70, cx + half + 120, py + drop + 110]);    // the beam, the pans and their swing
  const PT = placeLabel('\u201C' + L(r.these) + '\u201D', [[cx - half, 822], [cx - 150, 822], [cx, 925]], taken);
  const PC = placeLabel('\u201C' + L(r.contre) + '\u201D', [[cx + half, 822], [cx + 150, 925], [cx, 925]], taken);
  const Q = cote === 'ouvert' ? pointQ(cx, py - 150, { size: 170 }) : null;
  const tilt = cote === 'these' ? -9 : cote === 'contre' ? 9 : 0;           // degrees: down on the side defended
  return { focus: tk, events: () => [{ name: 'penche', t: tk, box: taken[0] }],
    seek(t) { g.setAttribute('opacity', eIn((t - .1) / STD));
      const q = eIn((t - tk + HIT) / .6), a = tilt * q + (cote === 'ouvert' ? 2.2 * Math.sin(Math.max(0, t - t2) * 2.4) * (t > t2) : 0);
      beam.setAttribute('transform', `rotate(${a} ${cx} ${py})`);
      [-1, 1].forEach((sd, k) => { const rad = a * Math.PI / 180, ex = cx + sd * half * Math.cos(rad), ey = py + sd * half * Math.sin(rad);
        pans[k].setAttribute('transform', `translate(${ex - (cx + sd * half)} ${ey - py})`); });
      PT.show(t, t1, cote === 'these' ? 99 : tk); PC.show(t, t2, cote === 'contre' ? 99 : tk);   // the words stay put: only the pans tip
      if (Q) Q.show(t, tk); } };
};

// R12 · question ouverte (SOLO) : les mots de la question, et un grand point d'interrogation qui reste ouvert.
RECETTES.question = r => {
  const ms = (r.mots || []).slice(0, 2), taken = [];
  const Q = pointQ(540, 560, { size: 400 }); taken.push(Q.box);
  const tq = first(T(r.question), ...ms.map(m => T(m)).map(x => x + .3));
  const P = ms.map((m, k) => placeLabel(L(m), k === 0 ? [[540, 905], [540, 330]] : [[540, 330], [540, 905]], taken));
  return { focus: tq, events: () => [{ name: 'question', t: tq, box: Q.box }],
    seek(t) { Q.show(t, tq); P.forEach((p, k) => p.show(t, T(ms[k]))); } };
};

// R13 · champ de vision (SOLO) : un schéma depuis l'œil (bords en pointillés, arc, voile dégradé) qui se resserre
// (stress, portrait mode, tunnel) ou s'élargit (calme, panoramique), et revient si la phrase le dit.
RECETTES.champ = r => {
  const ex = 250, ey = 600, len = 600, wide = 34, narrow = 5, down = (r.sens || 'resserre') === 'resserre';
  const eye = mk($('scene'), 'g', { class: 'chk', opacity: 0 });
  mk(eye, 'path', { d: `M${ex - 95} ${ey} Q ${ex} ${ey - 70} ${ex + 95} ${ey} Q ${ex} ${ey + 70} ${ex - 95} ${ey} Z`, fill: C.nuit, stroke: C.os, 'stroke-width': 10 });
  mk(eye, 'circle', { cx: ex + 18, cy: ey, r: 34, fill: C.os }); mk(eye, 'circle', { cx: ex + 22, cy: ey, r: 15, fill: C.abyss });
  const g = mk($('scene'), 'g', { opacity: 0 }), ox = ex + 100;
  const veil = mk(g, 'path', { fill: C.os, 'fill-opacity': .16 });
  const e1 = mk(g, 'path', { fill: 'none', stroke: C.os, 'stroke-width': 7, 'stroke-dasharray': '18 12', 'stroke-linecap': 'round' });
  const e2 = mk(g, 'path', { fill: 'none', stroke: C.os, 'stroke-width': 7, 'stroke-dasharray': '18 12', 'stroke-linecap': 'round' });
  const arc = mk(g, 'path', { fill: 'none', stroke: C.os, 'stroke-width': 8, 'stroke-linecap': 'round', opacity: .8 });
  const pts = [...Array(9)].map((_, i) => { const a = (-wide + 2 * wide * (i + .5) / 9) * Math.PI / 180, rr = len * (.6 + .3 * rnd(i + 4));
    return { a, sharp: mk($('scene'), 'circle', { cx: ox + rr * Math.cos(a), cy: ey + rr * Math.sin(a), r: 13, fill: C.os, opacity: 0 }),
      soft: mk($('scene'), 'circle', { cx: ox + rr * Math.cos(a), cy: ey + rr * Math.sin(a), r: 20, fill: C.brume, filter: 'url(#soft)', opacity: 0 }) }; });
  const tm = T(r.mot) - HIT, tb = r.retour ? Math.max(T(r.retour) - HIT, tm + 1.1) : 99, taken = [[ex - 100, ey - 380, 1000, ey + 380]];
  const PR = r.resultat ? placeLabel(L(r.resultat), [[540, 935], [540, 330]], taken) : null;
  const PR2 = r.resultat2 ? placeLabel(L(r.resultat2), [[540, 330], [540, 935]], taken) : null;
  const PC = r.cause && !PR2 ? placeLabel(L(r.cause), [[540, 330], [540, 935]], taken) : null;
  const a0 = down ? wide : narrow, a1 = down ? narrow : wide;
  return { focus: tm + HIT, events: () => [{ name: 'champ', t: tm + HIT, box: [ox, ey - 340, ox + len, ey + 340] }],
    seek(t) { eye.setAttribute('opacity', eIn((t - .1) / STD)); const vis = eIn((t - .3) / STD); g.setAttribute('opacity', vis);
      const q = eIn((t - tm) / .5) * (1 - eIn((t - tb) / .6)), half = (a0 + (a1 - a0) * q) * Math.PI / 180;
      const P1 = [ox + len * Math.cos(-half), ey + len * Math.sin(-half)], P2 = [ox + len * Math.cos(half), ey + len * Math.sin(half)];
      e1.setAttribute('d', `M${ox} ${ey} L${P1[0]} ${P1[1]}`); e2.setAttribute('d', `M${ox} ${ey} L${P2[0]} ${P2[1]}`);
      arc.setAttribute('d', `M${P1[0]} ${P1[1]} A ${len} ${len} 0 0 1 ${P2[0]} ${P2[1]}`);
      veil.setAttribute('d', `M${ox} ${ey} L${P1[0]} ${P1[1]} A ${len} ${len} 0 0 1 ${P2[0]} ${P2[1]} Z`);
      pts.forEach(p => { const inside = clamp(1 - (Math.abs(p.a) - half) / (5 * Math.PI / 180));
        p.sharp.setAttribute('opacity', vis * .95 * inside); p.soft.setAttribute('opacity', vis * .55 * (1 - inside)); });
      if (PR) { PR.show(t, T(r.resultat)); if (tb < 99) PR.setAttribute('opacity', +PR.getAttribute('opacity') * (1 - eIn((t - tb) / .3))); }
      if (PR2) PR2.show(t, T(r.resultat2)); if (PC) PC.show(t, T(r.cause), tm + .4); } };
};

// R0 · mots-clés (le repli sûr, toujours valide) : 2 ou 3 mots dits, empilés, chacun sur son mot ; le dernier en grand.
RECETTES.mots_cles = r => {
  const ms = (r.mots || []).slice(0, 3), n = ms.length, ys = n === 1 ? [600] : n === 2 ? [500, 720] : [420, 610, 820];
  const V = ms.map((m, k) => verdict(L(m), 540, ys[k], { size: k === n - 1 ? 140 : 104, maxw: 820, oneLine: true }));
  const ts = ms.map(m => T(m));
  return { focus: ts[n - 1], events: () => [{ name: 'dernier', t: ts[n - 1], box: V[n - 1].box }],
    seek(t) { V.forEach((v, k) => { v.show(t, ts[k]); const act = clamp(Math.min((t - ts[k] + .1) / .08 + 1, ((k < n - 1 ? ts[k + 1] : 99) - t) / .08));
      v._t.setAttribute('fill', mix(k === n - 1 ? C.os : C.brume, C.ambre, act * (k === n - 1 ? 1 : .8))); }); } };
};
