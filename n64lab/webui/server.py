"""A small local web UI for n64lab, using only the Python standard library.

    python -m n64lab ui            # then open http://127.0.0.1:8064

Every ROM you open becomes a *project*: a folder in the workspace holding
the ROM, its symbol file and config, and the generated C project.  The page
in static/ talks to the JSON API below; long builds run as background jobs
the page polls.

This is a local tool with no login.  It listens on 127.0.0.1 unless told
otherwise (Docker needs --host 0.0.0.0), and it builds and runs programs from
ROMs you give it, so don't expose it to a network you don't trust.
"""

import base64
import io
import json
import mimetypes
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback
import zipfile
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from .. import build as builder
from ..codegen import generate_function
from ..interp import Interpreter
from ..rom import Rom, RomError

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
EXAMPLES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "examples")
MAX_UPLOAD = 128 * 1024 * 1024
PROJECT_ID = re.compile(r"^[0-9a-f]{12}$")


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# -- projects ---------------------------------------------------------------------

class Project:
    """A ROM plus everything generated from it, stored in one folder."""

    def __init__(self, workspace, pid):
        self.id = pid
        self.dir = os.path.join(workspace, pid)
        self.lock = threading.Lock()
        self._program = None

    @property
    def meta_path(self):
        return os.path.join(self.dir, "project.json")

    def meta(self):
        with open(self.meta_path, encoding="utf-8") as f:
            return json.load(f)

    def save_meta(self, meta):
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    @property
    def rom_path(self):
        return os.path.join(self.dir, "rom.z64")

    @property
    def symbols_path(self):
        return os.path.join(self.dir, "rom.sym")

    @property
    def recomp_dir(self):
        return os.path.join(self.dir, "recomp")

    def rom(self):
        return Rom.load(self.rom_path)

    def config(self):
        config = dict(self.meta().get("config") or {})
        if os.path.exists(self.symbols_path):
            config["_symbols_file"] = self.symbols_path
        return config

    def program(self, refresh=False):
        """The analyzed program, cached until the config changes."""
        with self.lock:
            if self._program is None or refresh:
                self._program = builder.make_program(self.rom(), self.config())
            return self._program


class Workspace:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)
        self.projects = {}
        self.jobs = {}
        self.lock = threading.Lock()

    def get(self, pid):
        if not PROJECT_ID.match(pid or ""):
            raise ApiError("bad project id", 404)
        with self.lock:
            if pid not in self.projects:
                project = Project(self.root, pid)
                if not os.path.exists(project.meta_path):
                    raise ApiError("no such project", 404)
                self.projects[pid] = project
            return self.projects[pid]

    def create(self, name, rom_bytes, symbols_text=None):
        try:
            rom = Rom.from_bytes(rom_bytes)
        except RomError as e:
            raise ApiError(str(e))
        pid = secrets.token_hex(6)
        project = Project(self.root, pid)
        os.makedirs(project.dir)
        with open(project.rom_path, "wb") as f:
            f.write(rom.data)  # stored big-endian whatever the upload's byte order
        if symbols_text:
            with open(project.symbols_path, "w", encoding="utf-8") as f:
                f.write(symbols_text)
        project.save_meta({"id": pid, "name": name, "title": rom.title, "created": time.time(),
                           "config": {}})
        with self.lock:
            self.projects[pid] = project
        return project

    def list(self):
        out = []
        for pid in sorted(os.listdir(self.root)):
            if PROJECT_ID.match(pid) and os.path.exists(os.path.join(self.root, pid, "project.json")):
                out.append(self.get(pid).meta())
        return sorted(out, key=lambda m: -m.get("created", 0))

    def delete(self, pid):
        project = self.get(pid)
        with self.lock:
            self.projects.pop(pid, None)
        shutil.rmtree(project.dir, ignore_errors=True)

    # Builds take from seconds to minutes, so they run as jobs the page polls.
    def start_job(self, kind, work):
        jid = secrets.token_hex(6)
        job = {"id": jid, "kind": kind, "state": "running", "log": [], "result": None}
        with self.lock:
            self.jobs[jid] = job

        def log(*parts):
            job["log"].append(" ".join(str(p) for p in parts))

        def run():
            try:
                job["result"] = work(log)
                job["state"] = "done"
            except Exception as e:  # report every failure to the page
                job["log"].append(str(e) if isinstance(e, (RuntimeError, ApiError, RomError))
                                  else traceback.format_exc())
                job["state"] = "failed"

        threading.Thread(target=run, daemon=True).start()
        return job

    def job(self, jid):
        job = self.jobs.get(jid)
        if job is None:
            raise ApiError("no such job", 404)
        return job


