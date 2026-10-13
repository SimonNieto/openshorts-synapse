"""Le DIRECTEUR du motion seul (13/10/2026) : UN appel IA par clip ClipGen, et une animation pour CHAQUE clip.
Il lit le clip entier, choisit UN moment et UNE relation de la liste fermée, et remplit ses rôles avec des numéros de
mots dits. Le code vérifie et répare (check / normalize) ; si la fiche reste invalide, il se replie sur la recette
« mots_cles » (les mots dits, en typographie animée), toujours valide. Il ne rappelle jamais l'IA.
Règles : CHARTE_BROLL.md §1 (sens), brief de l'équipe motion (ses décisions du 13/10), grammaire_v0 du motion designer."""
import json, re, sys

# (the repo root is already on the path: motion_director sits next to broll.py)

LEAD, HOLD, MAX_D, MIN_D, PRE, SHORTEST = .8, .6, 6.0, 4.0, 1.0, 3.5
LEADS = {"chiffre": .35, "mots_cles": .35, "question": .35, "debat": .35}   # text first: never an empty screen
HEAD, TAIL = 6.0, 1.0            # never in the hook (first 6 s), always end on the face (last 1 s) — integration_v0 §3.1

RELATIONS = {
    # name: (required roles, optional roles, list roles {name: (min, max)})
    "niveau": (["quantite", "verbe"], ["valeur", "cause"], {}),
    "reference": (["quantite", "reference", "verbe"], ["valeur"], {}),
    "cause_effet": (["cause", "lien", "effet"], ["valeur"], {}),
    "contraste": (["a", "b", "bascule"], ["quoi"], {}),
    "etapes": ([], [], {"etapes": (2, 4)}),
    "boucle": ([], ["emballement", "accent"], {"stations": (2, 3)}),
    "blocage": (["source", "cible", "verbe"], ["bloqueur"], {}),
    "transformation": (["a", "b", "verbe"], ["lieu"], {}),
    "chiffre": (["valeur"], ["quoi", "total", "avant"], {}),
    "trajet": ([], [], {"etapes": (2, 3)}),
    "champ": (["mot"], ["resultat", "retour", "resultat2", "cause"], {}),
    "debat": (["these", "contre"], ["bascule"], {}),
    "question": (["question"], [], {"mots": (1, 2)}),
    "mots_cles": ([], [], {"mots": (2, 3)}),
}
# the roles SHOWN AS TEXT (a label is required and checked); the other roles are moments ({i}); a label given to a
# moment role is used when it is valid (a verdict) and dropped by normalize when it is not
TEXT = {"niveau": {"quantite", "valeur", "cause"}, "reference": {"quantite", "reference", "valeur"},
        "cause_effet": {"cause", "effet", "valeur"}, "contraste": {"a", "b", "quoi"}, "etapes": {"etapes"},
        "boucle": {"stations"}, "blocage": {"source", "cible", "bloqueur"}, "transformation": {"a", "b", "lieu"},
        "chiffre": {"valeur", "quoi", "total", "avant"}, "trajet": {"etapes"}, "champ": {"resultat", "resultat2", "cause"},
        "debat": {"these", "contre"}, "question": {"mots"}, "mots_cles": {"mots"}}
OUTCOME = re.compile(r"\b(remission|relapse|recurrence|survival|mortality|tumou?r|cancer|chemo\w*|dose|doses|dosing)\b", re.I)
GAUGES = {"niveau", "reference", "cause_effet", "contraste", "chiffre", "etapes"}
BANNED = re.compile(r"\b(die|dies|died|dying|death|deaths|dead|kill|kills|killed|killing|suicide|overdose|corpse|murder)\b", re.I)

