"""What the art director learns from the owner (4-oct-2026, the user: « quand je vois une erreur sur la photo, je
l'explique, et pour les prochaines photos l'IA apprend de ce que je lui ai expliqué »; then « chaque ajout vérifiable
comme tu fais là, et que ça modifie de la même manière pour que tout reste cohérent »).

1. A 👍 / 👎 of the B-roll gallery, with why and what to change, becomes ONE proposed lesson: the AI writes it from
   her words and the picture's context — a principle, never a fix of that picture nor a list of things.
2. The check (« Vérifier »): the AI rewrites the WHOLE set of kept lessons with the new one (one coherent set: repeats
   merged, the newest wins a contradiction); the art director then draws the critiqued moment and three fixed
   reference moments of other clips twice — with the current set, with the new set — same seeds, through the very
   code of the production (broll_draw.direct_and_verify, picture_text); a before / after board.
3. « Appliquer »: the kept set becomes exactly the set that was checked. Nothing applies without a check, and a check
   goes stale when the kept set or the lesson's text changes after it.

The kept ones go into the art director's call of the « dessin » chain (broll_draw) when plus.BROLL["lessons"] is on.
Kept in output/_lessons/ (director_lessons.json, reference_moments.json, checks/<lesson>/)."""
import hashlib
import json
import os
import threading
import time
import uuid

import broll_gallery

LESSONS_FILE = os.path.join("_lessons", "director_lessons.json")
REFS_FILE = os.path.join("_lessons", "reference_moments.json")
CHECKS_DIR = os.path.join("_lessons", "checks")
STATUSES = ("proposed", "kept", "refused")
MAX_IN_PROMPT = 30
MAX_TEXT = 500
N_REFS = 3
STALE_SECONDS = 30 * 60

LESSON_PROMPT = """Tu aides le directeur artistique d'une chaîne YouTube à apprendre des remarques de sa propriétaire.
Le directeur lit une phrase d'un clip et écrit le texte d'UNE image dessinée (un modèle d'image la dessine ensuite,
le code ajoute la phrase de style de la charte en tête du texte).

Elle a mis {verdict} à cette image :
- phrase du clip : « {said} »
- idée du directeur : « {idea} »
- texte envoyé au modèle d'image : « {prompt} »
- pourquoi, selon elle : « {why} »
- ce qu'elle veut changer : « {change} »

Écris UNE leçon pour les PROCHAINES images, en français, une ou deux phrases :
- un principe général que le directeur applique quand il écrit le texte d'une image, pas une correction de
  celle-ci, pas une liste d'objets ni de scènes ;
- si la cause tient à la façon dont le texte a été écrit (un mot qui pousse le modèle d'image vers ce qu'elle
  n'aime pas), la leçon dit quoi écrire à la place ;
- à partir de SES mots : n'invente pas ce qu'elle n'a pas dit.
{verdict_note}
Leçons déjà retenues :
{kept}
Si la remarque dit la même chose qu'une leçon déjà retenue, mets son numéro dans "same_as" (sinon null).

Réponds en JSON : {{"lesson": "...", "same_as": null}}"""

LESSON_SCHEMA = {"type": "object", "properties": {"lesson": {"type": "string"},
                                                  "same_as": {"type": ["integer", "null"]}},
                 "required": ["lesson"]}

MERGE_PROMPT = """Tu tiens les règles qu'un directeur artistique suit quand il écrit le texte de chaque image dessinée
d'une chaîne YouTube : les leçons de sa propriétaire, écrites après avoir vu des images.

Règles actuelles :
{current}

Nouvelle leçon :
« {new} »

Réécris l'ENSEMBLE des règles en y intégrant la nouvelle, pour qu'elles restent cohérentes :
- garde le sens de chaque règle, en mots simples, une ou deux phrases chacune, en français ;
- fusionne ce qui se répète ; si la nouvelle contredit une ancienne, la nouvelle l'emporte et l'ancienne est
  réécrite ou retirée ;
- des principes, jamais une liste d'objets ni de scènes ; {max} règles au plus.
summary : une phrase pour elle, ce qui change dans les règles.

Réponds en JSON : {{"lessons": ["...", ...], "summary": "..."}}"""

MERGE_SCHEMA = {"type": "object", "properties": {"lessons": {"type": "array", "items": {"type": "string"}},
                                                 "summary": {"type": "string"}},
                "required": ["lessons", "summary"]}


def _path(output_dir):
    return os.path.join(output_dir, LESSONS_FILE)


def lessons(output_dir):
    try:
        with open(_path(output_dir), encoding="utf-8") as f:
            data = json.load(f)
        return [x for x in data.get("lessons", []) if isinstance(x, dict) and x.get("id")]
    except (OSError, ValueError, AttributeError):
        return []


