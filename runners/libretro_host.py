"""Minimal Python libretro host for headless framebuffer capture.

Loads a libretro core (.dll/.so), runs a ROM for N frames, and returns the
final framebuffer as raw BGR555 LE bytes (240x160x2 = 76800 bytes).

Why this exists
---------------
mGBA ships no standalone DLL on Windows. The only redistributable mGBA shared
library is mgba_libretro.dll from the RetroArch buildbot. NanoBoyAdvance is
similar (no headless binary in releases). The libretro API is small enough
that a Python ctypes host is more practical than building a C wrapper.

Design notes
------------
* All callbacks use ``CFUNCTYPE`` (cdecl). ``WINFUNCTYPE`` (stdcall) crashes
  on Windows because libretro cores export cdecl on every platform.
* Every callback object is stored as an instance attribute on
  ``LibretroCore``. If they go out of scope, the C side calls into freed
  memory and segfaults — this is the most common ctypes pitfall.
* Frame counting happens in the ``video_refresh`` callback, NOT by counting
  ``retro_run`` calls. Cores can drop or duplicate frames; only the
  callback fires once per emitted framebuffer.
* BIOS files are passed via ``RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY``.
  We create a temp dir, drop the BIOS in with the canonical filename
  (``gba_bios.bin`` for GBA cores), and return that dir to the core.
  This is verified against mgba_libretro behavior, NOT a GET_VARIABLE hack.
* Pixel format conversion to BGR555 LE happens once per captured frame.
  We prefer 0RGB1555 (lossless), accept XRGB8888 (lossless), warn on
  RGB565 (lossy: 6-bit green truncated to 5-bit).

Public API
----------
* ``LibretroCore``: low-level wrapper for one DLL load + one game.
* ``LibretroSession.run_capture()``: high-level "run a ROM, get a hash".

This module is host-only. Per-core adapters (mgba.py, nanoboyadvance.py)
import LibretroSession and configure DLL path / BIOS / variables.
"""
from __future__ import annotations

import ctypes
import shutil
import sys
import tempfile
from ctypes import (
    CFUNCTYPE,
    POINTER,
    Structure,
    c_bool,
    c_char_p,
    c_double,
    c_float,
    c_int16,
    c_size_t,
    c_uint,
    c_void_p,
)
from pathlib import Path

# ---------------------------------------------------------------------------
# libretro.h constants (only what we actually use)
# ---------------------------------------------------------------------------

RETRO_API_VERSION = 1

# Pixel formats (RETRO_PIXEL_FORMAT_*)
RETRO_PIXEL_FORMAT_0RGB1555 = 0  # native GBA, 16-bit, lossless
RETRO_PIXEL_FORMAT_XRGB8888 = 1  # 32-bit, lossless after >> 3
RETRO_PIXEL_FORMAT_RGB565 = 2    # 16-bit, lossy on green channel

# Environment commands (only the ones we handle)
RETRO_ENVIRONMENT_GET_OVERSCAN = 2
RETRO_ENVIRONMENT_GET_CAN_DUPE = 3
RETRO_ENVIRONMENT_SET_MESSAGE = 6
RETRO_ENVIRONMENT_SHUTDOWN = 7
RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL = 8
RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY = 9
RETRO_ENVIRONMENT_SET_PIXEL_FORMAT = 10
RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS = 11
RETRO_ENVIRONMENT_GET_VARIABLE = 15
RETRO_ENVIRONMENT_SET_VARIABLES = 16
RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE = 17
RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME = 18
RETRO_ENVIRONMENT_GET_LIBRETRO_PATH = 19
RETRO_ENVIRONMENT_GET_LOG_INTERFACE = 27
RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY = 31
RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO = 32
RETRO_ENVIRONMENT_SET_GEOMETRY = 37
RETRO_ENVIRONMENT_GET_INPUT_BITMASKS = 51
RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION = 52
RETRO_ENVIRONMENT_SET_CORE_OPTIONS = 53
RETRO_ENVIRONMENT_SET_CORE_OPTIONS_INTL = 54
RETRO_ENVIRONMENT_GET_PREFERRED_HW_RENDER = 56
RETRO_ENVIRONMENT_GET_AUDIO_VIDEO_ENABLE = 71