PROMPT = """You are the motion director of "The Synapse Cut", YouTube Shorts cut from health and neuroscience podcasts
(Huberman, Walker, Rogan). The viewer scrolls on a phone, hears the voice and reads a one-word caption.
In EVERY clip we insert ONE full-screen motion graphic of 4 to 6 seconds (no character, no picture: simple shapes,
gauges, counters, paths, and the spoken words as labels) that makes the viewer SEE the idea of that moment.
EVERY clip gets one — there is no "no picture" answer. Choose the best moment and the relation that shows it honestly.

THE CLIP: "@@TITLE@@"
Its words, numbered, with the time each is heard (seconds from the clip start; the clip lasts @@DUR@@ s):
@@WORDS@@

WHERE: every word you use must be heard between @@LO@@ s and @@HI@@ s, and all of them within 4.5 seconds.

THE CLOSED LIST OF RELATIONS (use exactly one; roles take word numbers "i" and, for texts, a "label"):
A. Mechanisms of the body, the brain, the perception (stated as FACT by the expert):
- "niveau": a quantity rises or drops — a gauge moves on the verb. roles: quantite {i, label}, verbe {i, label},
  sens "hausse"|"baisse", depart (0-1), arrivee (0-1, consistent with what is said: "drops by 30%" -> 0.8 then 0.56),
  valeur {i, label} (the number as said, optional), cause {i, label} (optional).
- "reference": a quantity reaches / passes / stays below a reference said ("like someone 10 years older", "as impaired
  as a drunk", "above normal"). roles: quantite, reference, verbe {i, label}, position "atteint"|"depasse"|"sous",
  sens "baisse" (lower, less, drops, older, senior: the gauge comes DOWN to the line) | "hausse" (it rises to it),
  valeur (optional). The reference is a LINE with its words, never the thing itself.
- "cause_effet": a named cause changes a named effect. roles: cause, lien {i} (the linking verb), effet,
  sens_effet "hausse"|"baisse", valeur (optional).
- "contraste": two situations A and B, one difference that flips on a word. roles: a, b, bascule {i}, gagnant "a"|"b"
  (which side gets more), sens "plus"|"moins", quoi {i, label} (what is compared, optional).
- "etapes": 2 to 4 steps in the order said (a process, or the steps of a story). roles: etapes [{i, label}].
- "boucle": thoughts or a cycle that keep coming back. roles: stations [{i, label}] (2-3), emballement {i} (optional),
  accent {i, label} (the meaning word, e.g. LOOPING, optional).
- "blocage": something fails to reach its target (can't, doesn't, blocks). roles: source, cible, verbe {i, label} (the
  negation AND its verb, e.g. CAN'T SEND), bloqueur {i, label} (only if a blocker is named, e.g. ALCOHOL).
- "transformation": A becomes B (at a place). roles: a, b, verbe {i}, lieu {i, label} (optional).
- "chiffre": a striking number said. roles: valeur {i, label} (the number only: "30%", "8", "251,000"), quoi {i, label}
  (what is counted, e.g. DAYS, HOURS OF SLEEP), total {i, label} (for "7 of 10", "round 7 rather than round 10"),
  avant {i, label} (the number before, optional).
- "trajet": a signal travels inside the body through 2-3 named places in order. roles: etapes [{i, label}],
  sens "descend" (a command, the brain to the body) | "monte" (a sensation, to the brain).
- "champ": the field of VISION narrows (stress, tunnel vision, portrait mode) or widens (calm, panoramic). roles:
  sens "resserre"|"elargit", mot {i}, resultat {i, label} (optional), retour {i} and resultat2 {i, label} (when it goes
  back the other way, optional), cause {i, label} (optional).
B. The shape of an argument (for opinions, debates, stories, speculation, AI, medicine — never shown as a body fact):
- "debat": a claim and the opposite claim, each shown as SAID (in quotes). roles: these {i, label}, contre {i, label},
  cote "these"|"contre"|"ouvert" (the side the speaker takes, or open), bascule {i} (optional).
- "question": an open question or a hypothesis that stays open. roles: mots [{i, label}] (1-2), question {i}.
- "mots_cles": the 2-3 key spoken words, one after the other (only when nothing above fits). roles: mots [{i, label}].

HOW TO DECIDE (the channel's rules):
- Read the whole clip; pick the moment where SEEING the relation makes the idea clearer. Prefer, in this order: a
  mechanism stated as fact (A), a striking number, a contrast; for an opinion, a debate or a story use B honestly:
  an opinion stays an opinion ("debat", "question"), a hypothesis stays open, never a body mechanism.
- The direction and the verb decide: a sensation goes up, a command goes down; "can't" is a failure; a relation that
  shows the opposite of the sentence is forbidden. Nothing figurative taken literally, nothing the speaker denies,
  no mechanism he does not state.
- Labels: the exact spoken words at those numbers (UPPERCASE, 18 characters at most, 1 to 3 words), never a quote of a
  sentence, never a figure of speech (MONKEY BRAIN -> BRAIN), and each names its thing BY ITSELF (EXHAUSTION, DREAM
  SLEEP — never TIME, LEVEL, THING). A relation label carries the negation AND its verb (CAN'T SEND).
- TWO REGISTERS. Body register (A) only when all four hold: a process, in the body / brain / perception, stated as a
  FACT by the expert, and seeing it helps. Otherwise argument register (B), which keeps it honest:
  * never body imagery for an opinion, a story or a hypothesis (no "trajet", no body "niveau");
  * the status is said with the speaker's own words when the window has one: POSSIBLE, PERHAPS, MAYBE, ONE CASE,
    THEORY, I THINK — that word becomes a label (a "mots_cles" or a "question" label, or the "these" of a "debat");
  * an open question or an unknown stays open ("question"), never shown answered;
  * a reported story is a sequence of steps ("etapes"), never a gauge or a counter — a number from a story goes in the
    steps as said, never in the counter;
  * a "full / solid" state only when the speaker cites data ("we know", "the data say").
- THE QUANTITY THAT MOVES IS THE ONE THAT CHANGES: "the pressure for dream sleep builds" -> label PRESSURE (not DREAM
  SLEEP); a cost ("costs more resources", "drains you") shows what is LEFT going down, never a rising gauge that reads
  as a gain. A number keeps its qualifier in the same label: UP TO 30%, ABOUT 7, ALMOST HALF.
- A red bar across the path ("blocage" with "bloqueur") only when the speaker names an obstacle ON THE PATH; when the
  source itself fails (stress, exhaustion), no bloqueur: the order smothers in the source.
- A PAST BELIEF ("it was thought", "they showed that it cannot", followed by "I don't buy that") is never shown as a
  fact: use "debat" (the old claim against the new one) or the words of the new fact.
- No gauge for a feeling of opinion or a hyperbole (nauseous, visceral, like cement, monkey brain): use "debat" or
  "mots_cles". A figure of speech is never a label, not even inside a debate.
- CANCER, SERIOUS ILLNESS, MEDICATION, DOSES: never an outcome gauge (remission, relapse, recurrence, survival,
  mortality) and never steps of "taking a treatment" (it reads as advice) — use "question" or the words of the
  uncertainty. If the quantity said contradicts the speaker's own conclusion ("lower rate of remission" then "it works,
  a very strong effect"), it is a slip of the tongue: do not animate that quantity.
- NEVER anything about death, dying or killing: no number of deaths (even when the word "die" is not in the window —
  "251,000 a year" for medical errors IS a death count), no ALIVE / DYING label, no hospital, nothing of its means.
  Never a person's name, never a drug dose, nothing that reads as medical advice. If the clip is about deaths or a
  person, animate ANOTHER line of the same clip (a term, a method, a duration, the argument), never the person.

Return JSON: {"phrase_spectateur": "<in French: what the viewer must have understood after the moment>",
"mot_sens": "<the word that carries the idea>", "relation": "<one name of the list>", "roles": {...}, "why": "<one short
sentence>"}"""

