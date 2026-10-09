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
    assert g["pos"]["inputs"]["text"].startswith("steam rises slowly from the cup. a cup of coffee")
    assert "morphing" in g["neg"]["inputs"]["text"]
    assert g["i2v"]["inputs"]["width"] % 32 == 0 and g["i2v"]["inputs"]["height"] % 32 == 0
    assert g["i2v"]["inputs"]["height"] > g["i2v"]["inputs"]["width"]          # vertical
    assert g["sample"]["inputs"]["noise_seed"] == 42 and g["sample"]["inputs"]["cfg"] == 1.0
    assert g["ckpt"]["inputs"]["ckpt_name"] == broll_animate.MODEL
    assert not any(k.startswith("_") for k in g)


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