# Devices and joypad bits (libretro side)
RETRO_DEVICE_JOYPAD = 1
RETRO_DEVICE_ID_JOYPAD_B = 0
RETRO_DEVICE_ID_JOYPAD_Y = 1
RETRO_DEVICE_ID_JOYPAD_SELECT = 2
RETRO_DEVICE_ID_JOYPAD_START = 3
RETRO_DEVICE_ID_JOYPAD_UP = 4
RETRO_DEVICE_ID_JOYPAD_DOWN = 5
RETRO_DEVICE_ID_JOYPAD_LEFT = 6
RETRO_DEVICE_ID_JOYPAD_RIGHT = 7
RETRO_DEVICE_ID_JOYPAD_A = 8
RETRO_DEVICE_ID_JOYPAD_X = 9
RETRO_DEVICE_ID_JOYPAD_L = 10
RETRO_DEVICE_ID_JOYPAD_R = 11

# Log levels (RETRO_LOG_*)
RETRO_LOG_DEBUG = 0
RETRO_LOG_INFO = 1
RETRO_LOG_WARN = 2
RETRO_LOG_ERROR = 3

# GBA framebuffer geometry (constant for all GBA cores)
GBA_WIDTH = 240
GBA_HEIGHT = 160
GBA_FRAME_BYTES = GBA_WIDTH * GBA_HEIGHT * 2  # BGR555 LE

# ---------------------------------------------------------------------------
# GBA → libretro joypad bit mapping
# ---------------------------------------------------------------------------
# Manifest [[tests.input]].keys uses GBA hardware bit order (REG_KEYINPUT):
#   bit 0 = A, 1 = B, 2 = SELECT, 3 = START, 4 = RIGHT, 5 = LEFT,
#   bit 6 = UP, 7 = DOWN, 8 = R, 9 = L
# libretro joypad uses different IDs (see RETRO_DEVICE_ID_JOYPAD_*).
# This table maps GBA bit index → libretro joypad ID.
_GBA_BIT_TO_RETRO = {
    0: RETRO_DEVICE_ID_JOYPAD_A,
    1: RETRO_DEVICE_ID_JOYPAD_B,
    2: RETRO_DEVICE_ID_JOYPAD_SELECT,
    3: RETRO_DEVICE_ID_JOYPAD_START,
    4: RETRO_DEVICE_ID_JOYPAD_RIGHT,
    5: RETRO_DEVICE_ID_JOYPAD_LEFT,
    6: RETRO_DEVICE_ID_JOYPAD_UP,
    7: RETRO_DEVICE_ID_JOYPAD_DOWN,
    8: RETRO_DEVICE_ID_JOYPAD_R,
    9: RETRO_DEVICE_ID_JOYPAD_L,
}


def gba_keys_to_retro_state(gba_mask: int) -> dict[int, int]:
    """Convert a GBA-style key bitmask into a {libretro_id: pressed} dict."""
    state: dict[int, int] = {rid: 0 for rid in _GBA_BIT_TO_RETRO.values()}
    for bit, rid in _GBA_BIT_TO_RETRO.items():
        if gba_mask & (1 << bit):
            state[rid] = 1
    return state


# ---------------------------------------------------------------------------
# libretro structs (only what we need to read)
# ---------------------------------------------------------------------------

class RetroSystemInfo(Structure):
    _fields_ = [
        ("library_name", c_char_p),
        ("library_version", c_char_p),
        ("valid_extensions", c_char_p),
        ("need_fullpath", c_bool),
        ("block_extract", c_bool),
    ]


class RetroGameGeometry(Structure):
    _fields_ = [
        ("base_width", c_uint),
        ("base_height", c_uint),
        ("max_width", c_uint),
        ("max_height", c_uint),
        ("aspect_ratio", c_float),
    ]


class RetroSystemTiming(Structure):
    _fields_ = [
        ("fps", c_double),
        ("sample_rate", c_double),
    ]


class RetroSystemAVInfo(Structure):
    _fields_ = [
        ("geometry", RetroGameGeometry),
        ("timing", RetroSystemTiming),
    ]


class RetroGameInfo(Structure):
    _fields_ = [
        ("path", c_char_p),
        ("data", c_void_p),
        ("size", c_size_t),
        ("meta", c_char_p),
    ]


class RetroVariable(Structure):
    _fields_ = [
        ("key", c_char_p),
        ("value", c_char_p),
    ]