SCHEMA = {"type": "object", "properties": {
    "phrase_spectateur": {"type": "string"}, "mot_sens": {"type": "string"}, "relation": {"type": "string"},
    "roles": {"type": "object"}, "why": {"type": "string"}}, "required": ["phrase_spectateur", "relation", "roles"]}


def word_lines(words):
    return "\n".join(f'[{k}] ({w["start"]:.2f}s) {w["text"]}' for k, w in enumerate(words))


def window(words, dur):
    return HEAD + LEAD, dur - TAIL - HOLD


def ask(title, words, dur, model="opus", effort="high", reuse=True):
    import broll
    lo, hi = window(words, dur)
    prompt = (PROMPT.replace("@@TITLE@@", title or "").replace("@@DUR@@", f"{dur:.1f}")
              .replace("@@WORDS@@", word_lines(words)).replace("@@LO@@", f"{lo:.1f}").replace("@@HI@@", f"{hi:.1f}"))
    return broll.claude_json(prompt, SCHEMA, timeout=600, stage="motion_directeur", model=model, effort=effort,
                             reuse=reuse) or {}


# ---------------------------------------------------------------- the code's side: check, repair, fall back
_NUM = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
        "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12", "fifteen": "15", "twenty": "20",
        "thirty": "30", "forty": "40", "fifty": "50", "hundred": "100", "percent": "%"}