# -- helpers ----------------------------------------------------------------------

def ppm_to_png(data):
    """Convert the runtime's .ppm screenshot to PNG so a browser can show it."""
    parts = data.split(b"\n", 3)
    width, height = map(int, parts[1].split())
    pixels = parts[3]
    rows = b"".join(b"\0" + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))

    def chunk(kind, body):
        return (len(body).to_bytes(4, "big") + kind + body +
                (zlib.crc32(kind + body) & 0xFFFFFFFF).to_bytes(4, "big"))

    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) +
            chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def function_list(program):
    out = []
    for addr in sorted(program.functions):
        f = program.functions[addr]
        out.append({"start": "0x%08X" % f.start, "end": "0x%08X" % f.end, "name": f.name,
                    "insns": len(f.insns), "reason": f.reason, "warnings": f.warnings,
                    "jump_tables": len(f.jump_tables), "stub": f.start in program.stubs})
    return out


def find_examples():
    found = []
    if os.path.isdir(EXAMPLES_DIR):
        for name in sorted(os.listdir(EXAMPLES_DIR)):
            src = os.path.join(EXAMPLES_DIR, name, name + ".c")
            if os.path.exists(src):
                with open(src, encoding="utf-8") as f:
                    first = f.read(600)
                m = re.search(r"\*\s*\w+\.c\s*-\s*(.+?)(?:\n \*\s*\n|\*/)", first, re.S)
                blurb = re.sub(r"\s*\n\s*\*\s*", " ", m.group(1)).strip() if m else ""
                found.append({"name": name, "description": blurb})
    return found


# -- the API ----------------------------------------------------------------------

