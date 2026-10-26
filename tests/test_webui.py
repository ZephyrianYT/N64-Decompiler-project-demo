"""Tests for the web UI's JSON API (n64lab/webui/server.py)."""

import io
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from n64lab import build as builder, homebrew  # noqa: E402
from n64lab.webui.server import make_server  # noqa: E402


def have_toolchain():
    try:
        homebrew.find_toolchain()
    except homebrew.ToolchainError:
        return False
    return builder.find_compiler("native") is not None


class WebUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workspace = tempfile.mkdtemp(prefix="n64lab_ws_")
        cls.server = make_server("127.0.0.1", 0, cls.workspace)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_port
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        shutil.rmtree(cls.workspace, ignore_errors=True)

    def request(self, method, path, body=None, headers=None, raw=False):
        data = body if isinstance(body, bytes) or body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=600) as res:
                content = res.read()
                return res.status, content if raw else json.loads(content)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def wait_job(self, job):
        for _ in range(1200):
            status, j = self.request("GET", "/api/jobs/" + job["id"])
            if j["state"] != "running":
                self.assertEqual(j["state"], "done", "\n".join(j["log"]))
                return j["result"]
            time.sleep(0.25)
        self.fail("job did not finish")

    def tiny_rom(self):
        code = [0x0C000104, 0x00000000, 0x0000000D, 0x00000000,  # jal f; nop; break; nop
                0x03E00008, 0x24020007]                            # f: jr $ra; li $v0, 7
        return homebrew.make_rom(b"".join(struct.pack(">I", w) for w in code), title="TINY")

    def test_page_and_static_files(self):
        status, html = self.request("GET", "/", raw=True)
        self.assertEqual(status, 200)
        self.assertIn(b"Wizard", html)
        for path in ("/app.js", "/style.css"):
            self.assertEqual(self.request("GET", path, raw=True)[0], 200)

    def test_rejects_paths_outside_the_static_folder(self):
        status, _ = self.request("GET", "/../server.py")
        self.assertEqual(status, 404)
        status, _ = self.request("GET", "/api/projects/../../etc")
        self.assertEqual(status, 404)

    def test_upload_inspect_analyze_and_view(self):
        status, info = self.request("POST", "/api/upload", self.tiny_rom(), {"X-Filename": "tiny.z64"})
        self.assertEqual(status, 200, info)
        pid = info["project"]["id"]
        self.assertEqual(info["title"], "TINY")
        self.assertTrue(info["checksum_ok"])

        status, analysis = self.request("GET", "/api/projects/%s/functions" % pid)
        self.assertEqual([f["start"] for f in analysis["functions"]], ["0x80000400", "0x80000410"])

        status, func = self.request("GET", "/api/projects/%s/functions/0x80000410" % pid)
        self.assertEqual(func["asm"][1]["delay"], True)  # the delay slot of `jr $ra`
        self.assertIn("return;", func["c"])

        status, analysis = self.request("PUT", "/api/projects/%s/config" % pid,
                                        {"config": {"names": {"0x80000410": "seven"}}, "symbols": ""})
        self.assertEqual(status, 200, analysis)
        self.assertIn("seven", [f["name"] for f in analysis["functions"]])

        status, err = self.request("PUT", "/api/projects/%s/config" % pid,
                                   {"config": {"stubs": ["no_such_function"]}})
        self.assertEqual(status, 400)
        self.assertIn("no_such_function", err["error"])

        status, trace = self.request("POST", "/api/projects/%s/trace" % pid, {"steps": 10})
        self.assertIn("jal", trace["trace"])

        status, listing = self.request("GET", "/api/projects")
        self.assertIn(pid, [p["id"] for p in listing["projects"]])
        self.assertEqual(self.request("DELETE", "/api/projects/" + pid)[0], 200)
        self.assertEqual(self.request("GET", "/api/projects/" + pid)[0], 404)

    def test_rejects_files_that_are_not_roms(self):
        status, err = self.request("POST", "/api/upload", b"hello" * 1000, {"X-Filename": "x.z64"})
        self.assertEqual(status, 400)
        self.assertIn("not an N64 ROM", err["error"])

    @unittest.skipUnless(have_toolchain(), "needs clang, ld.lld and a C compiler")
    def test_wizard_round_trip_with_an_example(self):
        status, job = self.request("POST", "/api/examples", {"name": "hello"})
        pid = self.wait_job(job)["project"]
        status, info = self.request("GET", "/api/projects/" + pid)
        self.assertTrue(info["has_symbols"])

        status, job = self.request("POST", "/api/projects/%s/build" % pid,
                                   {"target": "native", "opt": "1", "debug_calls": True})
        self.wait_job(job)
        status, result = self.request("POST", "/api/projects/%s/run" % pid, {"seconds": 10})
        self.assertIn("fib(10) = 55", result["stdout"])
        self.assertIn("program finished", result["log"])

        status, data = self.request("GET", "/api/projects/%s/download/project" % pid, raw=True)
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        self.assertIn("src/game_info.c", names)
        self.assertIn("runtime/n64_runtime.h", names)
        self.assertFalse(any(n.startswith("build/") for n in names))


if __name__ == "__main__":
    unittest.main()