def _toks(s):
    s = str(s).lower().replace("%", " % ").replace("’", "'")
    out = []
    for t in re.findall(r"[a-z0-9',.]+|%", s):
        t = t.strip(".,'") if t not in ("%",) else t
        t = t.replace(",", "")
        if t:
            out.append(_NUM.get(t, t))
    return out


def _idx(v):
    return v.get("i") if isinstance(v, dict) else v


def near_death(words, i, span=10):
    """A number said within 10 words of « die / death / kill… » counts deaths: never shown (her rule: nothing of a death)."""
    return any(BANNED.search(words[k]["text"]) for k in range(max(0, i - span), min(len(words), i + span + 1)))


_COMMON = {"i", "i'm", "i've", "i'll", "i'd", "okay", "ok", "so", "and", "but", "the", "a", "if", "you", "we", "it", "it's"}


def proper_name(label, words, i):
    """A label word that is a person's or a place's name: Title-case in the transcript, not at a sentence start, not an
    acronym (REM, MRI, AI stay allowed). Her rule: never a real person."""
    toks = set(_toks(label))
    for k in range(max(0, i - 4), min(len(words), i + 5)):
        w = re.sub(r"[^\w'-]", "", words[k]["text"])
        if not w or w.lower() not in toks or w.isupper() or not w[0].isupper() or w.lower() in _COMMON:
            continue
        prev = words[k - 1]["text"].strip() if k else "."
        if not prev.endswith((".", "?", "!")):
            return w
    return None


# the heads that turn the direction around: « time TO exhaustion » drops when exhaustion comes sooner; a « risk OF »,
# a « lack OF », a « loss OF » rise when the thing falls. « levels of testosterone » does not invert anything.
INVERTING = {("time", "to"), ("lack", "of"), ("loss", "of"), ("risk", "of"), ("fear", "of"), ("absence", "of"),
             ("need", "for"), ("resistance", "to")}


def inverting_head(label, words, i):
    """(index of the head, its two words) when an inverting head stands 1-3 words before the label's first word."""
    first_tok = (_toks(label) or [""])[0]
    lt = _toks(label)
    for j in range(max(1, i - 4), min(len(words), i + 5)):
        if _toks(words[j]["text"])[:1] != [first_tok]:
            continue
        for p in range(max(0, j - 4), j - 1):
            pair = tuple((_toks(words[p]["text"]) or [""])[:1] + (_toks(words[p + 1]["text"]) or [""])[:1])
            if pair in INVERTING and not (len(lt) > 1 and lt[0] == pair[0]):
                return p, pair
        return None
    return None


def cut_phrase(label, words, i):
    """The label starts right after a spoken « to » / « of »: it is the end of a longer quantity (« time to exhaustion »)
    and could say the opposite on a gauge."""
    return inverting_head(label, words, i) is not None


def label_ok(label, words, i):
    """Every token of the label is a spoken word within 4 words of i (numbers written as digits or words)."""
    near = set()
    for k in range(max(0, i - 4), min(len(words), i + 5)):
        near.update(_toks(words[k]["text"]))
    lt = _toks(label)
    return bool(lt) and all(t in near or t.isdigit() and any(t in n for n in near) for t in lt)


def roles_used(rel, roles):
    req, opt, lists = RELATIONS[rel]
    out = []
    for k in req + opt:
        if isinstance(roles.get(k), dict) and isinstance(roles[k].get("i"), int):
            out.append(roles[k]["i"])
    for k in lists:
        out += [x["i"] for x in roles.get(k) or [] if isinstance(x, dict) and isinstance(x.get("i"), int)]
    return out


