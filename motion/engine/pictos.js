// Bibliothèque fermée des pictogrammes du motion v2 (direction_v2.md, V2-5), 13/10/2026, motion designer.
//
// À valider au banc ET par elle avant tout usage (rien en prod sans sa validation nommée).
//
// Style :
//   - silhouette plate Os avec un dégradé de volume (lumière du haut) ;
//   - découpes Crépuscule, creux Cadran ;
//   - aucun contour extérieur, aucun visage, aucun texte.
// Les personnes sont anonymes, en buste ou en pied, toujours habillées.
//
// Données SVG pures dans une boîte de 240 × 240 centrée sur (0, 0). Tout le dessin tient dans un rayon de 100 unités,
// soit 0,78 r du médaillon (table FIT, vérifiée par _check_pictos.html).
//
// Branchement (aucune retouche) :
//   const p = picto(cle, g, x, y, r)   // g : le <g> du médaillon ; (x, y) : son centre ; r : son rayon
//   p.tone(k)   // 0 = au repos (Brume), 1 = allumé (Os) ; mélange continu, pour l'allumage en 0,18 s
//   p.idle(t)   // petit geste propre au picto, fonction PURE du temps (chrono, cœur, soleil) ; ne fait rien sinon
//   p.box       // [x0, y0, x1, y1] dans le repère du parent
// picto() rend null pour une clé inconnue : le moteur garde alors la tuile de texte.
// pictoPour(label) rend la clé du picto pour une étiquette du directeur, ou null. Aucun appel d'IA.
// Le groupe rendu n'a pas la classe « chk » : c'est le médaillon qui porte le contrôle des zones.
// Tout est déterministe : aucun aléatoire, aucune horloge ; les identifiants de dégradé sont numérotés.
(function () {
  const NSP = 'http://www.w3.org/2000/svg';
  const el = (parent, tag, attrs) => { const e = document.createElementNS(NSP, tag);
    for (const k in attrs) e.setAttribute(k, attrs[k]); parent.appendChild(e); return e; };
  const hx = c => [1, 3, 5].map(i => parseInt(c.slice(i, i + 2), 16));
  const lerp = (a, b, k) => { const A = hx(a), B = hx(b); k = Math.max(0, Math.min(1, k));
    return '#' + A.map((v, i) => Math.round(v + (B[i] - v) * k).toString(16).padStart(2, '0')).join(''); };

  // the two tones: at rest (Brume, on a Nuit medallion) and lit (Os, on a Crépuscule medallion)
  const TONE = {
    haut:  ['#A4AFD9', '#F7F1E6'],   // top of the volume gradient
    bas:   ['#7987BD', '#E2D7C3'],   // bottom of the volume gradient
    coupe: ['#141E37', '#22305A'],   // cut lines (Nuit at rest, Crépuscule lit: they read as real cut-outs)
    creux: ['#0F1730', '#1A2547'],   // hollows (Cadran)
    ombre: ['#6E7CB2', '#D9CDB6'],   // a shaded face (paper fold, coin centre)
  };
  let N = 0;

  // ---- the drawings. Each one gets (s, ctx): s = shape helpers bound to the picto group.
  // s.f(tag, attrs)       : silhouette (volume gradient)
  // s.cut(d, w)           : cut line (stroke, round caps)
  // s.hole(tag, attrs)    : hollow (Cadran)
  // s.sh(tag, attrs)      : shaded face
  // s.fs(d, w)            : silhouette drawn as a thick stroke (tubes, rays, dendrites)
  // s.g(attrs)            : a sub-group (for the animated parts)
  const D = {
    cerveau: s => { const g = s.g({ transform: 'translate(-2 6) scale(.92)' });
      s.f('path', { d: 'M-100 4 C-108 -46 -70 -94 -16 -96 C22 -112 78 -90 96 -46 C116 -8 104 36 74 50 C62 72 34 76 18 66 C14 74 14 86 10 98 L-8 98 C-8 86 -10 74 -16 64 C-60 72 -96 50 -100 4 Z' }, g);
      ['M-72 -24 C-58 -50 -32 -52 -18 -72', 'M-6 -42 C12 -66 46 -64 62 -46', 'M-80 18 C-58 0 -32 8 -16 -12',
        'M-2 10 C18 -8 48 -6 68 6', 'M-42 46 C-24 32 2 36 12 48'].forEach(d => s.cut(d, 10, g)); },
    oeil: s => {
      s.f('path', { d: 'M-104 0 C-70 -56 -36 -74 0 -74 C36 -74 70 -56 104 0 C70 56 36 74 0 74 C-36 74 -70 56 -104 0 Z' });
      s.cutFill('circle', { cx: 0, cy: 0, r: 46 });
      s.hole('circle', { cx: 0, cy: 0, r: 21 }); },
    oreille: s => {
      s.f('path', { d: 'M-6 -102 C52 -106 90 -66 86 -14 C83 22 60 38 46 56 C34 72 34 90 14 100 C-8 110 -36 98 -40 74 C-44 52 -26 44 -22 26 C-18 8 -40 -6 -48 -30 C-62 -72 -42 -100 -6 -102 Z' });
      s.cut('M-20 -62 C10 -76 52 -60 54 -22 C56 6 36 18 26 34', 11);
      s.cut('M-4 -30 C14 -38 30 -26 26 -8', 10);
      s.hole('ellipse', { cx: 6, cy: 12, rx: 13, ry: 17 }); },
    coeur: s => { const g = s.g({ 'data-anim': 'beat' });   // anatomical: pointed apex low left, aortic arch + 2 stubs
      s.f('path', { d: 'M-58 -36 C-84 0 -76 56 -34 92 C-18 106 -2 108 8 100 C44 74 78 36 76 -6 C74 -38 50 -50 26 -46 C8 -44 -4 -36 -16 -38 C-32 -44 -48 -48 -58 -36 Z' }, g);
      s.fs('M-4 -40 C-6 -92 46 -104 62 -62', 26, g); s.fs('M12 -80 L10 -104', 12, g); s.fs('M32 -86 L36 -106', 12, g);
      s.fs('M-34 -40 L-60 -72', 20, g);
      s.cut('M-20 -28 C-6 12 -12 52 -30 84', 10, g); },
    poumons: s => {
      s.f('path', { d: 'M-16 -50 C-46 -66 -90 -28 -96 34 C-100 80 -76 102 -44 96 C-24 92 -16 74 -16 44 Z' });
      s.f('path', { d: 'M16 -50 C46 -66 90 -28 96 34 C100 80 76 102 44 96 C24 92 16 74 16 44 Z' });
      s.f('rect', { x: -11, y: -104, width: 22, height: 66, rx: 11 });
      s.fs('M0 -44 C-6 -36 -14 -30 -26 -24', 16); s.fs('M0 -44 C6 -36 14 -30 26 -24', 16);
      s.cut('M-32 2 C-52 14 -66 36 -74 52', 10); s.cut('M32 2 C52 14 66 36 74 52', 10); },
    estomac: s => {
      s.f('path', { d: 'M-44 -100 L-16 -100 C-16 -60 -8 -30 8 -26 C30 -20 50 -40 72 -26 C98 -8 100 44 76 74 C50 104 -6 108 -40 84 C-70 62 -70 18 -56 -12 C-46 -34 -44 -60 -44 -100 Z' });
      s.fs('M80 40 C100 48 104 70 92 90', 22);
      s.cut('M-40 40 C-24 18 -4 6 22 2', 10);               // one fold, rising: never a curve that reads as a smile
      s.cut('M70 30 L84 46', 9); },                          // the pylorus, where the duodenum starts
    muscle: s => {   // the flexed arm, traced on the 💪 emoji's own silhouette (the phone test showed it reads at a glance):
      // ONE closed shape, no body around it. The fist is high on the left, bent toward the biceps, with the thumb
      // tucked (the notch under it). The forearm is a straight slant. A deep V. The biceps is a big round ball, far
      // above the line of the arm. The elbow is round, low on the left. Almost no inner lines: at 60 px they read as a face.
      s.f('path', { d: 'M-60.8 -84.4 C-61 -95 -55 -99 -46 -99 L-26 -99 C-4 -100 8 -82 4 -66 C2 -58 -2 -53 -7.6 -50 C-10 -46 -14 -40 -22.8 -38.4 L-44.8 -38.4 L-18.8 12.4 A62 62 0 1 1 41.2 94.4 L-56.8 94.4 A48 48 0 0 1 -104.8 45.6 Z' });
      el(s.root, 'path', { d: 'M65.2 -9.2 A48 48 0 0 1 86.3 16', fill: 'none', stroke: '#FFFFFF', 'stroke-opacity': .5, 'stroke-width': 10, 'stroke-linecap': 'round' });   // the glint on the biceps
      s.cut('M-20 22 L-32 56', 7); },                                              // the fold where the forearm meets the upper arm
    corps: s => {   // a standing figure, anonymous, in a T-shirt and trousers
      s.f('circle', { cx: 0, cy: -80, r: 22 });
      s.f('path', { d: 'M-34 -52 C-50 -52 -58 -42 -60 -26 L-66 26 C-67 36 -55 40 -52 31 L-44 -10 L-40 30 L40 30 L44 -10 L52 31 C55 40 67 36 66 26 L60 -26 C58 -42 50 -52 34 -52 Z' });
      s.f('path', { d: 'M-38 30 L-34 100 C-33 107 -14 107 -12 100 L-4 46 L4 46 L12 100 C14 107 33 107 34 100 L38 30 Z' });
      s.cut('M-40 31 L40 31', 9);                          // the belt line: shirt / trousers
      s.cut('M-14 -52 Q0 -38 14 -52', 8); },                // the crew neck
    lit: s => {
      s.f('rect', { x: -88, y: -56, width: 20, height: 126, rx: 10 });
      s.f('rect', { x: 76, y: -10, width: 16, height: 80, rx: 8 });
      s.f('rect', { x: -74, y: -2, width: 160, height: 50, rx: 18 });
      s.f('rect', { x: -64, y: -32, width: 54, height: 30, rx: 14 });
      s.cut('M-62 -3 L-12 -3', 8);                          // pillow on the mattress
      s.cut('M0 -2 L0 48', 9);                              // the edge of the blanket
      s.cut('M-74 30 L86 30', 8); },                         // the mattress under the blanket
    lune: s => { s.f('path', { d: 'M-2.7 -86 A86 86 0 1 0 80.1 31.4 A72 72 0 1 1 -2.7 -86 Z', transform: 'rotate(-12)' }); },
    soleil: s => { const g = s.g({ 'data-anim': 'rays' });
      for (let k = 0; k < 8; k++) s.f('rect', { x: -9, y: -100, width: 18, height: 32, rx: 9, transform: `rotate(${k * 45})` }, g);
      s.f('circle', { cx: 0, cy: 0, r: 52 }); },
    calendrier: s => {
      s.f('rect', { x: -88, y: -74, width: 176, height: 172, rx: 20 });
      s.cut('M-88 -30 L88 -30', 9);
      s.f('rect', { x: -56, y: -102, width: 18, height: 46, rx: 9 }); s.f('rect', { x: 38, y: -102, width: 18, height: 46, rx: 9 });
      s.hole('circle', { cx: -47, cy: -50, r: 7 }); s.hole('circle', { cx: 47, cy: -50, r: 7 });
      for (const y of [-12, 36]) for (const x of [-66, -17, 32]) s.hole('rect', { x, y, width: 34, height: 32, rx: 8 }); },
    chrono: s => {
      s.f('rect', { x: -20, y: -118, width: 40, height: 26, rx: 9 }); s.f('rect', { x: -9, y: -96, width: 18, height: 16 });
      s.f('rect', { x: 52, y: -98, width: 34, height: 20, rx: 9, transform: 'rotate(42 69 -88)' });
      s.f('circle', { cx: 0, cy: 6, r: 94 });
      s.hole('circle', { cx: 0, cy: 6, r: 72 });
      [0, 90, 180, 270].forEach(a => s.f('rect', { x: -5, y: -60, width: 10, height: 18, rx: 5, transform: `rotate(${a} 0 6)` }));
      const h = s.g({ 'data-anim': 'hand' }); s.fs('M0 6 L0 -44', 12, h);
      s.f('circle', { cx: 0, cy: 6, r: 11 }); },
    telephone: s => { const g = s.g({ transform: 'rotate(-10)' });
      s.f('rect', { x: -54, y: -100, width: 108, height: 200, rx: 24 }, g);
      s.hole('rect', { x: -42, y: -82, width: 84, height: 156, rx: 12 }, g);
      s.cutFill('rect', { x: -14, y: -94, width: 28, height: 7, rx: 3.5 }, g);
      s.cutFill('rect', { x: -16, y: 83, width: 32, height: 8, rx: 4 }, g); },
    document: s => {
      s.f('path', { d: 'M-70 -100 H30 L74 -56 V100 H-70 Z' });
      s.sh('path', { d: 'M30 -100 V-56 H74 Z' });
      s.cut('M30 -100 V-56 H74', 6);
      [[-58, 6], [-30, 48], [-2, 48], [26, 48], [54, 20]].forEach(([y, x1]) => s.cut(`M-46 ${y} L${x1} ${y}`, 11)); },
    flacon: s => { const g = s.g({ transform: 'translate(-18 4) scale(.85)' });   // a bottle and one capsule beside it, never being taken
      s.f('rect', { x: -58, y: -98, width: 116, height: 42, rx: 10 }, g);
      [-30, -10, 10, 30].forEach(x => s.cut(`M${x} -90 L${x} -64`, 9, g));
      s.f('rect', { x: -50, y: -54, width: 100, height: 150, rx: 18 }, g);
      s.cut('M-50 -55 L50 -55', 9, g);
      s.hole('rect', { x: -50, y: -14, width: 100, height: 62 }, g);
      const c = s.g({ transform: 'translate(88 34) rotate(-35)' }, g);
      s.f('rect', { x: -26, y: -12, width: 52, height: 24, rx: 12 }, c); s.cut('M0 -12 L0 12', 8, c); },
    medecin: s => {   // anonymous bust, coat, stethoscope; no face
      s.f('circle', { cx: 0, cy: -56, r: 36 });
      s.f('rect', { x: -15, y: -28, width: 30, height: 26 });
      s.f('path', { d: 'M-84 54 C-78 18 -46 -6 0 -6 C46 -6 78 18 84 54 A100 100 0 0 1 -84 54 Z' });
      s.hole('path', { d: 'M-20 -4 L0 34 L20 -4 Z' });
      s.cut('M-26 -4 L0 48 L26 -4', 9); s.cut('M0 48 L0 96', 8);
      s.cut('M-34 0 C-44 30 -36 56 -16 60', 9); s.cut('M34 0 C40 20 34 40 20 50', 9);
      s.hole('circle', { cx: -12, cy: 64, r: 13 }); },
    personne: s => {   // anonymous bust, crew-neck T-shirt; no face
      s.f('circle', { cx: 0, cy: -56, r: 37 });
      s.f('rect', { x: -15, y: -26, width: 30, height: 22 });
      s.f('path', { d: 'M-84 54 C-78 18 -46 -6 0 -6 C46 -6 78 18 84 54 A100 100 0 0 1 -84 54 Z' });
      s.cut('M-24 -4 Q0 18 24 -4', 9);
      s.cut('M-54 24 C-58 44 -60 62 -60 78', 8); s.cut('M54 24 C58 44 60 62 60 78', 8); },
    neurone: s => { const g = s.g({ transform: 'scale(.9)' });   // soma, 4 dendrites, one axon ending in 2 round terminals
      s.fs('M-40 -42 L-62 -70', 16, g); s.fs('M-62 -70 L-66 -94', 10, g); s.fs('M-62 -70 L-90 -76', 10, g);
      s.fs('M-48 -8 L-86 0', 16, g); s.fs('M-86 0 L-96 20', 10, g);
      s.fs('M0 -46 L10 -82', 14, g); s.fs('M10 -82 L30 -90', 9, g);
      s.fs('M-40 10 L-58 42', 14, g);
      s.fs('M2 -4 C28 16 46 34 58 60', 14, g); s.fs('M58 60 L54 88', 10, g); s.fs('M58 60 L86 72', 10, g);
      s.f('circle', { cx: 54, cy: 92, r: 10 }, g); s.f('circle', { cx: 90, cy: 73, r: 10 }, g);
      s.f('circle', { cx: -20, cy: -20, r: 31 }, g);
      s.hole('circle', { cx: -20, cy: -20, r: 12 }, g); },
  };

  // ---- the fit: [translate x, translate y, scale] per picto, so that EVERY painted point (half stroke included) is
  // within 100 units of the centre = 0.78 r of the medallion (the box is 240 units for r = 128). Computed once by
  // _check_pictos.html (geometry sampled in the browser), baked here: no measuring at render time.
  const FIT = {"cerveau": [-0.2,-4.5,1.035], "oeil": [0,0,0.962], "oreille": [-16.9,-0.6,0.933], "coeur": [-1.6,3.7,0.877], "poumons": [0,3.5,0.823], "estomac": [-22.3,-0.5,0.804], "muscle": [1.5, 2.3, 0.821], "corps": [0,-1.6,0.936], "lit": [-2,-7,0.937], "lune": [0.7,-1.2,1.12], "soleil": [0,0,1], "calendrier": [0,2,0.8], "chrono": [0,9,0.867], "telephone": [0,0,0.946], "document": [-3.5,1.5,0.803], "flacon": [-4.7,-3.1,0.944], "medecin": [0.1,-4,1.023], "personne": [0.1,-3.4,1.002], "neurone": [0.5,-1.4,0.887]};

  // ---- the closed lexicon: label words (lower case) → key. Phrases first, then single words, from the LAST word
  // (the head noun in English). Only literal, concrete things that are named.
  const PHRASES = { 'time to exhaustion': 'chrono', 'reaction time': 'chrono', 'brain cell': 'neurone', 'brain cells': 'neurone',
    'nerve cell': 'neurone', 'nerve cells': 'neurone', 'medical records': 'document', 'whole body': 'corps' };
  const MOTS = {
    cerveau: ['brain', 'brains', 'cortex'], oeil: ['eye', 'eyes', 'eyesight'], oreille: ['ear', 'ears', 'hearing'],
    coeur: ['heart', 'hearts'], poumons: ['lung', 'lungs'], estomac: ['stomach', 'gut', 'belly'],
    muscle: ['muscle', 'muscles', 'bicep', 'biceps'], corps: ['body', 'bodies'],
    lit: ['bed', 'sleep', 'sleeping', 'asleep', 'nap'], lune: ['night', 'nights', 'tonight', 'midnight'],
    soleil: ['morning', 'daylight', 'sunlight', 'sun'], calendrier: ['day', 'days', 'week', 'weeks'],
    chrono: ['hours', 'minutes', 'seconds', 'stopwatch', 'timer', 'duration'],
    telephone: ['phone', 'phones', 'smartphone', 'smartphones', 'cellphone'],
    document: ['record', 'records', 'file', 'files', 'report', 'reports', 'paperwork', 'document', 'documents'],
    flacon: ['pill', 'pills', 'medication', 'medications', 'medicine', 'medicines', 'prescription', 'prescriptions'],
    medecin: ['doctor', 'doctors', 'physician', 'physicians', 'surgeon', 'surgeons', 'nurse', 'nurses'],
    personne: ['person', 'patient', 'patients', 'someone', 'people', 'individual'],
    neurone: ['neuron', 'neurons', 'neurone', 'neurones'],
  };
  // never a picto, whatever else the label says (a label that names one of these keeps its text tile only)
  const INTERDITS = ['syringe', 'syringes', 'needle', 'needles', 'injection', 'injections', 'pen', 'pens', 'shot',
    'drug', 'drugs', 'cocaine', 'heroin', 'marijuana', 'cannabis', 'weed', 'psychedelic', 'psychedelics', 'lsd', 'dmt',
    'alcohol', 'drunk', 'beer', 'wine', 'vodka', 'drink', 'drinks', 'cigarette', 'cigarettes', 'smoking',
    'gun', 'guns', 'weapon', 'knife', 'blood', 'skull', 'death', 'dead', 'die', 'dying', 'kill', 'suicide', 'overdose',
    'poison', 'grave', 'coffin', 'funeral', 'cancer', 'tumor', 'tumors', 'tumour', 'wound'];
  const INDEX = {}; for (const k in MOTS) MOTS[k].forEach(w => { INDEX[w] = k; });

  function pictoPour(label) {
    const words = String(label || '').toLowerCase().replace(/[^a-z' -]/g, ' ').split(/[\s-]+/).filter(Boolean);
    if (!words.length || words.some(w => INTERDITS.includes(w.replace(/'s$/, '')))) return null;
    const txt = words.join(' ');
    for (const p in PHRASES) if ((' ' + txt + ' ').includes(' ' + p + ' ')) return PHRASES[p];
    for (let k = words.length - 1; k >= 0; k--) { const w = words[k].replace(/'s$/, ''); if (INDEX[w]) return INDEX[w]; }
    return null;
  }

  function picto(cle, g, x, y, r, o = {}) {
    const draw = D[cle]; if (!draw) return null;
    const id = 'pv' + (++N), sc = (o.scale || 1) * r / 128;
    const root = el(g, 'g', { class: 'picto', 'data-picto': cle, transform: `translate(${x} ${y}) scale(${sc.toFixed(4)})` });
    const defs = el(root, 'defs', {});
    const lg = el(defs, 'linearGradient', { id, gradientUnits: 'userSpaceOnUse', x1: 0, y1: -110, x2: 0, y2: 110 });
    const s0 = el(lg, 'stop', { offset: 0 }), s1 = el(lg, 'stop', { offset: 1 });
    const fit = FIT[cle] || [0, 0, 1], fitT = `scale(${fit[2]}) translate(${fit[0]} ${fit[1]})`;
    const clipR = 128 - 4 / sc;                        // the inner edge of an 8 px ring, in box units, whatever r is
    const cp = el(defs, 'clipPath', { id: id + 'c' }); el(cp, 'circle', { cx: 0, cy: 0, r: clipR.toFixed(2) });
    const clipG = el(root, 'g', { 'clip-path': `url(#${id}c)` });
    const body = el(clipG, 'g', { transform: fitT });
    const cuts = [], holes = [], shades = [], shadeStrokes = [], anim = {};
    const s = {
      root: body,
      g: (a, p = body) => { const e = el(p, 'g', a); if (a['data-anim']) anim[a['data-anim']] = e; return e; },
      f: (tag, a, p = body) => el(p, tag, Object.assign({ fill: `url(#${id})` }, a)),
      fs: (d, w, p = body) => el(p, 'path', { d, fill: 'none', stroke: `url(#${id})`, 'stroke-width': w, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }),
      cut: (d, w, p = body) => { const e = el(p, 'path', { d, fill: 'none', 'stroke-width': w, 'stroke-linecap': 'round', 'stroke-linejoin': 'round' }); cuts.push(e); return e; },
      cutFill: (tag, a, p = body) => { const e = el(p, tag, a); e.dataset.cf = '1'; cuts.push(e); return e; },
      hole: (tag, a, p = body) => { const e = el(p, tag, a); holes.push(e); return e; },
      sh: (tag, a, p = body) => { const e = el(p, tag, a); shades.push(e); return e; },
      sleeve: (d, w) => {   // a band of width w along the medallion edge, only where the drawing d is (its own outline)
        const ac = el(defs, 'clipPath', { id: id + 'a' }); el(ac, 'path', { d, transform: fitT });
        const lc = el(defs, 'clipPath', { id: id + 'l' }); el(lc, 'rect', { x: -200, y: -200, width: 150, height: 400 });   // the left side only
        const sg = el(el(clipG, 'g', { 'clip-path': `url(#${id}l)` }), 'g', { 'clip-path': `url(#${id}a)` });
        shadeStrokes.push(el(sg, 'circle', { cx: 0, cy: 0, r: (clipR - w / 2).toFixed(2), fill: 'none', 'stroke-width': w + 2 }));
        cuts.push(el(sg, 'circle', { cx: 0, cy: 0, r: (clipR - w).toFixed(2), fill: 'none', 'stroke-width': 7 })); },
    };
    draw(s);
    root.tone = k => {
      s0.setAttribute('stop-color', lerp(TONE.haut[0], TONE.haut[1], k)); s1.setAttribute('stop-color', lerp(TONE.bas[0], TONE.bas[1], k));
      const c = lerp(TONE.coupe[0], TONE.coupe[1], k), h = lerp(TONE.creux[0], TONE.creux[1], k), o2 = lerp(TONE.ombre[0], TONE.ombre[1], k);
      cuts.forEach(e => e.setAttribute(e.dataset.cf ? 'fill' : 'stroke', c)); holes.forEach(e => e.setAttribute('fill', h));
      shades.forEach(e => e.setAttribute('fill', o2)); shadeStrokes.forEach(e => e.setAttribute('stroke', o2)); return root; };
    root.idle = t => {   // pure function of time; amplitudes stay under the « secondary » limits (V2-9)
      if (anim.hand) anim.hand.setAttribute('transform', `rotate(${(30 + 180 * t) % 360} 0 6)`);
      if (anim.beat) { const b = Math.pow(Math.max(0, Math.sin(2 * Math.PI * 1.1 * t)), 6);
        anim.beat.setAttribute('transform', `translate(0 20) scale(${(1 + .04 * b).toFixed(4)}) translate(0 -20)`); }
      if (anim.rays) anim.rays.setAttribute('transform', `rotate(${(6 * t) % 360})`);
      return root; };
    root.box = [x - 100 * sc, y - 100 * sc, x + 100 * sc, y + 100 * sc];
    root.key = cle;
    root.tone(o.tone === undefined ? 1 : o.tone); root.idle(0);
    return root;
  }

  window.picto = picto;
  window.pictoPour = pictoPour;
  window.PICTOS = { cles: Object.keys(D), mots: MOTS, phrases: PHRASES, interdits: INTERDITS };
})();