class Api:
    def __init__(self, workspace):
        self.ws = workspace

    def tools(self, _):
        from .. import homebrew
        try:
            homebrew.find_toolchain()
            homebrew_ok = True
        except homebrew.ToolchainError:
            homebrew_ok = False
        return {
            "native_compiler": builder.find_compiler("native"),
            "windows_compiler": builder.find_compiler("windows"),
            "homebrew": homebrew_ok,
            "platform": sys.platform,
            "examples": find_examples(),
        }

    def projects(self, _):
        return {"projects": self.ws.list()}

    def upload(self, body, name):
        if not body:
            raise ApiError("empty upload")
        project = self.ws.create(os.path.basename(name) or "rom", body)
        return self.info(project.id)

    def example(self, data):
        from .. import homebrew
        name = data.get("name", "")
        src = os.path.join(EXAMPLES_DIR, name, name + ".c")
        if not re.match(r"^\w+$", name) or not os.path.exists(src):
            raise ApiError("no such example")

        def work(log):
            import tempfile
            log("building examples/%s/%s.c with clang..." % (name, name))
            with tempfile.TemporaryDirectory() as tmp:
                rom_path, sym_path = os.path.join(tmp, "p.z64"), os.path.join(tmp, "p.sym")
                homebrew.build([src], rom_path, title=name.upper(), symbols_out=sym_path)
                with open(rom_path, "rb") as f, open(sym_path, encoding="utf-8") as s:
                    project = self.ws.create(name + ".z64", f.read(), s.read())
            log("built %s.z64 (with function names)" % name)
            return {"project": project.id}

        return self.ws.start_job("example", work)

    def info(self, pid):
        project = self.ws.get(pid)
        rom = project.rom()
        return {
            "project": project.meta(),
            "describe": rom.describe(),
            "title": rom.title, "game_code": rom.game_code, "cic": rom.cic,
            "entry": "0x%08X" % rom.entry, "header_entry": "0x%08X" % rom.header_entry,
            "size": len(rom.data), "checksum_ok": rom.checksum_ok(), "format": rom.source_format,
            "has_symbols": os.path.exists(project.symbols_path),
            "built": self._built(project),
        }

    def _built(self, project):
        """Executables built so far, by target, that still exist."""
        builds = project.meta().get("builds") or {}
        return {target: name for target, name in builds.items()
                if os.path.isfile(os.path.join(project.recomp_dir, name))}

    def set_config(self, pid, data):
        project = self.ws.get(pid)
        config = data.get("config")
        if not isinstance(config, dict):
            raise ApiError("config must be a JSON object")
        meta = project.meta()
        meta["config"] = config
        project.save_meta(meta)
        if "symbols" in data:
            if data["symbols"]:
                with open(project.symbols_path, "w", encoding="utf-8") as f:
                    f.write(data["symbols"])
            elif os.path.exists(project.symbols_path):
                os.remove(project.symbols_path)
        return self.analyze(pid, refresh=True)

    def analyze(self, pid, refresh=False):
        project = self.ws.get(pid)
        try:
            program = project.program(refresh=refresh)
        except (RuntimeError, ValueError, KeyError) as e:
            raise ApiError("config problem: %s" % e)
        meta = project.meta()
        symbols = ""
        if os.path.exists(project.symbols_path):
            with open(project.symbols_path, encoding="utf-8") as f:
                symbols = f.read()
        return {"summary": builder.summary(program), "functions": function_list(program),
                "notes": program.notes, "config": meta.get("config") or {}, "symbols": symbols}

    def function(self, pid, addr):
        project = self.ws.get(pid)
        program = project.program()
        try:
            func = program.functions[int(addr, 0)]
        except (ValueError, KeyError):
            raise ApiError("no function at %s" % addr, 404)
        asm = []
        for insn in func.insns:
            asm.append({"addr": "%08X" % insn.addr, "word": "%08X" % insn.word,
                        "text": insn.text(program.symbols),
                        "label": insn.addr in func.labels and insn.addr != func.start,
                        "delay": False})
        for i, insn in enumerate(func.insns[:-1]):
            if insn.has_delay_slot:
                asm[i + 1]["delay"] = True
        targets = {}
        for insn in func.insns:
            if (insn.is_jump or insn.is_branch) and insn.target in program.functions:
                targets["%08X" % insn.target] = program.functions[insn.target].name
        return {"name": func.name, "start": "0x%08X" % func.start, "end": "0x%08X" % func.end,
                "reason": func.reason, "warnings": func.warnings, "asm": asm,
                "c": generate_function(program, func), "calls": targets}

    def trace(self, pid, data):
        project = self.ws.get(pid)
        steps = max(1, min(int(data.get("steps", 200)), 20000))
        symbols = {}
        if os.path.exists(project.symbols_path):
            from ..analysis import load_symbols
            symbols = load_symbols(project.symbols_path)
        out = io.StringIO()
        interp = Interpreter(project.rom(), symbols=symbols)
        output = interp.run(max_steps=steps, trace=True, out=out)
        return {"trace": out.getvalue(), "output": output}

    def build(self, pid, data):
        project = self.ws.get(pid)
        target = data.get("target", "native")
        if target not in ("native", "windows"):
            raise ApiError("target must be native or windows")
        debug_calls = bool(data.get("debug_calls"))
        opt = "-O" + (str(data.get("opt", "1")).lstrip("-").lstrip("O") or "1")

        def work(log):
            program = project.program()
            log("analysis: " + builder.summary(program))
            name = builder.write_project(program, project.recomp_dir, project.meta()["name"].split(".")[0],
                                         debug_calls=debug_calls)
            log("wrote the C project (src/, runtime/, asm/)")
            exe = builder.compile_project(project.recomp_dir, name, target=target, opt=opt, log=log)
            meta = project.meta()
            meta.setdefault("builds", {})[target] = os.path.basename(exe)
            project.save_meta(meta)
            log("built " + os.path.basename(exe))
            return {"exe": os.path.basename(exe), "target": target}

        return self.ws.start_job("build", work)

    def run(self, pid, data):
        project = self.ws.get(pid)
        exe = self._built(project).get("native")
        if not exe:
            raise ApiError("build it for this computer (target: native) first")
        seconds = max(0.2, min(float(data.get("seconds", 3)), 60))
        shot = os.path.join(project.dir, "screenshot.ppm")
        if os.path.exists(shot):
            os.remove(shot)
        cmd = [os.path.join(project.recomp_dir, exe), project.rom_path, "--headless",
               "--seconds", str(seconds), "--screenshot", shot]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=seconds + 30,
                                    cwd=project.recomp_dir)
        except subprocess.TimeoutExpired:
            raise ApiError("the program did not stop")
        png = None
        if os.path.exists(shot):
            with open(shot, "rb") as f:
                png = base64.b64encode(ppm_to_png(f.read())).decode("ascii")
        return {"stdout": result.stdout.decode("utf-8", "replace"),
                "log": result.stderr.decode("utf-8", "replace"),
                "exit_code": result.returncode, "screenshot": png}

    def download(self, pid, what):
        """Returns (filename, bytes, content type)."""
        project = self.ws.get(pid)
        if what == "exe":
            built = self._built(project)
            name = built.get("windows") or built.get("native")
            if not name:
                raise ApiError("nothing built yet", 404)
            with open(os.path.join(project.recomp_dir, name), "rb") as f:
                return name, f.read(), "application/octet-stream"
        if what == "project":
            if not os.path.isdir(project.recomp_dir):
                raise ApiError("recompile first", 404)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
                for root, dirs, files in os.walk(project.recomp_dir):
                    dirs[:] = [d for d in dirs if d != "build"]
                    for f in files:
                        path = os.path.join(root, f)
                        z.write(path, os.path.relpath(path, project.recomp_dir))
            return "%s_recomp.zip" % project.meta()["name"].split(".")[0], buf.getvalue(), "application/zip"
        raise ApiError("unknown download", 404)