def check(m, words, dur):
    """[] if the sheet can be rendered as it is, else the list of what is wrong (after normalize)."""
    rel, roles = m.get("relation"), m.get("roles") or {}
    if rel not in RELATIONS:
        return [f"relation inconnue {rel}"]
    req, opt, lists = RELATIONS[rel]
    errs = []
    lo, hi = window(words, dur)
    def one(k, v, need_label):
        i = _idx(v)
        if not isinstance(i, int) or not 0 <= i < len(words):
            return [f"{k}: mot {i} hors du clip"]
        e = []
        if not lo - .05 <= words[i]["start"] <= hi:
            e.append(f"{k}: mot {i} à {words[i]['start']:.1f} s, hors de {lo:.1f}-{hi:.1f}")
        if need_label:
            lab = (v.get("label") or "") if isinstance(v, dict) else ""
            if not lab:
                e.append(f"{k}: pas d'étiquette")
            elif len(lab) > 18:
                e.append(f"{k}: étiquette trop longue ({lab})")
            elif BANNED.search(lab):
                e.append(f"{k}: mot interdit ({lab})")
            elif proper_name(lab, words, i):
                e.append(f"{k}: nom propre ({proper_name(lab, words, i)})")
            elif rel in GAUGES and k in ("quantite", "effet") and cut_phrase(lab, words, i):
                e.append(f"{k}: « {lab} » est la fin d'une quantité plus longue (son sens peut s'inverser)")
            elif rel in GAUGES and OUTCOME.search(lab):
                e.append(f"{k}: issue médicale sur une jauge ou des étapes ({lab})")
            elif not label_ok(lab, words, i):
                e.append(f"{k}: « {lab} » n'est pas dit près du mot {i}")
            elif re.search(r"\d", lab) and near_death(words, i):
                e.append(f"{k}: chiffre dit à côté d'une mort ({lab})")
        return e
    for k in req:
        if k not in roles:
            errs.append(f"rôle {k} manquant")
        else:
            errs += one(k, roles[k], k in TEXT[rel] or bool(isinstance(roles[k], dict) and roles[k].get("label")))
    for k in opt:
        if k in roles and roles[k]:
            errs += one(k, roles[k], k in TEXT[rel] or bool(isinstance(roles[k], dict) and roles[k].get("label")))
    for k, (a, b) in lists.items():
        xs = roles.get(k) or []
        if not a <= len(xs) <= b:
            errs.append(f"{k}: {len(xs)} éléments ({a} à {b})")
        for x in xs:
            errs += one(k, x, True)
    used = roles_used(rel, roles)
    if used:
        span = words[max(used)]["end"] - words[min(used)]["start"]
        if span > MAX_D - HOLD + PRE:              # a word said up to PRE s before the shot is already on screen at t=0
            errs.append(f"mécanisme de {span:.1f} s ({MAX_D - HOLD + PRE:.1f} au plus)")
    else:
        errs.append("aucun mot joué")
    return errs


def _text_ok(x, words, dur):
    """One {i, label} that can be shown: in the window, spoken there, short, allowed."""
    probe = {"relation": "mots_cles", "roles": {"mots": [x, x]}}
    return not [e for e in check(probe, words, dur) if "mécanisme" not in e]