# Logging callback struct passed via GET_LOG_INTERFACE
RetroLogPrintf = CFUNCTYPE(None, c_uint, c_char_p)


class RetroLogCallback(Structure):
    _fields_ = [("log", RetroLogPrintf)]


# ---------------------------------------------------------------------------
# Callback typedefs
# ---------------------------------------------------------------------------

EnvCb = CFUNCTYPE(c_bool, c_uint, c_void_p)
VideoRefreshCb = CFUNCTYPE(None, c_void_p, c_uint, c_uint, c_size_t)
AudioSampleCb = CFUNCTYPE(None, c_int16, c_int16)
AudioBatchCb = CFUNCTYPE(c_size_t, POINTER(c_int16), c_size_t)
InputPollCb = CFUNCTYPE(None)
InputStateCb = CFUNCTYPE(c_int16, c_uint, c_uint, c_uint, c_uint)


# ---------------------------------------------------------------------------
# Pixel format conversion
# ---------------------------------------------------------------------------

def _pack_bgr555(r5: int, g5: int, b5: int) -> int:
    """Pack 5-bit RGB into a little-endian BGR555 halfword (GBA-native)."""
    return ((b5 & 0x1F) << 10) | ((g5 & 0x1F) << 5) | (r5 & 0x1F)


def convert_to_bgr555(
    raw: bytes,
    width: int,
    height: int,
    pitch: int,
    pixel_format: int,
) -> bytes:
    """Convert one libretro framebuffer to raw BGR555 LE (240x160x2)."""
    if width != GBA_WIDTH or height != GBA_HEIGHT:
        raise ValueError(
            f"unexpected geometry {width}x{height}, expected "
            f"{GBA_WIDTH}x{GBA_HEIGHT}"
        )

    out = bytearray(GBA_FRAME_BYTES)

    if pixel_format == RETRO_PIXEL_FORMAT_0RGB1555:
        # libretro 0RGB1555 layout (native byte order, 16-bit):
        #   bits 0-4: B, 5-9: G, 10-14: R, bit 15: 0
        # GBA BGR555 layout (LE):
        #   bits 0-4: R, 5-9: G, 10-14: B
        # We swap R and B channels.
        for y in range(GBA_HEIGHT):
            row = raw[y * pitch : y * pitch + GBA_WIDTH * 2]
            for x in range(GBA_WIDTH):
                px = row[x * 2] | (row[x * 2 + 1] << 8)
                b5 = px & 0x1F
                g5 = (px >> 5) & 0x1F
                r5 = (px >> 10) & 0x1F
                bgr = _pack_bgr555(r5, g5, b5)
                idx = (y * GBA_WIDTH + x) * 2
                out[idx] = bgr & 0xFF
                out[idx + 1] = (bgr >> 8) & 0xFF
        return bytes(out)

    if pixel_format == RETRO_PIXEL_FORMAT_XRGB8888:
        # 32-bit native: 0xAARRGGBB on little-endian (data bytes: B G R A)
        for y in range(GBA_HEIGHT):
            row = raw[y * pitch : y * pitch + GBA_WIDTH * 4]
            for x in range(GBA_WIDTH):
                b8 = row[x * 4]
                g8 = row[x * 4 + 1]
                r8 = row[x * 4 + 2]
                # Drop low 3 bits: 8-bit → 5-bit (lossless top 5)
                bgr = _pack_bgr555(r8 >> 3, g8 >> 3, b8 >> 3)
                idx = (y * GBA_WIDTH + x) * 2
                out[idx] = bgr & 0xFF
                out[idx + 1] = (bgr >> 8) & 0xFF
        return bytes(out)

    if pixel_format == RETRO_PIXEL_FORMAT_RGB565:
        # 16-bit RRRRRGGGGGGBBBBB. Green is 6-bit; we drop the LSB → lossy.
        for y in range(GBA_HEIGHT):
            row = raw[y * pitch : y * pitch + GBA_WIDTH * 2]
            for x in range(GBA_WIDTH):
                px = row[x * 2] | (row[x * 2 + 1] << 8)
                r5 = (px >> 11) & 0x1F
                g6 = (px >> 5) & 0x3F
                b5 = px & 0x1F
                bgr = _pack_bgr555(r5, g6 >> 1, b5)
                idx = (y * GBA_WIDTH + x) * 2
                out[idx] = bgr & 0xFF
                out[idx + 1] = (bgr >> 8) & 0xFF
        return bytes(out)

    raise ValueError(f"unsupported pixel format {pixel_format}")