# -- HTTP plumbing ---------------------------------------------------------------------

def make_handler(api, quiet=True):
    routes = [
        ("GET", r"/api/tools$", lambda h, m: api.tools(None)),
        ("GET", r"/api/projects$", lambda h, m: api.projects(None)),
        ("POST", r"/api/upload$", lambda h, m: api.upload(
            h.body(), unquote(h.headers.get("X-Filename", "rom.z64")))),
        ("POST", r"/api/examples$", lambda h, m: api.example(h.json())),
        ("GET", r"/api/jobs/(\w+)$", lambda h, m: api.ws.job(m.group(1))),
        ("GET", r"/api/projects/(\w+)$", lambda h, m: api.info(m.group(1))),
        ("DELETE", r"/api/projects/(\w+)$", lambda h, m: api.ws.delete(m.group(1)) or {"deleted": True}),
        ("GET", r"/api/projects/(\w+)/functions$", lambda h, m: api.analyze(m.group(1))),
        ("PUT", r"/api/projects/(\w+)/config$", lambda h, m: api.set_config(m.group(1), h.json())),
        ("GET", r"/api/projects/(\w+)/functions/(0x[0-9A-Fa-f]+)$",
         lambda h, m: api.function(m.group(1), m.group(2))),
        ("POST", r"/api/projects/(\w+)/trace$", lambda h, m: api.trace(m.group(1), h.json())),
        ("POST", r"/api/projects/(\w+)/build$", lambda h, m: api.build(m.group(1), h.json())),
        ("POST", r"/api/projects/(\w+)/run$", lambda h, m: api.run(m.group(1), h.json())),
    ]

    class Handler(BaseHTTPRequestHandler):
        server_version = "n64lab"

        def log_message(self, fmt, *args):
            if not quiet:
                super().log_message(fmt, *args)

        def body(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD:
                raise ApiError("file too large", 413)
            return self.rfile.read(length)

        def json(self):
            try:
                return json.loads(self.body() or b"{}")
            except ValueError:
                raise ApiError("request body is not JSON")

        def send(self, status, body, content_type, extra=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status, data):
            self.send(status, json.dumps(data).encode("utf-8"), "application/json")

        def dispatch(self, method):
            path = urlparse(self.path).path
            try:
                m = re.match(r"^/api/projects/(\w+)/download/(exe|project)$", path)
                if m and method == "GET":
                    name, data, ctype = api.download(m.group(1), m.group(2))
                    self.send(200, data, ctype, {"Content-Disposition": 'attachment; filename="%s"' % name})
                    return
                for verb, pattern, handler in routes:
                    m = re.match(pattern, path)
                    if m and verb == method:
                        self.send_json(200, handler(self, m))
                        return
                if method == "GET" and not path.startswith("/api/"):
                    self.static(path)
                    return
                raise ApiError("not found", 404)
            except ApiError as e:
                self.send_json(e.status, {"error": str(e)})
            except (RomError, RuntimeError, OSError) as e:
                self.send_json(400, {"error": str(e)})
            except Exception:
                self.send_json(500, {"error": traceback.format_exc()})

        def static(self, path):
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            full = os.path.realpath(os.path.join(STATIC_DIR, name))
            if not full.startswith(os.path.realpath(STATIC_DIR) + os.sep) or not os.path.isfile(full):
                raise ApiError("not found", 404)
            with open(full, "rb") as f:
                ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                self.send(200, f.read(), ctype)

        def do_GET(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

        def do_PUT(self):
            self.dispatch("PUT")

        def do_DELETE(self):
            self.dispatch("DELETE")

    return Handler


def make_server(host="127.0.0.1", port=8064, workspace="n64lab_workspace", quiet=True):
    api = Api(Workspace(workspace))
    return ThreadingHTTPServer((host, port), make_handler(api, quiet))


def serve(host="127.0.0.1", port=8064, workspace="n64lab_workspace", open_browser=False):
    server = make_server(host, port, workspace, quiet=False)
    url = "http://%s:%d/" % ("127.0.0.1" if host in ("0.0.0.0", "") else host, server.server_port)
    print("n64lab web UI running at %s  (workspace: %s)" % (url, os.path.abspath(workspace)))
    if host not in ("127.0.0.1", "localhost"):
        print("note: listening on %s, so other machines can reach it; it has no login." % host)
    print("press Ctrl+C to stop")
    if open_browser:
        import webbrowser
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