def normalize(m, words, dur):
    """Repairs that never need the AI: drop a broken optional role, sort steps by time, clamp levels."""
    rel, roles = m.get("relation"), dict(m.get("roles") or {})
    if rel not in RELATIONS:
        return m
    req, opt, lists = RELATIONS[rel]
    probe = {"relation": rel, "roles": {}}
    for k in opt:
        if k in roles:
            probe["roles"] = {kk: vv for kk, vv in roles.items() if kk in req or kk in lists}
            probe["roles"][k] = roles[k]
            errs = [e for e in check(probe, words, dur) if e.startswith(k + ":")]
            if errs:
                roles.pop(k)
    for k in req:
        v = roles.get(k)
        if k not in TEXT[rel] and isinstance(v, dict) and v.get("label") and not _text_ok(v, words, dur):
            roles[k] = {kk: vv for kk, vv in v.items() if kk != "label"}
    for k in lists:
        xs = [x for x in roles.get(k) or [] if isinstance(x, dict) and isinstance(x.get("i"), int)]
        xs = [x for x in xs if _text_ok(x, words, dur)]
        roles[k] = sorted(xs, key=lambda x: x["i"])[:RELATIONS[rel][2][k][1]]
    # a label whose words are all inside another label says nothing new (« 10 YEARS » next to « 10 YEARS SENIOR »): dropped
    labs = [(k, v) for k, v in roles.items() if isinstance(v, dict) and v.get("label") and k in opt]
    alls = [_toks(v["label"]) for v in roles.values() if isinstance(v, dict) and v.get("label")]
    for k, v in labs:
        mine = _toks(v["label"])
        if any(set(mine) < set(o) or (set(mine) == set(o) and o is not mine and len(mine) <= len(o)) for o in alls if o != mine or alls.count(o) > 1):
            roles.pop(k)
    # a measured quantity cut from its phrase can say the opposite (« EXHAUSTION » for « time TO exhaustion »):
    # the label takes the whole spoken « X to Y » / « X of Y » back when it fits
    for k in ("quantite", "effet"):
        v = roles.get(k)
        if rel in GAUGES and isinstance(v, dict) and v.get("label") and isinstance(v.get("i"), int):
            h = inverting_head(v["label"], words, v["i"])
            if h:                                      # « TIME TO » + the label (an adjective between may be left out)
                full = f"{h[1][0]} {h[1][1]} {v['label']}".upper()
                if len(full) <= 18:
                    roles[k] = dict(v, label=full, i=h[0])
    for k in ("depart", "arrivee"):
        if k in roles:
            try:
                roles[k] = max(0.0, min(1.05, float(roles[k])))
            except (TypeError, ValueError):
                roles.pop(k)
    m = dict(m, roles=roles)
    return m


def fallback(m, words, dur):
    """The safe sheet: 2-3 key spoken words in a 4.5 s window — from the director's own labels when they are valid,
    else from the clip's strongest words. Always renders."""
    lo, hi = window(words, dur)
    cands = []
    for v in (m.get("roles") or {}).values():
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, dict) and isinstance(x.get("i"), int) and x.get("label") and _text_ok(x, words, dur):
                cands.append({"i": x["i"], "label": x["label"].upper()})
    if len(cands) < 2:
        import viral_fx
        scored = []
        for k, w in enumerate(words):
            if lo <= w["start"] <= hi:
                s = viral_fx.keyword_score(w["text"])
                if s > 0 and not BANNED.search(w["text"]) and not (re.search(r"\d", w["text"]) and near_death(words, k))                         and not proper_name(w["text"], words, k):
                    scored.append((s, k))
        best = None
        for s, k in scored:                      # the densest 4 s with the strongest words
            group = sorted([(s2, k2) for s2, k2 in scored if 0 <= words[k2]["start"] - words[k]["start"] <= 4.0], reverse=True)[:3]
            tot = sum(g[0] for g in group)
            if len(group) >= 2 and (best is None or tot > best[0]):
                best = (tot, sorted(g[1] for g in group))
        if best:
            cands = [{"i": k, "label": re.sub(r"[^\w'%$-]", "", words[k]["text"]).upper()} for k in best[1]]
    seen, uniq = set(), []
    for c in sorted({c["i"]: c for c in cands}.values(), key=lambda c: c["i"]):
        if c["label"] not in seen:                 # never the same word twice on screen
            seen.add(c["label"]); uniq.append(c)
    cands = uniq
    while len(cands) > 2 and words[cands[-1]["i"]]["end"] - words[cands[0]["i"]]["start"] > MAX_D - HOLD + PRE:
        cands.pop()
    return {"phrase_spectateur": m.get("phrase_spectateur", ""), "mot_sens": m.get("mot_sens", ""),
            "relation": "mots_cles", "roles": {"mots": cands[:3]}, "why": "repli : " + (m.get("why") or ""), "repli": True}


def decide(title, words, dur, **kw):
    """The whole decision for one clip: ONE AI call, then code only. Returns (sheet, report)."""
    ans = ask(title, words, dur, **kw)
    first = check(ans, words, dur) if ans else ["pas de réponse"]
    m = normalize(ans, words, dur) if ans else {}
    errs = check(m, words, dur) if m else ["pas de réponse"]
    rep = {"premier_check": first, "apres_reparation": errs}
    if errs:
        m = fallback(ans or {}, words, dur)
        rep["repli"] = check(m, words, dur)
    return m, rep