def _save(output_dir, items):
    path = _path(output_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"lessons": items}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def kept(output_dir):
    return [x for x in lessons(output_dir) if x.get("status") == "kept"]


def _find(output_dir, lid):
    lesson = next((x for x in lessons(output_dir) if x["id"] == lid), None)
    if not lesson:
        raise ValueError("unknown lesson")
    return lesson


def _clean(text):
    return " ".join(str(text or "").split())[:MAX_TEXT]


def _last_entry(output_dir, pid):
    """Her last verdict line on ``pid`` (with the picture's context), or None."""
    last = None
    try:
        with open(os.path.join(output_dir, broll_gallery.FEEDBACK_FILE), encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("id") == pid:
                    last = e
    except OSError:
        return None
    return last if last and last.get("verdict") else None


def _ask(prompt, schema=LESSON_SCHEMA):
    import ai_brain
    return ai_brain.claude_json(prompt, schema, model="sonnet", effort="medium", timeout=240)


# --- 1. a verdict becomes a proposed lesson -------------------------------------------------------

def propose(output_dir, pid):
    """The lesson the AI draws from her last verdict on ``pid``: a new "proposed" lesson (it replaces a proposal from
    the same picture not yet applied), or the kept lesson that already says it ({"status": "same"}). ValueError when
    there is no verdict with words to learn from."""
    e = _last_entry(output_dir, pid)
    if not e:
        raise ValueError("Pas de verdict sur cette image.")
    if not (e.get("why") or "").strip() and not (e.get("change") or "").strip():
        raise ValueError("Écris pourquoi (ou ce que tu veux changer) : l'IA apprend de tes mots.")
    known = kept(output_dir)
    up = e["verdict"] == "up"
    prompt = LESSON_PROMPT.format(
        verdict="un pouce en haut (elle aime)" if up else "un pouce en bas (elle n'aime pas)",
        said=e.get("said") or "", idea=e.get("idea") or "", prompt=e.get("prompt") or "",
        why=e.get("why") or "", change=e.get("change") or "",
        verdict_note="Elle aime cette image : la leçon dit ce qu'il faut refaire.\n" if up else "",
        kept="\n".join(f"{i + 1}. {x['text']}" for i, x in enumerate(known)) or "(aucune)")
    data = _ask(prompt)
    same = data.get("same_as")
    if isinstance(same, int) and 1 <= same <= len(known):
        return {**known[same - 1], "status": "same"}
    text = _clean(data.get("lesson"))
    if not text:
        raise ValueError("L'IA n'a pas su en tirer une leçon.")
    lesson = {"id": uuid.uuid4().hex[:8], "text": text, "status": "proposed", "from": pid,
              "verdict": e["verdict"], "why": e.get("why") or "", "change": e.get("change") or "",
              "said": e.get("said") or "", "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    items = [x for x in lessons(output_dir) if not (x.get("from") == pid and x.get("status") == "proposed")]
    _save(output_dir, items + [lesson])
    return lesson


def update(output_dir, lid, status=None, text=None):
    """Rewrites a lesson, drops it (« Refuser » / « Retirer »), or puts it back to proposed; returns it. A proposed
    lesson is kept only through its check (apply). ValueError for an unknown lesson or status."""
    if status is not None and status not in STATUSES:
        raise ValueError("status must be proposed, kept or refused")
    items = lessons(output_dir)
    for x in items:
        if x["id"] == lid:
            if status == "kept" and x.get("status") != "kept":
                raise ValueError("Une leçon s'applique après sa vérification (planche avant / après).")
            if status is not None:
                x["status"] = status
            if text is not None:
                text = _clean(text)
                if not text:
                    raise ValueError("Une leçon vide ne s'apprend pas.")
                x["text"] = text
            x["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save(output_dir, items)
            return x
    raise ValueError("unknown lesson")


def block_of(texts):
    """A set of lessons as the art director reads it ("" when empty)."""
    texts = [t for t in texts if t][-MAX_IN_PROMPT:]
    if not texts:
        return ""
    return ("THE OWNER'S LESSONS (she wrote them after seeing earlier pictures; obey them like your principles):\n"
            + "\n".join(f"- {t}" for t in texts) + "\n\n")


def director_block(output_dir):
    """The kept lessons as the art director reads them ("" when there is none)."""
    return block_of([x["text"] for x in kept(output_dir)])


# --- 2. the check: one coherent set, drawn before / after -----------------------------------------

def merged_set(output_dir, text):
    """(the whole set of kept lessons rewritten with ``text``, one sentence on what changes)."""
    current = [x["text"] for x in kept(output_dir)]
    if not current:
        return [text], "Première règle : elle s'ajoute telle quelle."
    data = _ask(MERGE_PROMPT.format(current="\n".join(f"{i + 1}. {t}" for i, t in enumerate(current)), new=text,
                                    max=MAX_IN_PROMPT), MERGE_SCHEMA)
    merged = [t for t in (_clean(x) for x in data.get("lessons") or []) if t][:MAX_IN_PROMPT]
    return (merged or current + [text]), _clean(data.get("summary")) or "Règles réécrites avec la nouvelle leçon."


def _picture(output_dir, pid):
    return next((p for p in broll_gallery._from_traces(output_dir) + broll_gallery._from_bench(output_dir)
                 if p["id"] == pid), None)


def _seed(text):
    return int(hashlib.sha1(text.encode("utf-8")).hexdigest()[:12], 16)


def references(output_dir, exclude=None):
    """The fixed moments every check draws besides the critiqued one: chosen once among the jobs' kept pictures (other
    clips, a full screen first), so that the checks compare alike."""
    path = os.path.join(output_dir, REFS_FILE)
    try:
        with open(path, encoding="utf-8") as f:
            refs = [r for r in json.load(f) if isinstance(r, dict) and r.get("said")]
    except (OSError, ValueError, TypeError):
        refs = []
    if not refs:
        pics = [p for p in broll_gallery._from_traces(output_dir) if p["kept"] and p["said"] and p["seed"] is not None]
        pics.sort(key=lambda p: p["layout"] != "hero")
        clips = set()
        for p in pics:
            if p["clip"] in clips:
                continue
            clips.add(p["clip"])
            refs.append({k: p[k] for k in ("id", "said", "clip", "layout", "seed")})
            if len(refs) > N_REFS:
                break
        if refs:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(refs, f, ensure_ascii=False, indent=1)
    return [r for r in refs if r["id"] != exclude][:N_REFS]


def _check_dir(output_dir, lid):
    return os.path.join(output_dir, CHECKS_DIR, lid)


def _write_state(output_dir, lid, st):
    folder = _check_dir(output_dir, lid)
    os.makedirs(folder, exist_ok=True)
    tmp = os.path.join(folder, "check.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(folder, "check.json"))


def check_state(output_dir, lid):
    """The lesson's check as the gallery shows it, or None. "stale": the kept set or the lesson's text changed since."""
    try:
        with open(os.path.join(_check_dir(output_dir, lid), "check.json"), encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        return None
    if st.get("state") == "running" and time.time() - st.get("started", 0) > STALE_SECONDS:
        st = {**st, "state": "error", "error": "Vérification interrompue (serveur redémarré ?). Relance-la."}
    if st.get("state") == "done":
        lesson = next((x for x in lessons(output_dir) if x["id"] == lid), {})
        st["stale"] = (st.get("text") != lesson.get("text")
                       or sorted(st.get("base") or []) != sorted(x["id"] for x in kept(output_dir)))
    return st


def board_path(output_dir, lid):
    path = os.path.join(_check_dir(output_dir, lid), "planche.jpg")
    return path if os.path.isfile(path) else None


def start_check(output_dir, lid, direct=None, render=None, background=True):
    """Starts the check of proposed lesson ``lid`` (a thread: about 2 Claude calls and 8 pictures); returns its state."""
    lesson = _find(output_dir, lid)
    if lesson.get("status") != "proposed":
        raise ValueError("Seule une leçon proposée se vérifie.")
    st = check_state(output_dir, lid)
    if st and st.get("state") == "running":
        return st
    st = {"state": "running", "step": "Démarrage…", "started": time.time(), "text": lesson["text"]}
    _write_state(output_dir, lid, st)
    if background:
        threading.Thread(target=_run_check, args=(output_dir, lid, direct, render), daemon=True).start()
    else:
        _run_check(output_dir, lid, direct, render)
    return check_state(output_dir, lid)


def _render(text, out, layout, seed):
    import broll
    broll.local_image(text, "photo", out, engine="zimage", size=broll._gen_size(layout), seed=seed, raw=True)


def _run_check(output_dir, lid, direct=None, render=None):
    import broll_draw
    direct = direct or broll_draw.direct_and_verify
    render = render or _render
    folder = _check_dir(output_dir, lid)
    st = check_state(output_dir, lid) or {"started": time.time()}

    def step(text):
        st.update(state="running", step=text)
        _write_state(output_dir, lid, st)

    try:
        lesson = _find(output_dir, lid)
        pic = _picture(output_dir, lesson.get("from")) or {}
        moments = []
        if pic.get("said"):
            moments.append({"said": pic["said"], "clip": pic.get("clip") or "", "layout": pic.get("layout") or "card",
                            "seed": pic["seed"] if pic.get("seed") is not None else _seed(pic["said"]), "own": True})
        moments += [{**r, "own": False} for r in references(output_dir, lesson.get("from"))]
        if not moments:
            raise ValueError("Aucune image à redessiner pour vérifier.")
        base = kept(output_dir)
        step("L'IA fusionne la leçon avec les règles déjà gardées…")
        merged, summary = merged_set(output_dir, lesson["text"])
        sentences = [(m["clip"], "", m["said"]) for m in moments]
        step("Le directeur dessine avec les règles actuelles…")
        ideas_b, verd_b, suffix = direct(sentences, taught=block_of([x["text"] for x in base]))
        step("Le directeur dessine avec la leçon…")
        ideas_a, verd_a, suffix = direct(sentences, taught=block_of(merged))
        rows, n, total = [], 0, 2 * len(moments)
        for k, m in enumerate(moments):
            row = {"said": m["said"], "own": m["own"], "layout": m["layout"]}
            for side, ideas, verd in (("before", ideas_b, verd_b), ("after", ideas_a, verd_a)):
                n += 1
                step(f"Dessin des images ({n}/{total})…")
                text = (ideas[k] or {}).get("picture") or ""
                ok = bool(text) and (verd[k] or {}).get("verdict") == "pass"
                name = f"{side}_{k}.jpg"
                if ok:
                    render(broll_draw.picture_text(suffix, text), os.path.join(folder, name), m["layout"], m["seed"])
                row[side] = {"picture": text, "verdict": (verd[k] or {}).get("verdict", "refuse"),
                             "reason": (verd[k] or {}).get("reason", ""), "file": name if ok else None}
            rows.append(row)
        step("Planche…")
        _board(folder, rows)
        st.update(state="done", step="", merged=merged, summary=summary, base=[x["id"] for x in base],
                  text=lesson["text"], rows=rows, finished=time.time())
    except Exception as e:
        st.update(state="error", error=str(e)[:300])
    _write_state(output_dir, lid, st)


def _board(folder, rows):
    """Before on top, after below, one column per moment (the critiqued one first)."""
    from PIL import Image, ImageDraw, ImageFont

    def font(n):
        for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "C:/Windows/Fonts/arialbd.ttf"):
            if os.path.exists(f):
                return ImageFont.truetype(f, n)
        return ImageFont.load_default()

    H, PAD, LABEL, HEAD = 520, 18, 110, 70
    cells = []
    for r in rows:
        col = []
        for side in ("before", "after"):
            f = r[side]["file"]
            if f and os.path.isfile(os.path.join(folder, f)):
                im = Image.open(os.path.join(folder, f)).convert("RGB")
                im = im.resize((round(im.width * H / im.height), H))
            else:
                im = Image.new("RGB", (round(H * 9 / 16), H), (48, 50, 56))
                ImageDraw.Draw(im).text((16, H // 2 - 12), "refusée par la sécurité", fill=(200, 200, 200), font=font(18))
            col.append(im)
        cells.append(col)
    widths = [max(a.width, b.width) for a, b in cells]
    W = LABEL + sum(widths) + PAD * (len(cells) + 1)
    board = Image.new("RGB", (W, HEAD + 2 * H + 3 * PAD), (22, 23, 27))
    d = ImageDraw.Draw(board)
    d.text((PAD, HEAD + PAD + H // 2 - 14), "AVANT", fill=(235, 235, 235), font=font(26))
    d.text((PAD, HEAD + 2 * PAD + H + H // 2 - 14), "APRÈS", fill=(235, 235, 235), font=font(26))
    x = LABEL + PAD
    for r, (a, b), w in zip(rows, cells, widths):
        said = r["said"] if len(r["said"]) <= 70 else r["said"][:67] + "…"
        d.text((x, PAD), ("TON IMAGE · " if r["own"] else "") + said[:35], fill=(235, 235, 235), font=font(17))
        d.text((x, PAD + 24), said[35:70], fill=(170, 175, 185), font=font(17))
        board.paste(a, (x, HEAD + PAD))
        board.paste(b, (x, HEAD + 2 * PAD + H))
        x += w + PAD
    board.save(os.path.join(folder, "planche.jpg"), quality=86)


# --- 3. apply: the kept set becomes exactly the checked one ---------------------------------------

def apply(output_dir, lid):
    """The checked set replaces the kept lessons; ``lid`` is marked applied. ValueError without a fresh check."""
    st = check_state(output_dir, lid)
    if not st or st.get("state") != "done":
        raise ValueError("Vérifie d'abord la leçon (planche avant / après).")
    if st.get("stale"):
        raise ValueError("Les règles ou la leçon ont changé depuis la vérification : vérifie à nouveau.")
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    items = lessons(output_dir)
    for x in items:
        if x.get("status") == "kept":
            x.update(status="replaced", replaced_by=lid, updated=now)
        if x["id"] == lid:
            x.update(status="applied", applied=now)
    items += [{"id": uuid.uuid4().hex[:8], "text": t, "status": "kept", "from_check": lid, "at": now}
              for t in st["merged"]]
    _save(output_dir, items)
    return next(x for x in items if x["id"] == lid)
