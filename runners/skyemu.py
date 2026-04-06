"""SkyEmu runner adapter (HTTP server mode).

SkyEmu ships an HTTP server mode that serves screenshots and accepts
input via REST endpoints — no compilation, no library binding, no GUI.

    SkyEmu.exe http_server <port> <rom>
    GET /step?frames=N        — advance the emulator
    GET /input?A=1&B=0&...    — set joypad state
    GET /screen               — return PNG of current frame

This adapter is "tier 2" reference quality: SkyEmu is not cycle-accurate
in the way mgba_libretro / Cable Club / NanoBoyAdvance are. Reference
hashes captured here should be tagged accordingly so they don't drown
out tier-1 emulator agreement.

Discovery:
    1. SKYEMU_PATH environment variable
    2. SkyEmu in PATH (shutil.which)
    3. Common Windows install paths

This adapter has been written but not yet end-to-end tested — drop a
SkyEmu binary at one of the discovery paths to enable it.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

# GBA REG_KEYINPUT bit -> SkyEmu HTTP query param name.
_GBA_BIT_TO_SKYEMU_PARAM = {
    0: "A",
    1: "B",
    2: "Select",
    3: "Start",
    4: "Right",
    5: "Left",
    6: "Up",
    7: "Down",
    8: "R",
    9: "L",
}

_COMMON_PATHS = [
    Path(r"C:/tools/SkyEmu/SkyEmu.exe"),
    Path(r"C:/Program Files/SkyEmu/SkyEmu.exe"),
    Path(os.path.expandvars(r"%LOCALAPPDATA%/SkyEmu/SkyEmu.exe")),
]


def _find_skyemu() -> str | None:
    env = os.environ.get("SKYEMU_PATH")
    if env and Path(env).exists():
        return env
    found = shutil.which("SkyEmu")
    if found:
        return found
    for p in _COMMON_PATHS:
        if p.exists():
            return str(p)
    return None


def _free_port() -> int:
    """Pick an ephemeral TCP port the OS won't immediately re-use."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_ready(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/screen", timeout=1.0
            ) as resp:
                if resp.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    return False


def _http_get(port: int, path: str, timeout: float = 120.0) -> bytes:
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def _gba_mask_to_query(mask: int) -> str:
    parts = []
    for bit, name in _GBA_BIT_TO_SKYEMU_PARAM.items():
        parts.append(f"{name}={1 if mask & (1 << bit) else 0}")
    return "&".join(parts)


def _png_bytes_to_bgr555(png_bytes: bytes) -> bytes:
    """Reuse compare.py's PNG converter against an in-memory PNG."""
    # Local import to avoid pulling Pillow at module load if SkyEmu isn't used.
    from PIL import Image

    img = Image.open(BytesIO(png_bytes)).convert("RGB")
    if img.size != (240, 160):
        # Some SkyEmu builds emit at 2x. Resize down (nearest, no smoothing).
        img = img.resize((240, 160), Image.Resampling.NEAREST)
    pixels = img.load()
    out = bytearray(240 * 160 * 2)
    for y in range(160):
        for x in range(240):
            r8, g8, b8 = pixels[x, y]
            r5 = (r8 >> 3) & 0x1F
            g5 = (g8 >> 3) & 0x1F
            b5 = (b8 >> 3) & 0x1F
            u16 = r5 | (g5 << 5) | (b5 << 10)
            idx = (y * 240 + x) * 2
            out[idx] = u16 & 0xFF
            out[idx + 1] = (u16 >> 8) & 0xFF
    return bytes(out)


