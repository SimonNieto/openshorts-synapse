"""The bench's store of rendered pictures (v24, 4-oct-2026): every picture made stays on disk with its prompt, its seed,
its size, its steps, its model and the version that asked for it; the same prompt at the same size with the same seed
is never rendered twice. The seed of a v24 picture comes from its prompt (seed_of): an unchanged prompt is the same
picture, read back with no GPU, and only a changed prompt is rendered. The production chain never uses it.

  store/<2 hex>/<key>.jpg   the picture
  store/<2 hex>/<key>.json  {"prompt", "seed", "size", "steps", "model", "version", "made", "seconds"}"""
import hashlib
import json
import os
import shutil
import time

STORE_DIR = os.environ.get("BROLL_STORE_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "output",
                                                               "_test_broll", "store")


def seed_of(text, layout=""):
    """The seed of a prompt: the same text (and layout) always gets the same one, below 2**48 like broll's."""
    return int(hashlib.sha1(f"{layout}|{text}".encode("utf-8")).hexdigest()[:12], 16)


def key(text, size, steps, model, seed):
    """The picture's address: everything ComfyUI's answer depends on."""
    w, h = (int(x) for x in size)
    raw = json.dumps([str(text), w, h, int(steps or 0), str(model or "turbo"), int(seed)], ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def path_of(k, ext=".jpg"):
    return os.path.join(STORE_DIR, k[:2], k + ext)


def get(k):
    """The stored picture of key ``k``, None when it was never made."""
    p = path_of(k)
    return p if os.path.exists(p) else None


def info(k):
    """What the store remembers of the picture ``k`` ({} when nothing)."""
    try:
        with open(path_of(k, ".json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def put(k, src, meta):
    """Keeps a copy of the picture ``src`` under ``k`` with its ``meta``; returns the stored path."""
    dst = path_of(k)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copyfile(src, dst)
    with open(path_of(k, ".json"), "w", encoding="utf-8") as f:
        json.dump({**meta, "made": meta.get("made") or time.strftime("%Y-%m-%d %H:%M:%S")}, f, ensure_ascii=False,
                  indent=1)
    return dst


def renderer(make, size_of, steps_of, model="turbo", version="", dry=False, log=None, gpu_cap=None):
    """A ``render(text, out_path, layout) -> (path or None, seed)`` as broll_v20 / broll_v24 call it, through the store:
    the seed from the prompt, a picture already made copied back (0 s of GPU), a new one made by
    ``make(text, out_path, size, seed, steps)`` and kept. ``dry``: nothing is made, a new prompt answers (None, seed).
    ``gpu_cap``: seconds of GPU this renderer may spend; once spent, a new prompt answers (None, seed) too. ``log``
    (a list) gets one line per call: {"file", "key", "layout", "seed", "cached", "made", "s", "capped"}."""
    spent = [0.0]

    def render(text, out, layout):
        size, steps = tuple(size_of(layout)), steps_of(layout)
        seed = seed_of(text, layout)
        k = key(text, size, steps, model, seed)
        line = {"file": os.path.basename(out), "key": k, "layout": layout, "seed": seed, "size": list(size),
                "cached": False, "made": False, "s": 0.0, "capped": False}
        hit = get(k)
        if hit:
            shutil.copyfile(hit, out)
            line["cached"] = True
            if log is not None:
                log.append(line)
            return out, seed
        if dry or (gpu_cap is not None and spent[0] >= gpu_cap):
            line["capped"] = not dry
            if log is not None:
                log.append(line)
            return None, seed
        t0 = time.time()
        got = make(text, out, size, seed, steps)
        line["s"] = round(time.time() - t0, 1)
        spent[0] += line["s"]
        if got:
            put(k, got, {"prompt": text, "seed": seed, "size": list(size), "steps": steps, "model": model,
                         "version": version, "seconds": line["s"]})
            line["made"] = True
        if log is not None:
            log.append(line)
        return got, seed

    render.spent = spent
    return render
