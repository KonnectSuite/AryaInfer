"""serve/test_comfyui.py - ComfyUI images against a fake ComfyUI (no GPU, no ComfyUI, no network beyond localhost).

    python -m unittest serve.test_comfyui -v
"""
import json
import sys
import tempfile
import urllib.error
import urllib.request
import time
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from serve import comfy_fake_server as fake  # noqa: E402
from serve import comfyui as C  # noqa: E402
from serve.frontend import ChatTemplate  # noqa: E402
from serve.gallery import Gallery  # noqa: E402
from serve.server import ByteTokenizer, MockEngine, Service, serve  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SHIPPED = ROOT / "serve" / "comfy-workflows"
SQUARE = "Qwen_Image_2_1_Turbo_Square_1024"
EDIT = "Qwen_Image_2_1_Turbo_Edit"


def hub_for(tmp: str, base: str, **settings) -> C.ComfyHub:
    """A hub whose settings file, imports and gallery all live in `tmp`."""
    conf = C.normalize({"base_url": base, "timeout_s": 30, **settings})
    return C.ComfyHub(conf, settings_path=Path(tmp) / "comfyui.json", shipped=SHIPPED)


class Prepare(unittest.TestCase):
    """The placeholder contract: what a graph may declare and what a request may supply."""

    def test_prompt_and_seed_are_filled(self):
        graph = {"1": {"class_type": "Text", "inputs": {"prompt": "a {{prompt}} b", "noise_seed": "{{seed}}"}},
                 "2": {"class_type": "SaveImage", "inputs": {}}}
        out = C.prepare(graph, prompt="cat", seed=7)
        self.assertEqual(out["1"]["inputs"], {"prompt": "a cat b", "noise_seed": 7})

    def test_a_graph_without_the_prompt_placeholder_is_refused(self):
        graph = {"1": {"class_type": "Text", "inputs": {"prompt": "just text"}}}
        with self.assertRaises(C.WorkflowError) as caught:
            C.prepare(graph, prompt="cat")
        self.assertIn("{{prompt}}", str(caught.exception))

    def test_numeric_placeholders_must_be_whole_fields(self):
        graph = {"1": {"class_type": "Empty", "inputs": {"width": "{{width}}", "height": 512}},
                 "2": {"class_type": "Text", "inputs": {"prompt": "{{prompt}}"}}}
        self.assertEqual(C.prepare(graph, prompt="x", width=768)["1"]["inputs"]["width"], 768)
        embedded = {"1": {"class_type": "Text", "inputs": {"prompt": "a {{width}} wide picture"}},
                    "2": {"class_type": "Text", "inputs": {"prompt": "{{prompt}}"}}}
        with self.assertRaises(C.WorkflowError) as caught:
            C.prepare(embedded, prompt="x")
        self.assertIn("whole value", str(caught.exception))

    def test_a_baked_size_is_not_adjustable(self):
        graph = {"1": {"class_type": "Empty", "inputs": {"width": 1024, "height": 1024}},
                 "2": {"class_type": "Text", "inputs": {"prompt": "{{prompt}}"}}}
        with self.assertRaises(C.WorkflowError) as caught:
            C.prepare(graph, prompt="x", width=512)
        self.assertIn("bakes width", str(caught.exception))

    def test_the_resolution_follows_the_canvas(self):
        graph = {"1": {"class_type": "Encode", "inputs": {"prompt": "{{prompt}}", "width": "{{width}}",
                                                          "height": "{{height}}", "resolution": "{{resolution}}"}}}
        out = C.prepare(graph, prompt="x", width=768, height=1344)
        self.assertEqual((out["1"]["inputs"]["width"], out["1"]["inputs"]["height"]), (768, 1344))
        self.assertEqual(out["1"]["inputs"]["resolution"], 1344)
        out = C.prepare(graph, prompt="x", width=1000, height=1000)      # snapped to 32
        self.assertEqual(out["1"]["inputs"]["resolution"], 992)

    def test_an_image_input_needs_a_source(self):
        graph = {"1": {"class_type": "LoadImage", "inputs": {"image": "{{image}}"}},
                 "2": {"class_type": "Text", "inputs": {"prompt": "{{prompt}}"}}}
        with self.assertRaises(C.WorkflowError) as caught:
            C.prepare(graph, prompt="x")
        self.assertIn("source image", str(caught.exception))
        self.assertEqual(C.prepare(graph, prompt="x", image="up.png")["1"]["inputs"]["image"], "up.png")

    def test_references_expand_in_order(self):
        graph = {"1": {"class_type": "Text", "inputs": {"prompt": "{{prompt}}"}},
                 "14": {"class_type": "Encode", "inputs": {"images.image_1": ["{{images}}", 0]}}}
        out = C.prepare(graph, prompt="x", images=["a.png", "b.png"])
        inputs = out["14"]["inputs"]
        first, second = inputs["images.image_1"], inputs["images.image_2"]
        self.assertNotEqual(first[0], second[0])
        self.assertEqual(out[first[0]]["inputs"]["image"], "a.png")
        self.assertEqual(out[second[0]]["inputs"]["image"], "b.png")
        self.assertEqual(out[first[0]]["class_type"], "LoadImage")

    def test_too_many_references(self):
        graph = {"1": {"class_type": "Text", "inputs": {"prompt": "{{prompt}}"}},
                 "2": {"class_type": "Encode", "inputs": {"images.image_1": ["{{images}}", 0]}}}
        with self.assertRaises(C.WorkflowError) as caught:
            C.prepare(graph, prompt="x", images=[f"{i}.png" for i in range(17)])
        self.assertIn("at most 16", str(caught.exception))

    def test_the_shipped_graphs_describe_themselves(self):
        workflows = {w["name"]: w for w in C.load_workflows(SHIPPED, None)}
        self.assertEqual(len(workflows), 6)
        self.assertEqual(workflows[SQUARE]["role"], "text-to-image")
        self.assertEqual(workflows[SQUARE]["baked_size"], {"width": 1024, "height": 1024})
        self.assertEqual(workflows[EDIT]["role"], "image-to-image")
        self.assertFalse(workflows[EDIT]["baked_size"])
        self.assertEqual(workflows["Qwen_Image_2_1_Cutout_RGBA_1024"]["role"], "text-to-image")

    def test_the_shipped_graphs_prepare(self):
        text = (SHIPPED / f"{SQUARE}.json").read_text(encoding="utf-8-sig")
        out = C.prepare(text, prompt="a cat", seed=5)
        joined = json.dumps(out)
        self.assertIn("a cat", joined)
        self.assertIn('"noise_seed": 5', joined)
        edit = (SHIPPED / f"{EDIT}.json").read_text(encoding="utf-8-sig")
        with self.assertRaises(C.WorkflowError):
            C.prepare(edit, prompt="a cat")
        out = C.prepare(edit, prompt="a cat", image="up.png")
        self.assertIn("up.png", json.dumps(out))