# ---------------------------------------------------------------------------
# Logging plumbing
# ---------------------------------------------------------------------------

def _stderr_log(level: int, msg: bytes) -> None:
    name = {0: "DEBUG", 1: "INFO", 2: "WARN", 3: "ERROR"}.get(level, "?")
    try:
        text = msg.decode("utf-8", errors="replace").rstrip()
    except Exception:
        text = repr(msg)
    if level >= RETRO_LOG_WARN:
        print(f"[libretro {name}] {text}", file=sys.stderr)


# ---------------------------------------------------------------------------
# LibretroCore — low-level wrapper for one DLL load
# ---------------------------------------------------------------------------

class LibretroError(RuntimeError):
    pass


class LibretroCore:
    """Loads a libretro core, manages callbacks, runs frames.

    One instance == one DLL load + (optionally) one loaded game. Re-loading
    a different game is supported but the typical flow is one core per test.
    """

    def __init__(
        self,
        dll_path: Path,
        *,
        system_dir: Path | None = None,
        save_dir: Path | None = None,
        variables: dict[str, str] | None = None,
        verbose: bool = False,
    ) -> None:
        self.dll_path = Path(dll_path)
        if not self.dll_path.exists():
            raise LibretroError(f"libretro core not found: {dll_path}")

        self._verbose = verbose
        self._system_dir = (system_dir or Path(tempfile.mkdtemp(prefix="lr_sys_")))
        self._save_dir = (save_dir or Path(tempfile.mkdtemp(prefix="lr_save_")))
        self._variables = dict(variables or {})

        # Encoded as bytes once and held forever — c_char_p stores a pointer
        # into our Python bytes object, so the bytes must outlive the core.
        self._sys_dir_bytes = str(self._system_dir).encode("utf-8")
        self._save_dir_bytes = str(self._save_dir).encode("utf-8")
        self._libretro_path_bytes = str(self.dll_path).encode("utf-8")
        self._var_bytes_cache: dict[str, bytes] = {
            k: v.encode("utf-8") for k, v in self._variables.items()
        }

        # Pixel format negotiation: default to 0RGB1555 (GBA-native).
        self.pixel_format = RETRO_PIXEL_FORMAT_0RGB1555

        # Frame capture state
        self._last_frame: bytes | None = None  # raw libretro pixels
        self._last_w = 0
        self._last_h = 0
        self._last_pitch = 0
        self._frame_count = 0  # frames emitted since load_game

        # Input state: read on each input_state callback. Caller updates
        # via set_joypad_state() before retro_run().
        self._joypad_state: dict[int, int] = {}

        # Logging callback storage (must outlive core).
        # Untyped because CFUNCTYPE instances are not valid type-form.
        self._log_cb_struct = None
        self._log_printf_cb = None

        # Load DLL
        self._dll = ctypes.CDLL(str(self.dll_path))
        self._bind_functions()

        # Build and store callbacks (never let them GC)
        self._cb_env = EnvCb(self._on_environment)
        self._cb_video = VideoRefreshCb(self._on_video_refresh)
        self._cb_audio_sample = AudioSampleCb(self._on_audio_sample)
        self._cb_audio_batch = AudioBatchCb(self._on_audio_batch)
        self._cb_input_poll = InputPollCb(self._on_input_poll)
        self._cb_input_state = InputStateCb(self._on_input_state)

        # API version sanity
        api = self._dll.retro_api_version()
        if api != RETRO_API_VERSION:
            raise LibretroError(f"libretro API {api}, expected {RETRO_API_VERSION}")

        # Wire callbacks BEFORE retro_init — environment may be called
        # early to negotiate pixel format and core options.
        self._dll.retro_set_environment(self._cb_env)
        self._dll.retro_set_video_refresh(self._cb_video)
        self._dll.retro_set_audio_sample(self._cb_audio_sample)
        self._dll.retro_set_audio_sample_batch(self._cb_audio_batch)
        self._dll.retro_set_input_poll(self._cb_input_poll)
        self._dll.retro_set_input_state(self._cb_input_state)

        self._dll.retro_init()
        self._initialized = True
        self._game_loaded = False

    # ---- function binding ------------------------------------------------

    def _bind_functions(self) -> None:
        d = self._dll
        d.retro_api_version.restype = c_uint
        d.retro_api_version.argtypes = []

        d.retro_init.restype = None
        d.retro_init.argtypes = []
        d.retro_deinit.restype = None
        d.retro_deinit.argtypes = []

        d.retro_get_system_info.restype = None
        d.retro_get_system_info.argtypes = [POINTER(RetroSystemInfo)]
        d.retro_get_system_av_info.restype = None
        d.retro_get_system_av_info.argtypes = [POINTER(RetroSystemAVInfo)]

        d.retro_set_environment.restype = None
        d.retro_set_environment.argtypes = [EnvCb]
        d.retro_set_video_refresh.restype = None
        d.retro_set_video_refresh.argtypes = [VideoRefreshCb]
        d.retro_set_audio_sample.restype = None
        d.retro_set_audio_sample.argtypes = [AudioSampleCb]
        d.retro_set_audio_sample_batch.restype = None
        d.retro_set_audio_sample_batch.argtypes = [AudioBatchCb]
        d.retro_set_input_poll.restype = None
        d.retro_set_input_poll.argtypes = [InputPollCb]
        d.retro_set_input_state.restype = None
        d.retro_set_input_state.argtypes = [InputStateCb]

        d.retro_load_game.restype = c_bool
        d.retro_load_game.argtypes = [POINTER(RetroGameInfo)]
        d.retro_unload_game.restype = None
        d.retro_unload_game.argtypes = []

        d.retro_run.restype = None
        d.retro_run.argtypes = []
        d.retro_reset.restype = None
        d.retro_reset.argtypes = []

    # ---- callbacks -------------------------------------------------------

    def _on_environment(self, cmd: int, data_ptr) -> bool:
        """Handle libretro environment requests.

        Returning False tells the core "not supported" and is the safe
        default for anything we don't recognize. We only return True for
        commands we actually fulfill.
        """
        if cmd == RETRO_ENVIRONMENT_GET_SYSTEM_DIRECTORY:
            # data is char**: write our system dir pointer through it.
            ptr = ctypes.cast(data_ptr, POINTER(c_char_p))
            ptr[0] = ctypes.c_char_p(self._sys_dir_bytes)
            return True

        if cmd == RETRO_ENVIRONMENT_GET_SAVE_DIRECTORY:
            ptr = ctypes.cast(data_ptr, POINTER(c_char_p))
            ptr[0] = ctypes.c_char_p(self._save_dir_bytes)
            return True

        if cmd == RETRO_ENVIRONMENT_GET_LIBRETRO_PATH:
            ptr = ctypes.cast(data_ptr, POINTER(c_char_p))
            ptr[0] = ctypes.c_char_p(self._libretro_path_bytes)
            return True

        if cmd == RETRO_ENVIRONMENT_SET_PIXEL_FORMAT:
            # data is unsigned*
            ptr = ctypes.cast(data_ptr, POINTER(c_uint))
            requested = ptr[0]
            if requested in (
                RETRO_PIXEL_FORMAT_0RGB1555,
                RETRO_PIXEL_FORMAT_XRGB8888,
                RETRO_PIXEL_FORMAT_RGB565,
            ):
                self.pixel_format = requested
                if self._verbose:
                    fmt_name = {
                        0: "0RGB1555",
                        1: "XRGB8888",
                        2: "RGB565",
                    }[requested]
                    print(f"[libretro] core requested pixel format {fmt_name}",
                          file=sys.stderr)
                if requested == RETRO_PIXEL_FORMAT_RGB565:
                    print(
                        "[libretro WARN] core uses RGB565 — green channel "
                        "will be lossy after BGR555 conversion",
                        file=sys.stderr,
                    )
                return True
            return False

        if cmd == RETRO_ENVIRONMENT_GET_VARIABLE:
            ptr = ctypes.cast(data_ptr, POINTER(RetroVariable))
            var = ptr[0]
            if var.key is None:
                return False
            key = var.key.decode("utf-8", errors="replace")
            val = self._var_bytes_cache.get(key)
            if val is None:
                # Variable not set — let core use its default
                var.value = c_char_p(None)
                return False
            var.value = c_char_p(val)
            return True

        if cmd == RETRO_ENVIRONMENT_GET_VARIABLE_UPDATE:
            # bool*: report no pending update
            ptr = ctypes.cast(data_ptr, POINTER(c_bool))
            ptr[0] = False
            return True

        if cmd == RETRO_ENVIRONMENT_SET_VARIABLES:
            # Core declares its options. We don't need to do anything;
            # GET_VARIABLE handles the lookup. Returning True lets the core
            # know we accepted the declaration.
            return True

        if cmd == RETRO_ENVIRONMENT_SET_CORE_OPTIONS:
            return True
        if cmd == RETRO_ENVIRONMENT_SET_CORE_OPTIONS_INTL:
            return True
        if cmd == RETRO_ENVIRONMENT_GET_CORE_OPTIONS_VERSION:
            ptr = ctypes.cast(data_ptr, POINTER(c_uint))
            ptr[0] = 1
            return True

        if cmd == RETRO_ENVIRONMENT_GET_LOG_INTERFACE:
            # Provide a logging callback so the core can report errors.
            if self._log_printf_cb is None:
                self._log_printf_cb = RetroLogPrintf(_stderr_log)
                self._log_cb_struct = RetroLogCallback(self._log_printf_cb)
            ptr = ctypes.cast(data_ptr, POINTER(RetroLogCallback))
            ptr[0] = self._log_cb_struct  # type: ignore[assignment]
            return True

        if cmd == RETRO_ENVIRONMENT_GET_CAN_DUPE:
            ptr = ctypes.cast(data_ptr, POINTER(c_bool))
            ptr[0] = True
            return True

        if cmd == RETRO_ENVIRONMENT_GET_OVERSCAN:
            ptr = ctypes.cast(data_ptr, POINTER(c_bool))
            ptr[0] = False
            return True

        if cmd == RETRO_ENVIRONMENT_GET_INPUT_BITMASKS:
            # We don't implement bitmask polling — return false so the core
            # falls back to per-button input_state queries.
            return False

        if cmd == RETRO_ENVIRONMENT_GET_PREFERRED_HW_RENDER:
            return False

        if cmd == RETRO_ENVIRONMENT_GET_AUDIO_VIDEO_ENABLE:
            # Tell the core: video=on, audio=off (we don't capture audio).
            ptr = ctypes.cast(data_ptr, POINTER(c_int16))
            ptr[0] = 0b01  # bit0 = video enabled
            return True

        if cmd == RETRO_ENVIRONMENT_SET_PERFORMANCE_LEVEL:
            return True

        if cmd == RETRO_ENVIRONMENT_SET_INPUT_DESCRIPTORS:
            return True

        if cmd == RETRO_ENVIRONMENT_SET_SYSTEM_AV_INFO:
            return True
        if cmd == RETRO_ENVIRONMENT_SET_GEOMETRY:
            return True
        if cmd == RETRO_ENVIRONMENT_SET_SUPPORT_NO_GAME:
            return True
        if cmd == RETRO_ENVIRONMENT_SET_MESSAGE:
            return True
        if cmd == RETRO_ENVIRONMENT_SHUTDOWN:
            return True

        # Unhandled — be quiet unless verbose, return false.
        if self._verbose:
            print(f"[libretro] unhandled env cmd {cmd}", file=sys.stderr)
        return False

    def _on_video_refresh(self, data_ptr, width: int, height: int, pitch: int) -> None:
        # NULL data means "frame duped" — bump frame count, keep prior frame.
        self._frame_count += 1
        if not data_ptr:
            return
        if width == 0 or height == 0:
            return
        # Read the pixel rows. We need pitch * height bytes total.
        nbytes = pitch * height
        try:
            buf = (ctypes.c_ubyte * nbytes).from_address(data_ptr)
            self._last_frame = bytes(buf)
            self._last_w = width
            self._last_h = height
            self._last_pitch = pitch
        except Exception as e:
            print(f"[libretro WARN] video_refresh read failed: {e}", file=sys.stderr)

    def _on_audio_sample(self, left: int, right: int) -> None:
        pass  # we don't capture audio

    def _on_audio_batch(self, data_ptr, frames: int) -> int:
        return frames  # accept and discard

    def _on_input_poll(self) -> None:
        pass  # state is set by caller before retro_run

    def _on_input_state(self, port: int, device: int, index: int, id_: int) -> int:
        if port != 0 or device != RETRO_DEVICE_JOYPAD:
            return 0
        return self._joypad_state.get(id_, 0)

    # ---- public API ------------------------------------------------------

    def get_system_info(self) -> tuple[str, str]:
        info = RetroSystemInfo()
        self._dll.retro_get_system_info(ctypes.byref(info))
        name = (info.library_name or b"").decode("utf-8", errors="replace")
        ver = (info.library_version or b"").decode("utf-8", errors="replace")
        return name, ver

    def load_game(self, rom_path: Path) -> None:
        rom_path = Path(rom_path)
        if not rom_path.exists():
            raise LibretroError(f"ROM not found: {rom_path}")

        # mgba_libretro and most cores accept either need_fullpath=True
        # (path only) or need_fullpath=False (data buffer). We pass both —
        # the core uses whichever it prefers.
        rom_bytes = rom_path.read_bytes()
        path_bytes = str(rom_path).encode("utf-8")

        # Hold buffers alive on self
        self._rom_path_bytes = path_bytes
        self._rom_data_buf = (ctypes.c_ubyte * len(rom_bytes)).from_buffer_copy(rom_bytes)

        info = RetroGameInfo()
        info.path = c_char_p(self._rom_path_bytes)
        info.data = ctypes.cast(self._rom_data_buf, c_void_p)
        info.size = len(rom_bytes)
        info.meta = c_char_p(None)

        ok = self._dll.retro_load_game(ctypes.byref(info))
        if not ok:
            raise LibretroError(f"retro_load_game failed for {rom_path}")
        self._game_loaded = True
        self._frame_count = 0
        self._last_frame = None

    def set_joypad_state(self, gba_mask: int) -> None:
        """Set the joypad state for the next retro_run call.

        gba_mask uses GBA REG_KEYINPUT bit order. 0 = no keys held.
        """
        self._joypad_state = gba_keys_to_retro_state(gba_mask)

    def run_one(self) -> None:
        """Advance the core by one retro_run call (typically one frame)."""
        self._dll.retro_run()

    def get_frame_count(self) -> int:
        return self._frame_count

    def get_last_frame_bgr555(self) -> bytes | None:
        if self._last_frame is None:
            return None
        return convert_to_bgr555(
            self._last_frame,
            self._last_w,
            self._last_h,
            self._last_pitch,
            self.pixel_format,
        )

    def close(self) -> None:
        if not getattr(self, "_initialized", False):
            return
        try:
            if self._game_loaded:
                self._dll.retro_unload_game()
        except Exception:
            pass
        try:
            self._dll.retro_deinit()
        except Exception:
            pass
        self._initialized = False
        self._game_loaded = False

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# LibretroSession — high-level "run a ROM, get a frame" helper
# ---------------------------------------------------------------------------