class SkyEmuRunner:
    name = "skyemu"

    def __init__(self) -> None:
        self._exe = _find_skyemu()

    def is_available(self) -> bool:
        return self._exe is not None

    def run_test(
        self,
        rom_path: Path,
        frames: int,
        output_path: Path,
        *,
        inputs: list[dict] | None = None,
        completion: dict | None = None,
        bios_mode: str = "official",
    ) -> bool:
        del completion  # not used
        if self._exe is None:
            return False
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # SkyEmu BIOS behavior:
        #   - "official": copy the real Nintendo BIOS next to the ROM as
        #     gba_bios.bin. SkyEmu loads it via its standard path.
        #   - "cleanroom" / "hle": SkyEmu's internal fallback BIOS IS
        #     already the Cult-of-GBA replacement BIOS, so we ensure NO
        #     sibling gba_bios.bin exists and let SkyEmu use it. These
        #     two modes produce identical SkyEmu output by design (and
        #     we document that; the divergence show up on the other
        #     runners where HLE != cleanroom).
        #   Note: SkyEmu validates any external BIOS file against the
        #   canonical Nintendo hash and rejects non-matching blobs, so
        #   we cannot "force" cleanroom by dropping the Cult-of-GBA
        #   file next to the ROM — that triggers SkyEmu's reject path
        #   and produces an error screen for every test. Using the
        #   internal fallback is the correct answer.
        rom_dir = rom_path.parent
        sibling_bios = rom_dir / "gba_bios.bin"
        stash_path = rom_dir / "gba_bios.bin.skyemu-stash"
        if sibling_bios.exists():
            sibling_bios.rename(stash_path)
        try:
            if bios_mode == "official":
                real = os.environ.get("MGBA_BIOS_PATH") or os.environ.get("NBA_BIOS_PATH")
                if real and Path(real).exists():
                    sibling_bios.write_bytes(Path(real).read_bytes())
            # "cleanroom" / "hle": sibling_bios stays absent.
        except OSError:
            pass

        port = _free_port()
        proc = subprocess.Popen(
            [self._exe, "http_server", str(port), str(rom_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

        try:
            if not _wait_ready(port, timeout=10.0):
                print("[skyemu runner] HTTP server did not become ready",
                      file=sys.stderr)
                return False

            schedule = sorted(
                [(int(i["frame"]), int(i["keys"])) for i in (inputs or [])],
                key=lambda kv: kv[0],
            )

            current_mask = 0
            sched_idx = 0
            current_frame = 0
            try:
                # Step in small chunks (1 frame at a time when input changes,
                # bigger chunks otherwise) so we can apply the input schedule.
                while current_frame < frames:
                    # Apply any pending input change.
                    while sched_idx < len(schedule) and schedule[sched_idx][0] <= current_frame:
                        current_mask = schedule[sched_idx][1]
                        sched_idx += 1
                        _http_get(port, "/input?" + _gba_mask_to_query(current_mask))
                    # Step until next scheduled change or target. Cap each
                    # /step call at 1000 frames so long tests (e.g. fuzzarm
                    # 30000f) don't blow past a single-request HTTP timeout.
                    if sched_idx < len(schedule):
                        next_change = schedule[sched_idx][0]
                        chunk = max(1, min(frames, next_change) - current_frame)
                    else:
                        chunk = frames - current_frame
                    chunk = min(chunk, 1000)
                    _http_get(port, f"/step?frames={chunk}", timeout=180.0)
                    current_frame += chunk

                png_bytes = _http_get(port, "/screen")
            except (urllib.error.URLError, OSError) as e:
                print(f"[skyemu runner] HTTP error: {e}", file=sys.stderr)
                return False

            try:
                raw = _png_bytes_to_bgr555(png_bytes)
                output_path.write_bytes(raw)
            except Exception as e:
                print(f"[skyemu runner] decode/write failed: {e}", file=sys.stderr)
                return False

            return True
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
            except Exception:
                pass
            # Restore the original ROM-sibling BIOS file (if any) so
            # repeat runs don't inherit the bios_mode we just used.
            try:
                if sibling_bios.exists():
                    sibling_bios.unlink()
                if stash_path.exists():
                    stash_path.rename(sibling_bios)
            except OSError:
                pass


RUNNER = SkyEmuRunner()
