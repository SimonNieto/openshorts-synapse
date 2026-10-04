"""What the art director learns from the owner (4-oct-2026, the user: « quand je vois une erreur sur la photo, je
l'explique, et pour les prochaines photos l'IA apprend de ce que je lui ai expliqué »).

A 👍 / 👎 of the B-roll gallery, with why and what to change, becomes ONE lesson for the next pictures: the AI writes
it from her words and the picture's context (the sentence, the idea, the text sent to the image model) — a principle,
never a fix of that picture nor a list of things. Her rule (lessons are proposed, never applied alone): a new lesson is
"proposed" until she keeps it with one click in the gallery; she can rewrite it or drop it. The kept ones go into the
art director's call of the « dessin » chain (broll_draw), when plus.BROLL["lessons"] is on.

Kept in output/_lessons/director_lessons.json."""
import json
import os
import time
import uuid

import broll_gallery

LESSONS_FILE = os.path.join("_lessons", "director_lessons.json")
STATUSES = ("proposed", "kept", "refused")
MAX_IN_PROMPT = 30
MAX_TEXT = 500

LESSON_PROMPT = """Tu aides le directeur artistique d'une chaîne YouTube à apprendre des remarques de sa propriétaire.
Le directeur lit une phrase d'un clip et écrit le texte d'UNE image dessinée (un modèle d'image la dessine ensuite,
le code ajoute la phrase de style de la charte à la fin du texte).

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


def _ask(prompt):
    import ai_brain
    return ai_brain.claude_json(prompt, LESSON_SCHEMA, model="sonnet", effort="medium", timeout=240)


def propose(output_dir, pid):
    """The lesson the AI draws from her last verdict on ``pid``: a new "proposed" lesson (it replaces a proposal from
    the same picture not yet kept), or the kept lesson that already says it ({"status": "same"}). ValueError when
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
    text = " ".join(str(data.get("lesson") or "").split())[:MAX_TEXT]
    if not text:
        raise ValueError("L'IA n'a pas su en tirer une leçon.")
    lesson = {"id": uuid.uuid4().hex[:8], "text": text, "status": "proposed", "from": pid,
              "verdict": e["verdict"], "why": e.get("why") or "", "change": e.get("change") or "",
              "said": e.get("said") or "", "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    items = [x for x in lessons(output_dir) if not (x.get("from") == pid and x.get("status") == "proposed")]
    _save(output_dir, items + [lesson])
    return lesson


def update(output_dir, lid, status=None, text=None):
    """Keeps / drops / rewrites lesson ``lid``; returns it. ValueError for an unknown lesson or status."""
    if status is not None and status not in STATUSES:
        raise ValueError("status must be proposed, kept or refused")
    items = lessons(output_dir)
    for x in items:
        if x["id"] == lid:
            if status is not None:
                x["status"] = status
            if text is not None:
                text = " ".join(str(text).split())[:MAX_TEXT]
                if not text:
                    raise ValueError("Une leçon vide ne s'apprend pas.")
                x["text"] = text
            x["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
            _save(output_dir, items)
            return x
    raise ValueError("unknown lesson")


def director_block(output_dir):
    """The kept lessons as the art director reads them ("" when there is none)."""
    texts = [x["text"] for x in kept(output_dir)][-MAX_IN_PROMPT:]
    if not texts:
        return ""
    return ("THE OWNER'S LESSONS (she wrote them after seeing earlier pictures; obey them like your principles):\n"
            + "\n".join(f"- {t}" for t in texts) + "\n\n")