class LibretroSession:
    """High-level helper used by per-core adapters (mgba.py, etc.).

    Handles BIOS staging into the system directory, input scheduling from
    a manifest [[tests.input]] list, and frame-target loop.
    """

    def __init__(
        self,
        dll_path: Path,
        *,
        bios_path: Path | None = None,
        bios_filename: str = "gba_bios.bin",
        variables: dict[str, str] | None = None,
        verbose: bool = False,
    ) -> None:
        self.dll_path = Path(dll_path)
        self._bios_path = Path(bios_path) if bios_path else None
        self._bios_filename = bios_filename
        self._variables = dict(variables or {})
        self._verbose = verbose

        # Stage BIOS into a temp system dir
        self._sys_dir = Path(tempfile.mkdtemp(prefix="lr_sys_"))
        if self._bios_path is not None and self._bios_path.exists():
            shutil.copyfile(self._bios_path, self._sys_dir / self._bios_filename)
        elif self._bios_path is not None and self._verbose:
            print(
                f"[libretro WARN] bios path {self._bios_path} does not exist; "
                f"core will boot without BIOS",
                file=sys.stderr,
            )

    def run_capture(
        self,
        rom_path: Path,
        target_frames: int,
        *,
        inputs: list[dict] | None = None,
        max_run_calls: int | None = None,
        completion: dict | None = None,
    ) -> bytes:
        """Run ROM until completion criterion is met or target_frames hits.

        Returns raw BGR555 LE bytes (76800).

        `inputs` is the manifest [[tests.input]] list — each entry
        {"frame": int, "keys": int (GBA mask)}. The mask becomes "held"
        from that frame onward until a later entry overrides it.

        `completion` mirrors cable_club's completion modes. Supported here:
            - {"type": "exact_frame", "frame": N}
                Capture exactly at frame N (defaults to target_frames).
            - {"type": "stable_frames", "window": W, "min_frames": F}
                Hash the framebuffer each frame; capture once the hash has
                been identical for W consecutive frames after frame F.
            - {"type": "input_then_stable", "window": W, "min_frames": F}
                Same as stable_frames but min_frames is bumped past the last
                input event in the schedule.
        Anything else (None, debug_string) falls back to "run target_frames
        and capture the final frame".
        """
        import hashlib

        schedule: list[tuple[int, int]] = []
        if inputs:
            schedule = sorted(
                [(int(i["frame"]), int(i["keys"])) for i in inputs],
                key=lambda kv: kv[0],
            )

        comp_type = (completion or {}).get("type")
        comp_window = int((completion or {}).get("window", 10) or 10)
        comp_min_frames = int((completion or {}).get("min_frames", 0) or 0)
        if comp_type == "input_then_stable" and schedule:
            comp_min_frames = max(comp_min_frames, schedule[-1][0] + 1)
        comp_exact_frame = None
        if comp_type == "exact_frame":
            comp_exact_frame = int((completion or {}).get("frame", target_frames))

        cap = max_run_calls if max_run_calls is not None else target_frames * 5

        core = LibretroCore(
            self.dll_path,
            system_dir=self._sys_dir,
            variables=self._variables,
            verbose=self._verbose,
        )
        try:
            core.load_game(rom_path)
            current_mask = 0
            sched_idx = 0
            run_calls = 0
            prev_hash = b""
            stable_count = 0
            captured: bytes | None = None
            while core.get_frame_count() < target_frames:
                if run_calls >= cap:
                    raise LibretroError(
                        f"libretro core failed to emit {target_frames} frames "
                        f"after {cap} retro_run calls"
                    )
                cur_frame = core.get_frame_count()
                while sched_idx < len(schedule) and schedule[sched_idx][0] <= cur_frame:
                    current_mask = schedule[sched_idx][1]
                    sched_idx += 1
                core.set_joypad_state(current_mask)
                core.run_one()
                run_calls += 1

                if comp_exact_frame is not None and core.get_frame_count() >= comp_exact_frame:
                    captured = core.get_last_frame_bgr555()
                    break

                if comp_type in ("stable_frames", "input_then_stable"):
                    if core.get_frame_count() < comp_min_frames:
                        continue
                    fb = core.get_last_frame_bgr555()
                    if fb is None:
                        continue
                    h = hashlib.sha256(fb).digest()
                    if h == prev_hash:
                        stable_count += 1
                        if stable_count >= comp_window:
                            captured = fb
                            break
                    else:
                        stable_count = 0
                        prev_hash = h

            if captured is None:
                captured = core.get_last_frame_bgr555()
            if captured is None:
                raise LibretroError("core emitted no framebuffer")
            if len(captured) != GBA_FRAME_BYTES:
                raise LibretroError(
                    f"unexpected frame size {len(captured)}, expected {GBA_FRAME_BYTES}"
                )
            return captured
        finally:
            core.close()

    def cleanup(self) -> None:
        try:
            shutil.rmtree(self._sys_dir, ignore_errors=True)
        except Exception:
            pass

    def __del__(self) -> None:
        self.cleanup()


# ---------------------------------------------------------------------------
# CLI smoke test
# ---------------------------------------------------------------------------

def _cli() -> int:
    import argparse
    p = argparse.ArgumentParser(description="libretro_host smoke test")
    p.add_argument("--core", required=True, help="path to libretro .dll/.so")
    p.add_argument("--rom", required=True, help="path to ROM")
    p.add_argument("--frames", type=int, default=60)
    p.add_argument("--bios", help="path to GBA BIOS (optional)")
    p.add_argument("--out", required=True, help="output path for raw BGR555 .bin")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args()

    sess = LibretroSession(
        Path(args.core),
        bios_path=Path(args.bios) if args.bios else None,
        verbose=args.verbose,
    )
    raw = sess.run_capture(Path(args.rom), args.frames)
    Path(args.out).write_bytes(raw)
    print(f"wrote {len(raw)} bytes to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