class Settings(unittest.TestCase):
    def test_bad_values_are_refused(self):
        for bad in ({"base_url": "not a url"}, {"base_url": "ftp://x"}, {"timeout_s": 1},
                    {"free_vram": {"policy": "borrow"}}, {"launch": {"mode": "magic"}},
                    {"gallery": {"max_files": 1}}, {"headers": "x"}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    C.normalize(bad)

    def test_the_headers_are_masked_and_kept(self):
        settings = C.normalize({"headers": {"Authorization": "Bearer s3cret"}})
        public = C.public_settings(settings)
        self.assertEqual(public["headers"], {"Authorization": C.MASK})
        self.assertNotIn("s3cret", json.dumps(public))
        merged = C.merge_secrets({"headers": {"Authorization": C.MASK}}, settings)
        self.assertEqual(merged["headers"]["Authorization"], "Bearer s3cret")

    def test_a_file_round_trip(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "comfyui.json"
            settings = C.normalize({"base_url": "http://127.0.0.1:9999", "active_text": SQUARE})
            C.write_settings(path, settings)
            self.assertEqual(C.read_settings(path)["base_url"], "http://127.0.0.1:9999")
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(C.read_settings(path), {})
            self.assertTrue(list(Path(d).glob("comfyui.json.corrupt-*")))


class Check(unittest.TestCase):
    """Check names what a ComfyUI lacks before a run fails."""

    def setUp(self):
        self.httpd = fake.comfy_server()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def test_every_shipped_workflow_checks_out(self):
        hub = hub_for(self.tmp.name, self.base)
        result = hub.check()
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["workflows"]), 6)
        bad = [w for w in result["workflows"] if not w["ok"]]
        self.assertEqual(bad, [], bad)

    def test_a_missing_node_class_is_named(self):
        self.httpd.missing_node = "SaveImage"
        result = hub_for(self.tmp.name, self.base).check()
        first = result["workflows"][0]
        self.assertFalse(first["ok"])
        self.assertTrue(any("SaveImage" in m for m in first["missing_nodes"]))

    def test_a_missing_model_file_is_named(self):
        self.httpd.missing_model = "qwen_image_2.1_turbo_int8_convrot.safetensors"
        result = hub_for(self.tmp.name, self.base).check()
        first = result["workflows"][0]
        self.assertFalse(first["ok"])
        self.assertTrue(any("qwen_image_2.1_turbo_int8_convrot" in m for m in first["missing_models"]))

    def test_an_unreachable_server_says_so(self):
        hub = hub_for(self.tmp.name, "http://127.0.0.1:9")
        with self.assertRaises(C.ComfyError) as caught:
            hub.check()
        self.assertIn("Could not reach ComfyUI", str(caught.exception))


