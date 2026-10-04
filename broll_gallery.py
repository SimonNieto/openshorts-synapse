"""The B-roll gallery (4-oct-2026, the user: « un onglet où on regroupe toutes les anciennes images, un pouce en haut,
un pouce en bas, pourquoi et ce que j'ai envie de changer »): every drawn picture, kept or refused, from two places —

  - the jobs' traces: output/_broll_trace/<date>_<job8>/<clip>/trace.json (broll_v20.trace, v26 « dessin »);
  - the drawn bench: output/_test_broll/short/style_da2/<clip>/prompts.json (broll_dessin.py);

— with the owner's verdict on each (👍 / 👎, why, what to change), kept in output/_lessons/gallery_feedback.jsonl (one
line per click; the last one of a picture is its verdict). The verdicts feed the work on the principles; no call reads
them by itself. A picture's id is its path under the output folder, so the image route serves nothing else."""
import base64
import json
import os
import time

TRACE_DIR = "_broll_trace"
BENCH_DIR = os.path.join("_test_broll", "short", "style_da2")
FEEDBACK_FILE = os.path.join("_lessons", "gallery_feedback.jsonl")
VERDICTS = ("up", "down", "")


def _id(rel):
    return base64.urlsafe_b64encode(rel.replace(os.sep, "/").encode("utf-8")).decode("ascii").rstrip("=")


def path_of(output_dir, pid):
    """The image file of the picture ``pid`` — only a .jpg under the traces or the drawn bench — or None."""
    try:
        rel = base64.urlsafe_b64decode(pid + "=" * (-len(pid) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return None
    root = os.path.realpath(output_dir)
    path = os.path.realpath(os.path.join(root, rel))
    allowed = [os.path.realpath(os.path.join(root, d)) for d in (TRACE_DIR, BENCH_DIR)]
    if not path.lower().endswith(".jpg") or not any(path.startswith(a + os.sep) for a in allowed):
        return None
    return path if os.path.isfile(path) else None


def _load(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _from_traces(output_dir):
    root = os.path.join(output_dir, TRACE_DIR)
    out = []
    for run in sorted(os.listdir(root), reverse=True) if os.path.isdir(root) else []:
        for clip in sorted(os.listdir(os.path.join(root, run))) if os.path.isdir(os.path.join(root, run)) else []:
            data = _load(os.path.join(root, run, clip, "trace.json"))
            if not isinstance(data, dict):
                continue
            for p in data.get("pictures") or []:
                if not (isinstance(p, dict) and p.get("file")):
                    continue
                rel = os.path.join(TRACE_DIR, run, clip, p["file"])
                if not os.path.isfile(os.path.join(output_dir, rel)):
                    continue
                kept = bool(p.get("kept"))
                out.append({"id": _id(rel), "source": "job", "group": f"{run} · {data.get('clip') or clip}",
                            "date": run[:10], "clip": data.get("clip") or "", "said": p.get("said") or "",
                            "idea": p.get("idea") or "", "prompt": p.get("prompt") or "", "seed": p.get("seed"),
                            "layout": p.get("layout") or "", "kept": kept,
                            "status": "kept" if kept else ("refused" if p.get("verdict") == "refused" else "dropped"),
                            "why": p.get("why") or ""})
    return out


def _from_bench(output_dir):
    root = os.path.join(output_dir, BENCH_DIR)
    out = []
    folders = [""] + (sorted(d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))) if os.path.isdir(root) else [])
    for folder in folders:
        data = _load(os.path.join(root, folder, "prompts.json"))
        if not isinstance(data, list):
            continue
        for e in data:
            if not isinstance(e, dict):
                continue
            for key, kept in (("file", True), ("refused_file", False)):
                if not e.get(key):
                    continue
                rel = os.path.join(BENCH_DIR, folder, e[key])
                if not os.path.isfile(os.path.join(output_dir, rel)):
                    continue
                out.append({"id": _id(rel), "source": "bench", "group": f"banc · {e.get('clip') or folder or 'banc court'}",
                            "date": time.strftime("%Y-%m-%d", time.localtime(os.path.getmtime(os.path.join(output_dir, rel)))),
                            "clip": e.get("clip") or "", "said": e.get("sentence") or "", "idea": e.get("idea") or "",
                            "prompt": e.get("prompt") or "", "seed": e.get("seed"), "layout": e.get("layout") or "card",
                            "kept": kept, "status": "kept" if kept else "refused",
                            "why": "" if kept else (e.get("verifier_reason") or "")})
    return out


def feedback(output_dir):
    """{picture id: its last verdict {"verdict", "why", "change", "at"}} (a cleared verdict is dropped)."""
    out = {}
    try:
        with open(os.path.join(output_dir, FEEDBACK_FILE), encoding="utf-8") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("id"):
                    if e.get("verdict"):
                        out[e["id"]] = {k: e.get(k) or "" for k in ("verdict", "why", "change", "at")}
                    else:
                        out.pop(e["id"], None)
    except OSError:
        pass
    return out


def pictures(output_dir):
    """Every picture of the gallery, the jobs' first (newest first) then the bench's, each once (the same prompt and
    seed seen again in another folder is the same picture), each with the owner's verdict."""
    fb = feedback(output_dir)
    seen, out = set(), []
    for p in _from_traces(output_dir) + _from_bench(output_dir):
        key = (p["prompt"], p["seed"]) if p["prompt"] and p["seed"] is not None else p["id"]
        if key in seen:
            continue
        seen.add(key)
        out.append({**p, "feedback": fb.get(p["id"])})
    return out


def record(output_dir, pid, verdict, why="", change=""):
    """Appends the owner's verdict on ``pid`` ("up", "down", or "" to clear it) with why and what to change; returns the
    verdict as the gallery shows it. ValueError for an unknown picture or verdict."""
    if verdict not in VERDICTS:
        raise ValueError("verdict must be up, down or empty")
    if not path_of(output_dir, pid):
        raise ValueError("unknown picture")
    pic = next((p for p in _from_traces(output_dir) + _from_bench(output_dir) if p["id"] == pid), {})
    entry = {"id": pid, "verdict": verdict, "why": str(why or "")[:1000], "change": str(change or "")[:1000],
             "at": time.strftime("%Y-%m-%d %H:%M:%S"), "source": pic.get("source"), "clip": pic.get("clip"),
             "said": pic.get("said"), "idea": pic.get("idea"), "prompt": pic.get("prompt"), "seed": pic.get("seed"),
             "status": pic.get("status")}
    path = os.path.join(output_dir, FEEDBACK_FILE)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return {k: entry[k] for k in ("verdict", "why", "change", "at")} if verdict else None
