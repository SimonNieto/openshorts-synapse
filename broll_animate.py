"""B-roll « animé » (9-oct-2026): a generated 9:16 picture becomes a short silent video shot (2-3 s) with one light,
realistic motion — steam rising, a person blinking, the camera pushing in slowly, a hologram's light pulsing. The
reference channels (RECETTE_REFERENCES.md, OptimalHealth first) cut to such 1-3 s moving shots of the thing said.

Two engines (plus.BROLL["animate_engine"]), native ComfyUI nodes only, no custom node, run through ComfyUI's HTTP API
like the Z-Image pictures (broll.local_image); each graph lives in comfy_workflows/, this module only fills it in:
- "ltxv": LTX-Video 2B 0.9.8 distilled (Lightricks) + T5-XXL fp8, 11.5 GB of files, 8 steps; 29-47 s of GPU per 2.4 s
  shot on the RTX 3060 (bench of 9-oct-2026, 704x1248, 57 frames).
- "wan22": Wan 2.2 TI2V 5B (Comfy-Org repack) + UMT5-XXL fp8 + Wan 2.2 VAE, 18.1 GB of files, the official
  template's 20 steps at cfg 5; 406-446 s of GPU per 2.5 s shot on the RTX 3060 (bench of 9-oct-2026, 704x1280,
  61 frames): ~12x LTX, steadier (shapes held, no flicker), but less motion on faces.
Off by default: plus.BROLL["animate"].

Flow: the picture is cropped to 9:16 and sized for the model, uploaded to ComfyUI's input folder (subfolder
``synapse_animate``), animated, the frames come back from ComfyUI's temp folder (PreviewImage: never its gallery)
and ffmpeg writes an H.264 mp4 without sound at the output size."""
import io
import json
import os
import random
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from PIL import Image

WORKFLOWS = Path(__file__).resolve().parent / "comfy_workflows"
FPS = 24
# Per engine: its graph, the files ComfyUI must list (loader, input, file), the model's 9:16 frame size (LTX: multiples
# of 32, 9:16 within 0.3 %, close to the 720p the 2B model is made for; Wan 2.2 5B: its 1280x704 turned upright),
# the frame count rule (frames = step*n + 1: the VAE packs ``step`` frames into one latent frame), where the size,
# the seed and the frame rate go, and its negative prompt (Wan: the official template's). The mp4 is then scaled to
# OUT_SIZE.
WAN_NEGATIVE = ("色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，"
                "丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，"
                "静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走")
ENGINES = {
    "ltxv": {"workflow": "animate_ltxv_2b_distilled",
             "files": [("CheckpointLoaderSimple", "ckpt_name", "ltxv-2b-0.9.8-distilled.safetensors"),
                       ("CLIPLoader", "clip_name", "t5xxl_fp8_e4m3fn_scaled.safetensors")],
             "size": (704, 1248), "step": 8, "size_node": "i2v", "seed": ("sample", "noise_seed"),
             "fps": ("cond", "frame_rate"), "negative": None},
    "wan22": {"workflow": "animate_wan22_ti2v_5b",
              "files": [("UNETLoader", "unet_name", "wan2.2_ti2v_5B_fp16.safetensors"),
                        ("CLIPLoader", "clip_name", "umt5_xxl_fp8_e4m3fn_scaled.safetensors"),
                        ("VAELoader", "vae_name", "wan2.2_vae.safetensors")],
              "size": (704, 1280), "step": 4, "size_node": "latent", "seed": ("sample", "seed"),
              "fps": None, "negative": WAN_NEGATIVE},
}
DEFAULT_ENGINE = "ltxv"
WORKFLOW = ENGINES["ltxv"]["workflow"]
MODEL = ENGINES["ltxv"]["files"][0][2]
SIZE = ENGINES["ltxv"]["size"]
OUT_SIZE = (1080, 1920)
SECONDS = 2.5
UPLOAD_SUBFOLDER = "synapse_animate"
# The prompt: what moves first (LTX-Video reads the motion best when it leads), then a short description of what is
# in the picture when the caller has it, then what keeps the shot quiet. The negative names the usual faults of
# image-to-video models: shapes that melt or morph, faces that drift, flicker, text.
STEADY = ("The motion is slow, subtle and natural, the shape of every object and face stays exactly the same, "
          "realistic lighting, sharp detail, no cut.")
NEGATIVE = ("worst quality, low quality, blurry, jittery, flickering, inconsistent motion, morphing, warping, melting, "
            "deformed face, distorted face, extra limbs, deformed hands, sudden camera movement, fast motion, "
            "scene change, text, letters, watermark, logo")


def _cfg(cfg=None):
    """The job's B-roll recipe: ``cfg``, else the one the job carries (PLUS_BROLL_JSON), else plus.BROLL."""
    if isinstance(cfg, dict):
        return cfg
    try:
        got = json.loads(os.environ.get("PLUS_BROLL_JSON") or "null")
        if isinstance(got, dict):
            return got
    except ValueError:
        pass
    try:
        import plus
        return plus.BROLL
    except Exception:
        return {}