class Generate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.httpd = fake.comfy_server()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.hub = hub_for(self.tmp.name, self.base)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def test_one_image_lands_in_the_gallery(self):
        result = self.hub.generate({"prompt": "a cat", "count": 1, "workflow": SQUARE, "seed": 3})
        self.assertEqual(len(result["images"]), 1)
        image = result["images"][0]
        self.assertTrue(image["url"].startswith("/comfy/files/"))
        self.assertEqual(image["seed"], 3)
        record = self.hub.gallery.get(image["id"])
        self.assertIsNotNone(record)
        self.assertEqual(record["prompt"], "a cat")
        path = self.hub.gallery.file(record["file"])
        self.assertIsNotNone(path)
        self.assertTrue(path.read_bytes().startswith(b"\x89PNG"))

    def test_two_images_get_sequential_seeds(self):
        result = self.hub.generate({"prompt": "two", "count": 2, "workflow": SQUARE, "seed": 10})
        self.assertEqual([i["seed"] for i in result["images"]], [10, 11])
        self.assertEqual(len(self.hub.gallery.list()["items"]), 2)

    def test_an_edit_uploads_its_reference(self):
        record = self.hub.gallery.add(fake.PNG, {"prompt": "source", "provider": "comfyui"})
        result = self.hub.generate({"prompt": "make it blue", "count": 1, "workflow": EDIT,
                                    "references": [{"id": record["id"]}], "source": "edit"})
        self.assertEqual(len(self.httpd.uploads), 1)
        self.assertEqual(result["images"][0]["seed"] is not None, True)
        self.assertEqual(self.hub.gallery.get(result["images"][0]["id"])["source"], "edit")

    def test_a_reference_data_url_is_decoded(self):
        import base64
        data_url = "data:image/png;base64," + base64.b64encode(fake.PNG).decode()
        image = self.hub.upload_image(data_url)
        self.assertTrue(image["url"].startswith("/comfy/files/"))

    def test_a_comfyui_failure_is_the_sentence_the_page_shows(self):
        self.httpd.mode = "error"
        with self.assertRaises(C.ComfyError) as caught:
            self.hub.generate({"prompt": "boom", "count": 1, "workflow": SQUARE})
        self.assertIn("it failed on purpose", str(caught.exception))

    def test_a_workflow_without_an_output_says_so(self):
        self.httpd.mode = "no-output"
        with self.assertRaises(C.ComfyError) as caught:
            self.hub.generate({"prompt": "quiet", "count": 1, "workflow": SQUARE})
        self.assertIn("without an output image", str(caught.exception))

    def test_a_rejected_workflow_carries_comfyui_why(self):
        self.httpd.mode = "reject"
        with self.assertRaises(C.ComfyError) as caught:
            self.hub.generate({"prompt": "bad", "count": 1, "workflow": SQUARE})
        self.assertIn("prompt_outputs_failed_validation", str(caught.exception))

    def test_an_edit_graph_needs_a_reference_and_a_text_graph_takes_none(self):
        with self.assertRaises(C.WorkflowError):
            self.hub.generate({"prompt": "x", "count": 1, "workflow": EDIT})
        record = self.hub.gallery.add(fake.PNG, {"prompt": "s"})
        with self.assertRaises(C.WorkflowError):
            self.hub.generate({"prompt": "x", "count": 1, "workflow": SQUARE,
                               "references": [{"id": record["id"]}]})

    def test_a_job_runs_and_reports_itself(self):
        job = self.hub.start_job({"prompt": "async", "count": 1, "workflow": SQUARE})
        self.assertEqual(job["state"], "queued")
        deadline = time.monotonic() + 20
        state = job["state"]
        while time.monotonic() < deadline and state in ("queued", "running"):
            time.sleep(0.1)
            state = self.hub.job(job["id"])["state"]
        self.assertEqual(state, "done")
        self.assertEqual(len(self.hub.job(job["id"])["images"]), 1)

    def test_cancel_stops_a_slow_job(self):
        self.httpd.delay = 5.0
        job = self.hub.start_job({"prompt": "slow", "count": 1, "workflow": SQUARE})
        time.sleep(0.5)
        self.hub.cancel_job(job["id"])
        deadline = time.monotonic() + 20
        state = "queued"
        while time.monotonic() < deadline and state in ("queued", "running"):
            time.sleep(0.1)
            state = self.hub.job(job["id"])["state"]
        self.assertEqual(state, "cancelled")


