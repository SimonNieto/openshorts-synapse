"""Banc « dessin » (4-oct-2026) : la chaîne que l'utilisatrice a validée AU BANC — pas en production, qui reste v21 +
v22 tant qu'elle ne valide pas une version en la nommant.

Le monteur (broll_spec) place les moments d'un clip ; le directeur artistique (Opus, un appel par clip) écrit une seule
idée par moment, en dessin, avec la charte de style de l'épisode (.claude/skills/synapse-cut/charte.md, le suffixe
ajouté mot pour mot par le code) et ses principes du banc (directeur-banc.md) ; le vérificateur (Sonnet, un passage)
ne regarde que la sécurité et refuse ou laisse passer ; puis une passe de rendu Z-Image (broll_store : la graine vient
du prompt, une image déjà faite revient sans GPU). Ni spectateur, ni juge, ni refaite. Prompt et graine à côté de chaque
image, une planche par clip dans output/_test_broll/short/.

    python broll_dessin.py                          les dix moments du banc court, planche sur trois colonnes
    python broll_dessin.py --only 05_univers        quelques moments du banc court
    python broll_dessin.py --clip JOB:N [--moments 3,4]   un vrai clip (seulement ces moments rendus)"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import broll           # noqa: E402
import broll_ideas     # noqa: E402
import broll_store     # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
import broll_bench as bb  # noqa: E402

REPO = os.path.dirname(os.path.abspath(__file__))
HERE = os.path.join(REPO, "output", "_test_broll", "short", "style_da2")   # the drawn bench's pictures and sheets
SHORT = os.path.dirname(HERE)
SKILL = broll_ideas.SKILL_DIR


def read(name):
    with open(os.path.join(SKILL, name), encoding="utf-8") as f:
        return f.read().strip()


CHARTE, PRINCIPES_BANC = read("charte.md"), read("directeur-banc.md")
SUFFIX = next(line[1:].strip() for line in CHARTE.splitlines() if line.startswith("> Premium"))

DA_PROMPT = """You are the art director of the channel described below (its texts are in French; answer in ENGLISH).

THE CHANNEL'S PRINCIPLES (everything you propose obeys them, first of all "ce qui passe avant l'impact"):
{principes}

THE EPISODE'S STYLE CHARTER (every picture is drawn in it; the code adds the style words itself):
{charte}

YOUR PRINCIPLES (they decide how a sentence becomes a picture):
{banc}

