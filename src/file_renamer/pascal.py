"""Bounded, read-only bridge to the genuine PascalScript compiler and interpreter."""

import base64
import fnmatch
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, quote_plus, unquote, unquote_plus

from .metadata import child_options, tool_path

PRELUDE = (Path(__file__).parent / "assets/pascal-support.pas").read_text(encoding="utf-8") + "\n"

FUNCTION_NAMES = tuple(json.loads((Path(__file__).parent / "assets/pascal-functions.json").read_text()))


class PascalSession:
    def __init__(self):
        executable = tool_path("rule_runtime")
        if not executable:
            raise ValueError("Pascal runtime is missing. Build the native rule runtime first.")
        self.process = subprocess.Popen(
            [executable],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            bufsize=1,
            **child_options(),
        )
        self.lines = queue.Queue()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            for line in self.process.stdout:
                self.lines.put(line)
        finally:
            self.lines.put(None)

    def _write(self, payload):
        try:
            self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise ValueError("Pascal runtime stopped") from exc

    def _request(self, request, context=None):
        if "script" in request:
            request = dict(request, script=PRELUDE + request["script"], line_offset=PRELUDE.count("\n"))
        self._write(request)
        deadline = time.monotonic() + 5
        while True:
            try:
                line = self.lines.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                self.close()
                raise ValueError("Pascal Script exceeded its five-second execution limit") from exc
            if line is None:
                raise ValueError("Pascal runtime stopped unexpectedly")
            response = json.loads(line)
            if "query" in response:
                try:
                    value = self._bridge(response, context)
                    self._write({"value": str(value)})
                except Exception as exc:
                    self._write({"error": str(exc)})
                continue
            if "error" in response:
                raise ValueError(response["error"])
            return response

    def _bridge(self, request, context):
        kind, a, b = request["query"], request["a"], request["b"]

        def packed(values):
            return "".join(str(value) + "\0" for value in values)

        direct = {
            "currentindex": context.file_index + 1 if context else 1,
            "markedindex": context.index + 1 if context else 1,
            "totalfiles": len(context.files) if context else 0,
            "totalmarked": len(context.marked_files) if context else 0,
            "allfiles": packed(context.files) if context else "",
            "markedfiles": packed(context.marked_files) if context else "",
            "apppath": context.application_path if context else "",
            "appparams": packed(context.application_params) if context else "",
            "clipboard": context.clipboard if context else "",
            "cwd": os.getcwd(),
            "temppath": tempfile.gettempdir() + os.sep,
        }
        if kind in direct:
            return direct[kind]
        if kind == "env":
            return os.environ.get(a, "")
        if kind == "codepage":
            import ctypes

            def codec(name):
                if name == "ansi":
                    return f"cp{ctypes.windll.kernel32.GetACP()}" if os.name == "nt" else "utf-8"
                if name == "oem":
                    return f"cp{ctypes.windll.kernel32.GetOEMCP()}" if os.name == "nt" else "utf-8"
                return name

            source, destination = b.split(",")
            data = base64.b64decode(a).decode(codec(source)).encode(codec(destination))
            return base64.b64encode(data).decode()
        if kind in {"getglobal", "setglobal", "hasglobal", "clearglobal", "clearglobals", "globalcount", "globalnames"}:
            values = context.globals
            if kind == "setglobal":
                values[a] = json.loads(b)
            elif kind == "getglobal":
                return json.dumps(values.get(a, {}))
            elif kind == "hasglobal":
                return a in values
            elif kind == "clearglobal":
                values.pop(a, None)
            elif kind == "clearglobals":
                values.clear()
            elif kind == "globalcount":
                return len(values)
            else:
                return packed(values)
            return ""
        if kind == "filesearch":
            return next((str(Path(folder) / a) for folder in b.split(";") if (Path(folder) / a).is_file()), "")
        if kind == "shortpath":
            if os.name != "nt":
                raise ValueError("DOS short paths are only available on Windows")
            import ctypes

            buffer = ctypes.create_unicode_buffer(32768)
            if not ctypes.windll.kernel32.GetShortPathNameW(a, buffer, len(buffer)):
                raise ValueError("Short path is unavailable")
            return buffer.value
        if kind in {"scanfiles", "scanfolders"}:
            from .filesystem import hidden_path

            mask, flags = b.split("\0") if kind == "scanfiles" else ("", b)
            recursive, hidden, system_files = [flag.casefold() == "true" for flag in flags.split(",")]
            root = Path(a)
            pending, results = [root], []
            deadline = time.monotonic() + 5
            while pending:
                if time.monotonic() > deadline:
                    raise ValueError("Script directory scan exceeded five seconds")
                folder = pending.pop()
                for entry in sorted(folder.iterdir()):
                    if entry.is_symlink() or (not hidden and hidden_path(entry)):
                        continue
                    if not system_files and getattr(entry.stat(), "st_file_attributes", 0) & 4:
                        continue
                    directory = entry.is_dir()
                    if directory and recursive:
                        pending.append(entry)
                    if directory == (kind == "scanfolders") and (not mask or fnmatch.fnmatchcase(entry.name, mask)):
                        results.append(str(entry))
                    if len(results) > 100000:
                        raise ValueError("Script directory scan exceeds 100,000 entries")
            return packed(results)
        if kind in {"base64encode", "base64decode"}:
            return (
                base64.b64encode(a.encode()).decode()
                if kind == "base64encode"
                else base64.b64decode(a, validate=True).decode()
            )
        if kind == "urlencode":
            return (quote_plus if b.casefold() == "true" else quote)(a, safe="")
        if kind == "urldecode":
            return (unquote_plus if b.casefold() == "true" else unquote)(a)
        if kind == "romanint":
            from .compat_rules import roman

            numbers = dict(I=1, V=5, X=10, L=50, C=100, D=500, M=1000)
            text = a.upper()
            values = [numbers[c] for c in text]
            total = sum(
                -value if i + 1 < len(values) and value < values[i + 1] else value for i, value in enumerate(values)
            )
            if not text or roman(total) != text:
                raise ValueError("Invalid Roman number")
            return total
        if kind == "meta":
            if context.metadata is None:
                from .metadata import Metadata

                context.metadata = Metadata(context.now, context.clipboard)
            return context.metadata.get(b.strip(":"), a)
        if kind == "now":
            return (context.now - datetime(1899, 12, 30)).total_seconds() / 86400
        if kind == "roman":
            from .compat_rules import roman

            return roman(int(a))
        path = Path(a)
        if kind == "exists":
            return path.is_file()
        if kind == "isdir":
            return path.is_dir()
        if kind == "size":
            return path.stat().st_size if path.is_file() else -1
        if kind in {"modified", "created"}:
            info = path.stat()
            if kind == "created" and os.name != "nt" and not hasattr(info, "st_birthtime"):
                raise ValueError("Creation time is unavailable on this filesystem")
            stamp = info.st_mtime if kind == "modified" else getattr(info, "st_birthtime", info.st_ctime)
            return (datetime.fromtimestamp(stamp) - datetime(1899, 12, 30)).total_seconds() / 86400
        if kind == "expandpath":
            return path.absolute()
        if kind == "relativepath":
            return os.path.relpath(b, path.parent)
        if kind == "samepath":
            return os.path.normcase(a) == os.path.normcase(b)
        if kind in {"mask", "masklist"}:
            masks = b.split(";") if kind == "masklist" else [b]
            return any(fnmatch.fnmatchcase(a.casefold(), mask.casefold()) for mask in masks)
        if kind == "metaformat":
            from .date_formats import format_date

            tag, fmt = b.split("\0", 1)
            value = context.metadata.get(tag, a)
            if value and ("Date" in tag or tag == "Date_Now"):
                return format_date(datetime.strptime(value, "%Y-%m-%d %H-%M-%S"), fmt)
            return value
        if kind in {"readtext", "readcontent", "readfragment"}:
            with path.open("rb") as stream:
                if kind == "readfragment":
                    start, count = map(int, b.split(","))
                    if start < 0 or not 0 <= count <= 1024 * 1024:
                        raise ValueError("File fragment is out of range")
                    stream.seek(start)
                    data = stream.read(count)
                else:
                    data = stream.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError("Script text reads are limited to 1 MiB")
            if kind != "readtext":
                return base64.b64encode(data).decode("ascii")
            if data.startswith((b"\xff\xfe", b"\xfe\xff")):
                return data.decode("utf-16")
            try:
                return data.decode("utf-8-sig")
            except UnicodeDecodeError:
                return data.decode("cp1252")
        raise ValueError("Unknown Pascal function")

    def compile(self, script):
        return self._request({"script": script, "compile_only": True})

    def matches(self, pattern, text, case_sensitive):
        return self._request(
            {"operation": "regex", "pattern": pattern, "text": text, "case_sensitive": case_sensitive}
        )["matches"]

    def evaluate(self, script, name, context):
        return self._request(
            {"script": script, "name": name, "path": context.path, "index": context.index + 1}, context
        )["name"]

    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=2)
        self.reader.join(timeout=1)
        self.process.stdin.close()
        self.process.stdout.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