class ToolCall(unittest.TestCase):
    """The chat's generate_image tool: what the model is offered and what comes back."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.httpd = fake.comfy_server()
        self.hub = hub_for(self.tmp.name, f"http://127.0.0.1:{self.httpd.server_address[1]}")

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def test_the_tool_is_offered_with_a_prompt_argument(self):
        tools = self.hub.tools()
        self.assertEqual([t["name"] for t in tools], ["generate_image"])
        self.assertEqual(tools[0]["parameters"]["required"], ["prompt"])
        self.assertIn("generate_image", self.hub.routes())

    def test_a_call_answers_with_the_addresses(self):
        result = self.hub.call("generate_image", {"prompt": "a lighthouse", "count": 1})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["server"], "images")
        self.assertIn("/comfy/files/", result["text"])
        self.assertEqual(len(result["images"]), 1)
        self.assertTrue(result["images"][0]["url"].startswith("/comfy/files/"))

    def test_an_empty_prompt_is_an_error_result_not_a_crash(self):
        result = self.hub.call("generate_image", {"prompt": "   "})
        self.assertFalse(result["ok"])
        self.assertTrue(result["text"].startswith("error:"))


class GalleryStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.gallery = Gallery(Path(self.tmp.name), {"max_files": 3, "max_mib": 0})

    def tearDown(self):
        self.tmp.cleanup()

    def test_newest_first_and_paged(self):
        for i in range(4):
            self.gallery.add(fake.PNG, {"prompt": f"p{i}", "created": 100 + i})
        page = self.gallery.list(limit=2)
        self.assertEqual([r["prompt"] for r in page["items"]], ["p3", "p2"])
        self.assertEqual(self.gallery.list(limit=2)["total"], 3)          # pruned to max_files
        self.assertTrue(self.gallery.list(limit=2)["more"])
        self.assertFalse(self.gallery.list(limit=5)["more"])

    def test_favourites_survive_pruning(self):
        first = self.gallery.add(fake.PNG, {"prompt": "keep me", "created": 1})
        self.gallery.favorite(first["id"], True)
        for i in range(10):
            self.gallery.add(fake.PNG, {"prompt": f"p{i}", "created": 10 + i})
        prompts = [r["prompt"] for r in self.gallery.list(limit=10)["items"]]
        self.assertIn("keep me", prompts)
        self.assertLessEqual(len(prompts), 3)

    def test_delete_removes_the_file_and_the_record(self):
        item = self.gallery.add(fake.PNG, {"prompt": "bye"})
        self.assertTrue(self.gallery.favorite(item["id"])["favorite"])
        self.assertEqual(self.gallery.delete([item["id"]]), [item["id"]])
        self.assertIsNone(self.gallery.get(item["id"]))
        self.assertFalse((Path(self.tmp.name) / item["file"]).exists())

    def test_a_file_name_cannot_leave_the_folder(self):
        self.assertIsNone(self.gallery.file("../secrets.txt"))
        self.assertIsNone(self.gallery.file("abc.png"))
        self.assertIsNotNone(self.gallery.file(self.gallery.add(fake.PNG, {})["file"]))

    def test_an_unreadable_index_is_moved_aside(self):
        path = Path(self.tmp.name) / "index.json"
        path.write_text("{oops", encoding="utf-8")
        reopened = Gallery(Path(self.tmp.name), {"max_files": 3})
        self.assertEqual(reopened.items, [])
        self.assertTrue(list(Path(self.tmp.name).glob("index.json.corrupt-*")))


class Launcher(unittest.TestCase):
    """The launch rules that do not need a process: what is local, which plan applies, argument splitting."""

    def test_only_this_machine_can_be_started(self):
        for url, local in (("http://127.0.0.1:8188", True), ("http://localhost:8188", True),
                           ("https://comfy.example.org", False), ("http://100.64.0.5:8188", False)):
            with self.subTest(url=url):
                self.assertEqual(C.is_local(url), local)

    def test_extra_arguments_split_like_a_shell(self):
        self.assertEqual(C._extra_args("--listen 127.0.0.1 --port 8188"), ["--listen", "127.0.0.1", "--port", "8188"])
        self.assertEqual(C._extra_args('--extra-model-paths-config "C:/my models/extra.yaml"'),
                         ["--extra-model-paths-config", "C:/my models/extra.yaml"])
        self.assertEqual(C._extra_args(""), [])

    def test_the_plan_follows_the_mode_and_what_exists(self):
        with tempfile.TemporaryDirectory() as d:
            settings = C.normalize({"launch": {"mode": "process", "server_dir": d, "python_exe": sys.executable}})
            manager = C.ServerManager(lambda: settings)
            self.assertEqual(manager._plan()["launch"], "process")
            settings["launch"]["mode"] = "auto"
            self.assertEqual(manager._plan()["launch"], "external")     # no task, no main.py
            (Path(d) / "main.py").write_text("print('x')", encoding="utf-8")
            self.assertEqual(manager._plan()["launch"], "process")      # main.py is there now
            settings["launch"]["mode"] = "scheduled-task"
            self.assertEqual(manager._plan()["launch"], "scheduled-task")


class Http(unittest.TestCase):
    """The page's own endpoints: GET /comfy, POST /comfy, GET /comfy/files/."""

    @classmethod
    def setUpClass(cls):
        cls.httpd = fake.comfy_server()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tok = ByteTokenizer()
        self.svc = Service(MockEngine(tok, "</think>\n\nhi"), tok, ChatTemplate(ROOT / "serve/chat_template.jinja"))
        self.svc.comfy = hub_for(self.tmp.name, self.base)
        self.httpd_strata = serve(self.svc, port=0)
        self.base_url = f"http://127.0.0.1:{self.httpd_strata.server_address[1]}"

    def tearDown(self):
        self.httpd_strata.shutdown()
        self.httpd_strata.server_close()
        self.tmp.cleanup()

    def call(self, path, body=None, ctype="application/json"):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base_url + path, data=data,
                                     headers={"Content-Type": ctype} if data is not None else {})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                ctype_out = r.headers.get("Content-Type", "")
                raw = r.read()
                return r.status, (json.loads(raw) if "json" in ctype_out else raw), ctype_out
        except urllib.error.HTTPError as e:
            with e:
                return e.code, json.loads(e.read() or b"{}"), e.headers.get("Content-Type", "")

    def test_the_view_lists_the_workflows(self):
        code, view, _ = self.call("/comfy")
        self.assertEqual(code, 200, view)
        self.assertTrue(view["configured"])
        self.assertEqual(len(view["workflows"]), 6)
        self.assertEqual(view["settings"]["headers"], {})

    def test_set_and_check(self):
        code, out, _ = self.call("/comfy", {"set": {"base_url": self.base, "active_text": SQUARE}})
        self.assertEqual(code, 200, out)
        self.assertEqual(out["settings"]["active_text"], SQUARE)
        code, out, _ = self.call("/comfy", {"check": True})
        self.assertEqual(code, 200, out)
        self.assertTrue(all(w["ok"] for w in out["check"]["workflows"]))

    def test_generate_then_fetch_the_image(self):
        code, out, _ = self.call("/comfy", {"generate": {"prompt": "a fox", "count": 1, "workflow": SQUARE}})
        self.assertEqual(code, 202, out)
        job_id = out["job"]["id"]
        deadline = time.monotonic() + 20
        job = None
        while time.monotonic() < deadline:
            code, view, _ = self.call(f"/comfy?job={job_id}")
            job = view.get("job") or {}
            if job.get("state") in ("done", "error", "cancelled"):
                break
            time.sleep(0.1)
        self.assertEqual(job.get("state"), "done", job)
        image = job["images"][0]
        code, body, ctype = self.call(image["url"])
        self.assertEqual(code, 200)
        self.assertIn("image/png", ctype)
        self.assertTrue(body.startswith(b"\x89PNG"))
        code, out, _ = self.call("/comfy", {"delete": [image["id"]]})
        self.assertEqual(code, 200, out)
        self.assertEqual(self.call(image["url"])[0], 404)

    def test_the_gallery_page_lists_the_images(self):
        code, out, _ = self.call("/comfy", {"generate": {"prompt": "page", "count": 2, "workflow": SQUARE}})
        self.assertEqual(code, 202, out)
        time.sleep(1.0)
        code, view, _ = self.call("/comfy?gallery=1&limit=10")
        self.assertEqual(code, 200, view)
        self.assertIn("page", view)
        self.assertGreaterEqual(len(view["page"]["items"]), 1)

    def test_the_page_only(self):
        code, out, _ = self.call("/comfy", {"set": {}}, ctype="text/plain")
        self.assertEqual(code, 415, out)

    def test_an_unknown_action_is_a_400(self):
        code, out, _ = self.call("/comfy", {"nonsense": True})
        self.assertEqual(code, 400, out)


if __name__ == "__main__":
    unittest.main()