For each sentence below you get the clip it belongs to, what was heard just before, and the sentence itself. For each
one, ONE picture, drawn in the charter: the IDEA of the sentence, never its word, the simplest symbol of it, big.
People are always drawn and anonymous; never a speaker, never a real person of the story.
For each sentence: "idea" (what it means, one line) and "picture": the drawing in plain words, 60 at most, what fills
the frame first, what it does, two or three particular details, the light. Say "a single" or "only one" for every thing
that appears once. No style word and no camera word (the code adds the charter's style), nothing to read in the
picture except a question mark when your principles ask for one, no negation in the words (say what is there).
{moments}
Return JSON: {{"moments": [{{"k": 0, "idea": "...", "picture": "..."}}]}}"""
DA_SCHEMA = {"type": "object", "properties": {"moments": {"type": "array", "items": {
    "type": "object", "properties": {"k": {"type": "integer"}, "idea": {"type": "string"},
                                     "picture": {"type": "string"}},
    "required": ["k", "idea", "picture"]}}}, "required": ["moments"]}

VERIFY_PROMPT = """You are the verifier of the channel described below (its texts are in French; answer in ENGLISH).
You check SAFETY only, in one pass, before any picture is made. You do not judge whether a picture is good, relevant or
well chosen, and you give no score: you refuse or you let it pass.

THE CHANNEL'S PRINCIPLES:
{principes}

Every picture is DRAWN in the episode's illustration style (the code adds the style words to the description): an
organ drawn whole and clean (a brain, a spine, a nerve), even with an instrument touching it, is fine, never a reason
to refuse.
Refuse a picture when:
- it is gore: a head or a body opened, a wound, blood, a cut into flesh, tissue taken out of a body;
- something in it evokes a death or its means, even as a visual cliché (a clip about a death, a sentence about deaths);
- in a clip about a death, or on a sentence that mentions a death, something in it hangs, dangles or is looped: a
  cord, a strap, a lanyard, a belt, a scarf, a cable, a tube, a rope, a lace (a badge's lanyard coiled on a desk, in a
  clip about a suicide, is one; so is anything "hanging", "swinging" or "dangling" from a line, whatever it is) —
  anywhere else, a washing line or a strap is an ordinary thing and passes;
- in a clip whose subject is a death, the dead person is shown, alive or not: such a clip shows an absence;
- it gives real victims a number or their belongings (chairs, bowls, toys, shoes, clothes of the victims);
- it shows a drug, its gear or its intake.
Otherwise let it pass. "verdict": "pass" or "refuse"; "reason": 12 words at most when you refuse.
{items}
Return JSON: {{"moments": [{{"k": 0, "verdict": "pass", "reason": ""}}]}}"""
VERIFY_SCHEMA = {"type": "object", "properties": {"moments": {"type": "array", "items": {
    "type": "object", "properties": {"k": {"type": "integer"}, "verdict": {"type": "string", "enum": ["pass", "refuse"]},
                                     "reason": {"type": "string"}},
    "required": ["k", "verdict", "reason"]}}}, "required": ["moments"]}

ORDER = [("01_frigo", 1), ("02_dmt", 2), ("03_voix", 3), ("04_dopamine", 4), ("05_univers", 7), ("06_ibogaine", 9),
         ("07_question", 10), ("08_absence", 5), ("09_grave", 6), ("10_banderole", 8)]
STEPS = int(os.environ.get("COMFYUI_ZIMAGE_STEPS") or 8)


def bench_moments():
    """The ten moments of the short bench: [(name, label, clip title, before, sentence)]."""
    fiches = json.load(open(os.path.join(SHORT, "fiches.json"), encoding="utf-8"))
    test_b = {e["file"][:-4].replace("_v2", ""): e for e in json.load(open(
        os.path.join(SHORT, "style_cartoon", "B_editorial", "prompts_v2.json"), encoding="utf-8"))}
    by_id = {f["id"]: f for f in fiches["moments"]}
    out = []
    for name, mid in ORDER:
        f = by_id[mid]
        ctx = fiches["clips"][f["clip_key"]]
        said, before, _a = broll_ideas._around(ctx["words"], float(f["moment"]["t"]))
        out.append((name, test_b[name]["moment"], ctx["title"], before, said))
    return out


def clip_moments(spec):
    """A real clip: the moments the editor places in it (broll_spec, the same capture as broll_bench24 freeze)."""
    import broll_bench24 as b24
    job, n = spec.split(":")
    prof = b24._env()
    job_dir, meta = b24._episode(job)
    clip, pre_fx = bb._clip_of(job_dir, meta, int(n))
    got = b24._capture_editor(job_dir, meta, int(n), clip, pre_fx, prof)
    title = clip.get("video_title_for_youtube_short") or ""
    out = []
    for j, m in enumerate(sorted(got["moments"], key=lambda m: float(m["t"]))):
        said, before, _a = broll_ideas._around(got["words"], float(m["t"]))
        out.append((f"{j + 1:02d}_{float(m['t']):.0f}s", f"{float(m['t']):.1f} s", title, before, said))
    return out, f"{os.path.basename(job_dir)[:8]}_clip{n}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", default="")
    ap.add_argument("--only", default="", help="bench moments by name (05_univers,...): a folder of their own")
    ap.add_argument("--moments", default="", help="clip mode: render only these moments (1-based, e.g. 3,4)")
    args = ap.parse_args()
    if args.clip:
        moments, tag = clip_moments(args.clip)
        folder = os.path.join(HERE, tag)
    elif args.only:
        keep = set(args.only.split(","))
        moments = [m for m in bench_moments() if m[0] in keep]
        tag, folder = "only", os.path.join(HERE, "only")
    else:
        moments, tag, folder = bench_moments(), "bench", HERE
    os.makedirs(folder, exist_ok=True)
    q = broll_ideas._q
    lines = [f'k={k} — clip "{q(title, 20)}"\n  heard just before: "{q(before)}"\n  SENTENCE: "{q(said)}"'
             for k, (_n, _l, title, before, said) in enumerate(moments)]
    principes = broll_ideas.skill_text("principes")
    data = broll_ideas._call(DA_PROMPT.format(principes=principes, charte=CHARTE, banc=PRINCIPES_BANC,
                                              moments="\n".join(lines)),
                             DA_SCHEMA, "broll_ideas", broll_ideas._model("broll_ideas", "opus"),
                             effort=os.environ.get("CLAUDE_EFFORT_BROLL_IDEAS") or "high")
    got = {m["k"]: m for m in data.get("moments") or [] if isinstance(m, dict) and isinstance(m.get("k"), int)}
    items = [f'k={k} — clip "{q(title, 20)}"; sentence: "{q(said)}"\n  picture: "{q((got.get(k) or {}).get("picture"), 70)}"'
             for k, (_n, _l, title, _b, said) in enumerate(moments) if (got.get(k) or {}).get("picture")]
    checked = broll_ideas._call(VERIFY_PROMPT.format(principes=principes, items="\n".join(items)), VERIFY_SCHEMA,
                                "broll_verify", broll_ideas._model("broll_verify", "sonnet"), effort="medium")
    verdicts = {m["k"]: m for m in checked.get("moments") or [] if isinstance(m, dict) and isinstance(m.get("k"), int)}

    def make(text, out, size, seed, steps):
        return broll.local_image(text, "photo", out, size=size, seed=seed, steps=steps, raw=True)

    render = broll_store.renderer(make, lambda layout: broll._gen_size(layout, "std"), lambda layout: STEPS,
                                  version="style_da2")
    index = []
    broll._comfy_enter()
    try:
        for k, (name, label, title, before, said) in enumerate(moments):
            m, v = got.get(k) or {}, verdicts.get(k) or {"verdict": "refuse", "reason": "not answered"}
            picture = re.sub(r"\s+", " ", str(m.get("picture") or "")).strip()
            simple = False
            prompt = f"{picture} {SUFFIX}"
            seed, made = None, False
            wanted = not args.moments or (k + 1) in {int(x) for x in args.moments.split(",") if x.strip()}
            if picture and v.get("verdict") == "pass" and wanted:
                _g, seed = render(prompt, os.path.join(folder, name + ".jpg"), "card")
                made = bool(_g)
            entry = {"file": name + ".jpg" if made else None, "moment": label, "clip": title, "heard_before": before,
                     "sentence": said, "idea": m.get("idea"), "picture": picture, "prompt": prompt, "seed": seed,
                     "verifier": v.get("verdict"), "verifier_reason": v.get("reason") or "", "layout": "card",
                     "style": "simplified" if simple else "charte",
                     "size": list(broll._gen_size("card", "std")), "steps": STEPS, "model": "z-image turbo"}
            index.append(entry)
            with open(os.path.join(folder, name + ".txt"), "w", encoding="utf-8") as f:
                f.write(f"{label}\nsentence: {said}\nidea (director): {entry['idea']}\nverifier: {entry['verifier']} "
                        f"{entry['verifier_reason']}\nseed: {seed}\nprompt: {prompt}\n")
            print(f"{name}: {v.get('verdict')} {v.get('reason') or ''} | seed {seed} — {entry['idea']}", flush=True)
    finally:
        broll._comfy_leave()
    with open(os.path.join(folder, "prompts.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    if tag == "bench":
        sheet_three(index)
    elif tag == "only":
        pass
    else:
        sheet_clip(index, folder, tag)
    print("DONE")


def _cell(sheet, d, path, x, y, TW, TH, refused, font):
    if path and os.path.exists(path):
        im = Image.open(path).convert("RGB")
        im.thumbnail((TW, TH))
        sheet.paste(im, (x, y))
    else:
        d.rectangle([x, y, x + TW, y + TH], outline=(140, 140, 140), width=2)
        for i, line in enumerate(bb._wrap(refused or "pas d'image", font, TW - 20)[:4]):
            d.text((x + 10, y + 10 + i * 22), line, fill=(240, 110, 110), font=font)


def sheet_three(index):
    """Moment by moment: the hand-written test, the director of before, the director of today."""
    test_dir = os.path.join(SHORT, "style_cartoon", "B_editorial")
    test_b = {e["file"][:-4].replace("_v2", ""): e["file"] for e in json.load(open(
        os.path.join(test_dir, "prompts_v2.json"), encoding="utf-8"))}
    before_dir = os.path.join(SHORT, "style_da")
    TW, TH = 520, 325
    W = 20 + 3 * (TW + 16) + 4
    ROW = TH + 170
    sheet = Image.new("RGB", (W, 70 + len(index) * ROW), (20, 20, 22))
    d = ImageDraw.Draw(sheet)
    fh, fb, fs = bb._font(26, True), bb._font(19), bb._font(16)
    for c, title in enumerate(("Test à la main", "Directeur d'avant", "Directeur d'aujourd'hui")):
        d.text((20 + c * (TW + 16), 20), title, fill=(255, 216, 77), font=fh)
    y = 70
    for j, e in enumerate(index):
        name = ORDER[j][0]
        cols = [os.path.join(test_dir, test_b[name]), os.path.join(before_dir, name + ".jpg"),
                os.path.join(HERE, e["file"]) if e["file"] else None]
        for c, path in enumerate(cols):
            _cell(sheet, d, path, 20 + c * (TW + 16), y, TW, TH,
                  f"refusée par le vérificateur : {e['verifier_reason']}" if c == 2 and not e["file"] else "", fs)
        yy = y + TH + 8
        d.text((20, yy), f"{j + 1}. {e['moment']}", fill=(255, 216, 77), font=fb)
        for line in bb._wrap(f"« {e['sentence']} »", fs, W - 40)[:2]:
            yy += 24
            d.text((20, yy), line, fill=(214, 214, 214), font=fs)
        for line in bb._wrap(f"idée du directeur d'aujourd'hui : {e['idea'] or '-'}", fs, W - 40)[:3]:
            yy += 22
            d.text((20, yy), line, fill=(160, 172, 184), font=fs)
        y += ROW
    sheet.save(os.path.join(SHORT, "planche_trois_colonnes.jpg"), quality=90)


def sheet_clip(index, folder, tag):
    TW, TH = 760, 475
    W = 20 + 2 * (TW + 20)
    ROW = TH + 150
    rows = (len(index) + 1) // 2
    sheet = Image.new("RGB", (W, 70 + rows * ROW), (20, 20, 22))
    d = ImageDraw.Draw(sheet)
    fh, fb, fs = bb._font(26, True), bb._font(19), bb._font(16)
    d.text((20, 20), f"{index[0]['clip'] if index else tag}", fill=(255, 216, 77), font=fh)
    for j, e in enumerate(index):
        x, y = 20 + (j % 2) * (TW + 20), 70 + (j // 2) * ROW
        _cell(sheet, d, os.path.join(folder, e["file"]) if e["file"] else None, x, y, TW, TH,
              f"refusée par le vérificateur : {e['verifier_reason']}" if e["verifier"] == "refuse" else "", fs)
        yy = y + TH + 8
        d.text((x, yy), f"{j + 1}. à {e['moment']}" + ("   — dessin simplifié (gore)" if e.get("style") == "simplified"
                                                        else ""), fill=(255, 216, 77), font=fb)
        for line in bb._wrap(f"« {e['sentence']} »", fs, TW)[:2]:
            yy += 24
            d.text((x, yy), line, fill=(214, 214, 214), font=fs)
        for line in bb._wrap(f"idée : {e['idea'] or '-'}", fs, TW)[:2]:
            yy += 22
            d.text((x, yy), line, fill=(160, 172, 184), font=fs)
    sheet.save(os.path.join(SHORT, f"planche_clip_{tag}.jpg"), quality=90)


if __name__ == "__main__":
    main()