def enabled(cfg=None):
    """plus.BROLL["animate"] as the job carries it (9-oct-2026: off in production until the user has seen a bench; on
    on the references-v3 branch)."""
    return bool(_cfg(cfg).get("animate", False))


def engine(cfg=None):
    """The animation engine asked by the recipe (plus.BROLL["animate_engine"]), "ltxv" by default."""
    return str(_cfg(cfg).get("animate_engine") or "ltxv")


def engine_name(engine=None):
    """The engine asked, else plus.BROLL["animate_engine"], else LTX-Video."""
    if not engine:
        try:
            import plus
            engine = plus.BROLL.get("animate_engine")
        except Exception:
            engine = None
    engine = engine or DEFAULT_ENGINE
    if engine not in ENGINES:
        raise ValueError(f"unknown animation engine {engine!r} (one of {sorted(ENGINES)})")
    return engine


def _comfy_url():
    return (os.environ.get("COMFYUI_URL") or "http://host.docker.internal:8188").rstrip("/")


def frames_for(seconds, fps=FPS, step=8):
    """The frame count: step*n+1 (LTX-Video's VAE packs 8 frames into one latent frame, Wan 2.2's 4), n >= 1."""
    n = max(1, round((float(seconds) * fps - 1) / step))
    return step * n + 1


# Bench of 9-oct-2026 (output/_stepup/etude2/v3/animation): without it, LTX-Video turned the 3D renders (a holographic
# head by ~30 degrees, a heart that rotated instead of beating); "static camera ... does not rotate" first kept the
# head still with only its light pulsing. Not added when the motion itself moves the camera ("the camera pushes in").
STATIC = "Static camera, the subject stays in place and does not rotate."


def prompt_text(motion, scene=""):
    motion = str(motion or "").strip().rstrip(".")
    lead = "" if "camera" in motion.lower() else STATIC
    parts = [lead, motion + "." if motion else "", str(scene or "").strip(), STEADY]
    return " ".join(p for p in parts if p)


def load_workflow(name=WORKFLOW):
    graph = json.loads((WORKFLOWS / f"{name}.json").read_text(encoding="utf-8"))
    return {k: v for k, v in graph.items() if not k.startswith("_")}


def build_graph(image_name, motion, seed, *, scene="", width=None, height=None, length=None, fps=FPS,
                negative=None, engine=None):
    """The ComfyUI API graph of one shot (``image_name``: the uploaded picture as LoadImage names it)."""
    eng = ENGINES[engine_name(engine)]
    g = load_workflow(eng["workflow"])
    g["load"]["inputs"]["image"] = image_name
    g["pos"]["inputs"]["text"] = prompt_text(motion, scene)
    g["neg"]["inputs"]["text"] = negative or eng["negative"] or NEGATIVE
    g[eng["size_node"]]["inputs"].update({"width": int(width or eng["size"][0]),
                                          "height": int(height or eng["size"][1]),
                                          "length": int(length or frames_for(SECONDS, fps, eng["step"]))})
    if eng["fps"]:
        g[eng["fps"][0]]["inputs"][eng["fps"][1]] = float(fps)
    g[eng["seed"][0]]["inputs"][eng["seed"][1]] = int(seed)
    return g


def fit(image_path, width, height):
    """The picture cropped to the frame's aspect (centred, never stretched) and resized: PNG bytes."""
    im = Image.open(image_path).convert("RGB")
    w, h = im.size
    target = width / height
    if w / h > target:                       # too wide: crop the sides
        nw = round(h * target)
        im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    elif w / h < target:                     # too tall: crop top and bottom
        nh = round(w / target)
        im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    im = im.resize((width, height), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def available(engine=None, timeout=5):
    """True when ComfyUI answers and lists every file of the engine."""
    import httpx
    try:
        files = ENGINES[engine_name(engine)]["files"]
        with httpx.Client(timeout=timeout) as http:
            for node, field, name in files:
                info = http.get(f"{_comfy_url()}/object_info/{node}").json()
                if name not in info[node]["input"]["required"][field][0]:
                    return False
        return True
    except Exception:
        return False


def _gpu_seconds(status):
    """Execution time ComfyUI reports (execution_start -> success), in s, else None."""
    stamps = {m[0]: (m[1] or {}).get("timestamp") for m in (status.get("messages") or []) if m and len(m) > 1}
    a, b = stamps.get("execution_start"), stamps.get("execution_success")
    return round((b - a) / 1000.0, 1) if a and b else None


def encode(frame_paths, out_path, fps=FPS, out_size=OUT_SIZE):
    """The frames as an H.264 mp4, no audio track, yuv420p (plays everywhere), scaled to ``out_size``."""
    d = Path(frame_paths[0]).parent
    pattern = str(d / "f_%04d.png")
    vf = f"scale={out_size[0]}:{out_size[1]}:flags=lanczos,setsar=1" if out_size else "setsar=1"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-framerate", str(fps), "-i", pattern, "-vf", vf,
                    "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-an",
                    "-movflags", "+faststart", str(out_path)], check=True)
    return out_path


