"""B-roll « animé » (9-oct-2026): a picture -> a short silent 9:16 mp4 through ComfyUI. ComfyUI is simulated (httpx
MockTransport): no GPU, no model. ffmpeg is the real one (the container has it)."""
import io
import json
import subprocess

import httpx
import pytest
from PIL import Image

import broll_animate
import plus


def test_off_by_default():
    assert plus.BROLL["animate"] is False
    assert broll_animate.enabled() is False


@pytest.mark.parametrize("seconds,frames", [(2.0, 49), (2.5, 57), (3.0, 73), (0.1, 9)])
def test_frame_count_is_8n_plus_1(seconds, frames):
    assert broll_animate.frames_for(seconds) == frames
    assert (frames - 1) % 8 == 0


def test_workflow_uses_native_nodes_only_and_is_filled():
    g = broll_animate.build_graph("synapse_animate/x.png", "steam rises slowly from the cup", 42,
                                  scene="a cup of coffee on a table", length=57)
    native = {"CheckpointLoaderSimple", "CLIPLoader", "CLIPTextEncode", "LoadImage", "LTXVPreprocess",
              "LTXVImgToVideo", "LTXVConditioning", "KSamplerSelect", "ManualSigmas", "SamplerCustom", "VAEDecode",
              "PreviewImage"}
    assert {n["class_type"] for n in g.values()} <= native
    assert not any(v is None for n in g.values() for v in n["inputs"].values())
    assert g["load"]["inputs"]["image"] == "synapse_animate/x.png"
    assert g["pos"]["inputs"]["text"].startswith(broll_animate.STATIC + " steam rises slowly from the cup. a cup of")
    assert "morphing" in g["neg"]["inputs"]["text"]
    assert g["i2v"]["inputs"]["width"] % 32 == 0 and g["i2v"]["inputs"]["height"] % 32 == 0
    assert g["i2v"]["inputs"]["height"] > g["i2v"]["inputs"]["width"]          # vertical
    assert g["sample"]["inputs"]["noise_seed"] == 42 and g["sample"]["inputs"]["cfg"] == 1.0
    assert g["ckpt"]["inputs"]["ckpt_name"] == broll_animate.MODEL
    assert not any(k.startswith("_") for k in g)


def test_engine_comes_from_plus_and_ltxv_by_default(monkeypatch):
    assert plus.BROLL["animate_engine"] == "ltxv"
    assert broll_animate.engine_name() == "ltxv"
    monkeypatch.setitem(plus.BROLL, "animate_engine", "wan22")
    assert broll_animate.engine_name() == "wan22"
    assert broll_animate.engine_name("ltxv") == "ltxv"
    with pytest.raises(ValueError):
        broll_animate.engine_name("sora")


def test_wan22_graph_follows_the_official_template_and_4n_plus_1():
    g = broll_animate.build_graph("synapse_animate/x.png", "she blinks once", 9, engine="wan22",
                                  length=broll_animate.frames_for(2.5, step=4))
    assert {n["class_type"] for n in g.values()} == {
        "UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode", "LoadImage", "Wan22ImageToVideoLatent",
        "ModelSamplingSD3", "KSampler", "VAEDecode", "PreviewImage"}
    assert not any(v is None for n in g.values() for v in n["inputs"].values())
    lat = g["latent"]["inputs"]
    assert (lat["width"], lat["height"], lat["length"]) == (704, 1280, 61) and (61 - 1) % 4 == 0
    assert lat["start_image"] == ["load", 0]
    s = g["sample"]["inputs"]
    assert (s["seed"], s["steps"], s["cfg"], s["sampler_name"]) == (9, 20, 5.0, "uni_pc")
    assert g["ms"]["inputs"]["shift"] == 8.0
    assert g["neg"]["inputs"]["text"] == broll_animate.WAN_NEGATIVE
    assert g["clip"]["inputs"]["type"] == "wan"


def test_available_checks_every_file_of_the_engine(monkeypatch):
    lists = {"UNETLoader": ("unet_name", ["wan2.2_ti2v_5B_fp16.safetensors"]),
             "CLIPLoader": ("clip_name", ["umt5_xxl_fp8_e4m3fn_scaled.safetensors"]),
             "VAELoader": ("vae_name", ["ae.safetensors"]),
             "CheckpointLoaderSimple": ("ckpt_name", [])}

    def handler(request):
        node = request.url.path.rsplit("/", 1)[-1]
        field, names = lists[node]
        return httpx.Response(200, json={node: {"input": {"required": {field: [names]}}}})
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: real(*a, **{**k, "transport": httpx.MockTransport(handler)}))
    assert broll_animate.available("wan22") is False                     # the Wan VAE is missing
    lists["VAELoader"] = ("vae_name", ["wan2.2_vae.safetensors"])
    assert broll_animate.available("wan22") is True
    assert broll_animate.available("ltxv") is False


def test_static_camera_unless_the_motion_moves_the_camera():
    assert broll_animate.prompt_text("she blinks once").startswith("Static camera")
    assert broll_animate.prompt_text("The camera pushes in slowly").startswith("The camera pushes in slowly.")


