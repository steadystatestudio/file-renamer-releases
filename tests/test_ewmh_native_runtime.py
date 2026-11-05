"""Exercise real XRandR cleanup and EWMH validation on an owned authenticated Xvfb."""

import ctypes
import ctypes.util
import json
import os
import secrets
import select
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Native Linux C/X11 fixtures")
HERE = Path(__file__).parent
SOURCE = (
    HERE / "ewmh_workarea.c"
    if (HERE / "ewmh_workarea.c").exists()
    else HERE.parent / "scripts/native_appearance_probe.c"
)


def _wait_for_display(process, descriptor, stderr_path, timeout=20):
    """Require a real bounded displayfd response and retain the startup reason."""
    started = time.monotonic()
    deadline = started + timeout
    response = bytearray()

    def failed(reason):
        with stderr_path.open("rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - 16384))
            stderr = stream.read(16384).decode("utf-8", errors="replace")
        elapsed = time.monotonic() - started
        raise AssertionError(
            f"Owned Xvfb {reason}; exit={process.poll()}; elapsed={elapsed:.3f}s; stderr-tail={stderr}"
        )

    while time.monotonic() < deadline:
        if process.poll() is not None:
            failed("exited-before-readiness")
        remaining = max(0, deadline - time.monotonic())
        if not select.select([descriptor], [], [], min(.05, remaining))[0]:
            continue
        chunk = os.read(descriptor, 32 - len(response))
        if not chunk:
            failed("closed-displayfd-before-readiness")
        response.extend(chunk)
        if b"\n" in response:
            value = bytes(response).strip()
            if not value.isdigit() or len(value) > 5:
                failed("invalid-displayfd-response")
            return ":" + value.decode("ascii")
        if len(response) == 32:
            failed("oversized-displayfd-response")
    failed("readiness-timeout")


@pytest.fixture(scope="module")
def native(tmp_path_factory):
    root = tmp_path_factory.mktemp("owned-ewmh")
    compiler = shutil.which("cc")
    server = shutil.which("Xvfb")
    if not compiler or not server:
        pytest.skip("Native compiler and owned Xvfb are required")
    if not ctypes.util.find_library("Xrandr"):
        pytest.skip("XRandR cleanup regression requires optional host library")
    exe = root / "workarea-probe"
    subprocess.run(
        [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", str(SOURCE), "-ldl", "-o", str(exe)], check=True
    )
    auth = root / "Xauthority"
    name = b"MIT-MAGIC-COOKIE-1"
    cookie = secrets.token_bytes(16)
    auth.write_bytes(struct.pack(">HHHH", 65535, 0, 0, len(name)) + name + struct.pack(">H", len(cookie)) + cookie)
    auth.chmod(0o600)
    rd, wr = os.pipe()
    stderr_path = root / "xvfb-stderr.log"
    stderr_stream = stderr_path.open("wb")
    process, connection, lib = None, None, None
    try:
        try:
            process = subprocess.Popen(
                [server, "-displayfd", str(wr), "-screen", "0", "1280x800x24", "-nolisten", "tcp", "-auth", str(auth)],
                pass_fds=(wr,), stdout=subprocess.DEVNULL, stderr=stderr_stream, start_new_session=True,
            )
        finally:
            os.close(wr)
        display = _wait_for_display(process, rd, stderr_path)
        env = dict(os.environ, DISPLAY=display, XAUTHORITY=str(auth))
        env.pop("LD_LIBRARY_PATH", None)
        env.pop("LD_LIBRARY_PATH_ORIG", None)
        lib = ctypes.CDLL(ctypes.util.find_library("X11"))
        lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        lib.XOpenDisplay.restype = ctypes.c_void_p
        lib.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        lib.XDefaultRootWindow.restype = ctypes.c_ulong
        lib.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        lib.XInternAtom.restype = ctypes.c_ulong
        lib.XChangeProperty.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_int,
        ]
        lib.XDeleteProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
        lib.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
        lib.XCloseDisplay.argtypes = [ctypes.c_void_p]
        previous = os.environ.get("XAUTHORITY")
        os.environ["XAUTHORITY"] = str(auth)
        try:
            connection = lib.XOpenDisplay(display.encode())
        finally:
            if previous is None:
                os.environ.pop("XAUTHORITY", None)
            else:
                os.environ["XAUTHORITY"] = previous
        assert connection
        window = lib.XDefaultRootWindow(connection)

        def put(key, values, format=32, type="CARDINAL"):
            atom = lib.XInternAtom(connection, key.encode(), 0)
            if values is None:
                lib.XDeleteProperty(connection, window, atom)
            else:
                data = (
                    (ctypes.c_ulong * len(values))(*values) if format == 32 else (ctypes.c_ubyte * len(values))(*values)
                )
                lib.XChangeProperty(
                    connection,
                    window,
                    atom,
                    lib.XInternAtom(connection, type.encode(), 0),
                    format,
                    0,
                    ctypes.cast(data, ctypes.c_void_p),
                    len(values),
                )
            lib.XSync(connection, 0)

        def run():
            r = subprocess.run(
                [str(exe), "--workarea"], check=False, env=env, capture_output=True, text=True, timeout=3
            )
            assert r.returncode == 0, (r.returncode, r.stderr)
            assert len(r.stdout) < 16384
            return json.loads(r.stdout)

        yield put, run
    finally:
        if connection:
            lib.XCloseDisplay(connection)
        os.close(rd)
        if process is not None:
            if process.poll() is None:
                process.terminate()
            try:
                process.wait(3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(3)
        stderr_stream.close()


@pytest.fixture
def configured(native):
    put, run = native
    put("_NET_WORKAREA", [0, 40, 1280, 760])
    put("_NET_CURRENT_DESKTOP", [0])
    return put, run


def test_actual_xrandr_probe_exits_cleanly_repeatedly(configured):
    _, run = configured
    # Non-null monitor data proves XRRGetMonitors registered its XCloseDisplay
    # callback; closing libXrandr before the display used to crash this path.
    for _ in range(12):
        d = run()
        assert d["source"] == "x11-ewmh" and d["workarea"] == [0, 40, 1280, 760] and d["errors"] == []
        assert d["monitors"] and len(d["monitors"]) >= 1


def test_missing_current_desktop_accepts_identical_areas(configured):
    put, run = configured
    put("_NET_WORKAREA", [0, 40, 1280, 760] * 2)
    put("_NET_CURRENT_DESKTOP", None)
    d = run()
    assert d["workarea"] == [0, 40, 1280, 760] and d["desktop_selection"] == "identical-workareas"


def test_missing_current_desktop_rejects_different_areas(configured):
    put, run = configured
    put("_NET_WORKAREA", [0, 40, 1280, 760, 0, 50, 1280, 750])
    put("_NET_CURRENT_DESKTOP", None)
    assert run()["errors"] == ["ewmh-current-desktop-unavailable"]


@pytest.mark.parametrize(
    "values,format,type,reason",
    [
        ([0, 40, 1280, 760], 8, "CARDINAL", "ewmh-workarea-unavailable-or-invalid"),
        ([0, 40, 1280, 760], 32, "STRING", "ewmh-workarea-unavailable-or-invalid"),
        ([0, 40, 1280, 800], 32, "CARDINAL", "ewmh-workarea-outside-root"),
        ([0, 40, 1280], 32, "CARDINAL", "ewmh-workarea-unavailable-or-invalid"),
    ],
)
def test_invalid_workarea_is_bounded_failure(configured, values, format, type, reason):
    put, run = configured
    put("_NET_WORKAREA", values, format, type)
    d = run()
    assert d["workarea"] is None and d["errors"] == [reason]


def test_invalid_current_desktop_is_rejected(configured):
    put, run = configured
    put("_NET_CURRENT_DESKTOP", [99])
    assert run()["errors"] == ["ewmh-current-desktop-invalid"]


def test_selected_desktop_area_is_used(configured):
    put, run = configured
    put("_NET_WORKAREA", [0, 40, 1280, 760, 0, 50, 1280, 750])
    put("_NET_CURRENT_DESKTOP", [1])
    assert run()["workarea"] == [0, 50, 1280, 750]


@pytest.mark.parametrize("response", [b"71\n", b"not-a-display\n", b""])
def test_startup_requires_actual_valid_displayfd_bytes(tmp_path, response):
    from types import SimpleNamespace

    stderr = tmp_path / "startup.log"
    stderr.write_bytes(b"retained startup diagnostics")
    rd, wr = os.pipe()
    os.write(wr, response)
    os.close(wr)
    try:
        process = SimpleNamespace(poll=lambda: None)
        if response == b"71\n":
            assert _wait_for_display(process, rd, stderr) == ":71"
        else:
            with pytest.raises(AssertionError, match="displayfd"):
                _wait_for_display(process, rd, stderr)
    finally:
        os.close(rd)


def test_failed_server_reports_exit_and_bounded_stderr(tmp_path):
    from types import SimpleNamespace

    stderr = tmp_path / "startup.log"
    stderr.write_bytes(b"omitted-prefix" + b"x" * 20000 + b" loader-failure")
    with pytest.raises(AssertionError, match="exit=127") as failure:
        _wait_for_display(SimpleNamespace(poll=lambda: 127), -1, stderr)
    assert "loader-failure" in str(failure.value) and "omitted-prefix" not in str(failure.value)
    assert len(str(failure.value)) < 16500


def test_unresponsive_server_keeps_readiness_timeout_and_diagnostics(tmp_path):
    from types import SimpleNamespace

    stderr = tmp_path / "startup.log"
    stderr.write_bytes(b"server-still-starting")
    rd, wr = os.pipe()
    try:
        with pytest.raises(AssertionError, match="readiness-timeout.*server-still-starting"):
            _wait_for_display(SimpleNamespace(poll=lambda: None), rd, stderr, timeout=.03)
    finally:
        os.close(rd)
        os.close(wr)