def animate(image_path, motion, out_path, *, scene="", seconds=SECONDS, size=None, out_size=OUT_SIZE, seed=None,
            fps=FPS, timeout=1800, negative=None, engine=None):
    """One 9:16 picture -> one silent mp4 of ``seconds`` (2-3 s) with the light motion ``motion`` ("steam rises
    slowly from the cup", "she blinks once", "the camera pushes in slowly"). ``scene``: what the picture shows (its
    image prompt, optional). ``engine``: "ltxv" / "wan22", else plus.BROLL["animate_engine"]. Returns {"path",
    "seconds", "frames", "seed", "gpu_s", "wall_s", "engine"}; raises RuntimeError when ComfyUI refuses, fails or
    times out."""
    import httpx
    seed = random.randint(0, 2 ** 48) if seed is None else int(seed)
    engine = engine_name(engine)
    width, height = size or ENGINES[engine]["size"]
    length = frames_for(seconds, fps, ENGINES[engine]["step"])
    base = _comfy_url()
    t0 = time.time()
    tmp = Path(tempfile.mkdtemp(prefix="animate_"))
    try:
        with httpx.Client(timeout=60) as http:
            name = f"{uuid.uuid4().hex[:12]}.png"
            r = http.post(f"{base}/upload/image", files={"image": (name, fit(image_path, width, height), "image/png")},
                          data={"subfolder": UPLOAD_SUBFOLDER, "type": "input", "overwrite": "true"})
            if r.status_code != 200:
                raise RuntimeError(f"ComfyUI refused the picture ({r.status_code}): {r.text[:300]}")
            up = r.json()
            ref = f"{up.get('subfolder')}/{up['name']}" if up.get("subfolder") else up["name"]
            graph = build_graph(ref, motion, seed, scene=scene, width=width, height=height, length=length, fps=fps,
                                negative=negative, engine=engine)
            r = http.post(f"{base}/prompt", json={"prompt": graph, "client_id": uuid.uuid4().hex})
            if r.status_code != 200:
                raise RuntimeError(f"ComfyUI refused the job ({r.status_code}): {r.text[:300]}")
            pid = r.json()["prompt_id"]
            deadline = time.time() + timeout
            while time.time() < deadline:
                h = http.get(f"{base}/history/{pid}").json().get(pid)
                if h:
                    status = h.get("status") or {}
                    if status.get("status_str") == "error":
                        msgs = [m for m in status.get("messages") or [] if m and m[0] == "execution_error"]
                        raise RuntimeError("ComfyUI error: " + str(
                            msgs[-1][1].get("exception_message") if msgs else status)[:300])
                    imgs = (h.get("outputs") or {}).get("out", {}).get("images") or []
                    if imgs:
                        frames = []
                        for i, im in enumerate(imgs):
                            got = http.get(f"{base}/view", params={"filename": im["filename"],
                                                                  "subfolder": im.get("subfolder", ""),
                                                                  "type": im.get("type", "temp")})
                            got.raise_for_status()
                            p = tmp / f"f_{i:04d}.png"
                            p.write_bytes(got.content)
                            frames.append(p)
                        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
                        encode(frames, out_path, fps=fps, out_size=out_size)
                        return {"path": str(out_path), "seconds": round(len(frames) / fps, 2), "frames": len(frames),
                                "seed": seed, "gpu_s": _gpu_seconds(status), "wall_s": round(time.time() - t0, 1),
                                "engine": engine}
                    if status.get("completed"):
                        raise RuntimeError("ComfyUI finished without frames")
                time.sleep(0.5)
        raise RuntimeError(f"ComfyUI timed out after {timeout}s")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def contact_sheet(video_path, out_path, n=4, width=270):
    """``n`` frames of the video side by side (first, ..., last), for a bench board."""
    tmp = Path(tempfile.mkdtemp(prefix="animsheet_"))
    try:
        dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                                    "default=nw=1:nk=1", str(video_path)], capture_output=True, text=True,
                                   check=True).stdout.strip())
        shots = []
        for i in range(n):
            t = min(dur - 0.05, dur * i / max(1, n - 1))
            p = tmp / f"s{i}.png"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(video_path), "-frames:v", "1",
                            str(p)], check=True)
            shots.append(Image.open(p).convert("RGB"))
        h = round(width * shots[0].height / shots[0].width)
        sheet = Image.new("RGB", (width * n + 6 * (n - 1), h), (20, 20, 20))
        for i, s in enumerate(shots):
            sheet.paste(s.resize((width, h), Image.LANCZOS), (i * (width + 6), 0))
        sheet.save(out_path, quality=90)
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