def test_fit_crops_to_the_frame_aspect_without_stretching(tmp_path):
    src = tmp_path / "wide.png"
    im = Image.new("RGB", (1152, 720), (0, 0, 0))
    im.paste((255, 0, 0), (536, 0, 616, 720))                  # a red band in the middle
    im.save(src)
    out = Image.open(io.BytesIO(broll_animate.fit(src, 704, 1248)))
    assert out.size == (704, 1248)
    assert out.getpixel((352, 600))[0] > 200                    # the centre is kept


class FakeComfy:
    """/upload/image, /prompt, /history, /view of a ComfyUI that returns ``n`` coloured frames."""

    def __init__(self, n=9, error=None):
        self.n, self.error, self.graph, self.upload, self.polls = n, error, None, None, 0

    def __call__(self, request):
        path = request.url.path
        if path == "/upload/image":
            self.upload = request.content
            return httpx.Response(200, json={"name": "abc.png", "subfolder": "synapse_animate", "type": "input"})
        if path == "/prompt":
            self.graph = json.loads(request.content)["prompt"]
            return httpx.Response(200, json={"prompt_id": "p1"})
        if path == "/history/p1":
            self.polls += 1
            if self.polls < 2:
                return httpx.Response(200, json={})
            if self.error:
                return httpx.Response(200, json={"p1": {"status": {"status_str": "error", "messages": [
                    ["execution_error", {"exception_message": self.error}]]}, "outputs": {}}})
            return httpx.Response(200, json={"p1": {
                "status": {"status_str": "success", "completed": True, "messages": [
                    ["execution_start", {"timestamp": 1000}], ["execution_success", {"timestamp": 42500}]]},
                "outputs": {"out": {"images": [{"filename": f"f{i}.png", "subfolder": "", "type": "temp"}
                                               for i in range(self.n)]}}}})
        if path == "/view":
            i = int(request.url.params["filename"][1:-4])
            buf = io.BytesIO()
            Image.new("RGB", (64, 112), (i * 20 % 255, 80, 120)).save(buf, format="PNG")
            return httpx.Response(200, content=buf.getvalue())
        return httpx.Response(404)


@pytest.fixture
def comfy(monkeypatch):
    def make(**kw):
        fake = FakeComfy(**kw)
        real = httpx.Client

        def client(*a, **k):
            k["transport"] = httpx.MockTransport(fake)
            return real(*a, **k)
        monkeypatch.setattr(httpx, "Client", client)
        monkeypatch.setattr(broll_animate.time, "sleep", lambda s: None)
        monkeypatch.setenv("COMFYUI_URL", "http://comfy.test:8188")
        return fake
    return make


def _probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name,width,height,nb_frames",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)["streams"]


def test_animate_writes_a_silent_vertical_mp4(comfy, tmp_path):
    fake = comfy(n=9)
    src = tmp_path / "pic.jpg"
    Image.new("RGB", (768, 1344), (10, 20, 30)).save(src)
    out = tmp_path / "shot.mp4"
    res = broll_animate.animate(src, "the camera pushes in slowly", out, seconds=0.3, seed=7, out_size=(360, 640))
    assert res["frames"] == 9 and res["seed"] == 7 and res["gpu_s"] == 41.5 and res["path"] == str(out)
    streams = _probe(out)
    assert [s["codec_type"] for s in streams] == ["video"]                # no audio track
    assert streams[0]["codec_name"] == "h264" and (streams[0]["width"], streams[0]["height"]) == (360, 640)
    assert fake.graph["load"]["inputs"]["image"] == "synapse_animate/abc.png"
    assert fake.graph["i2v"]["inputs"]["length"] == 9
    assert fake.graph["pos"]["inputs"]["text"].startswith("the camera pushes in slowly.")
    assert b"\x89PNG" in fake.upload


def test_animate_with_wan22_sends_the_wan_graph(comfy, tmp_path):
    fake = comfy(n=5)
    src = tmp_path / "pic.jpg"
    Image.new("RGB", (768, 1344)).save(src)
    res = broll_animate.animate(src, "steam rises", tmp_path / "w.mp4", seconds=0.2, seed=3, engine="wan22",
                                out_size=(360, 640))
    assert res["engine"] == "wan22" and res["frames"] == 5
    assert fake.graph["sample"]["inputs"]["seed"] == 3 and fake.graph["latent"]["inputs"]["length"] == 5
    assert Image.open(io.BytesIO(fake_upload_png(fake.upload))).size == (704, 1280)


def fake_upload_png(body):
    return body[body.index(b"\x89PNG"):]


def test_a_comfy_error_is_raised_and_no_file_left(comfy, tmp_path):
    comfy(error="Allocation on device")
    src = tmp_path / "pic.jpg"
    Image.new("RGB", (768, 1344)).save(src)
    out = tmp_path / "shot.mp4"
    with pytest.raises(RuntimeError, match="Allocation on device"):
        broll_animate.animate(src, "she blinks once", out, seconds=0.3)
    assert not out.exists()


def test_contact_sheet_has_n_frames_side_by_side(comfy, tmp_path):
    comfy(n=17)
    src = tmp_path / "pic.jpg"
    Image.new("RGB", (768, 1344)).save(src)
    out = tmp_path / "shot.mp4"
    broll_animate.animate(src, "steam rises", out, seconds=0.7, out_size=(360, 640))
    sheet = broll_animate.contact_sheet(out, tmp_path / "sheet.jpg", n=4, width=100)
    w, h = Image.open(sheet).size
    assert w == 4 * 100 + 3 * 6 and h == round(100 * 640 / 360)
