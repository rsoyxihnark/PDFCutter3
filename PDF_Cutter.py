import os
import queue
import base64
import struct
import threading
import zlib
import ctypes
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Generator, Literal, TypedDict
from ctypes import wintypes
from contextlib import contextmanager, suppress
import tkinter as tk
from tkinter import filedialog, messagebox
import ttkbootstrap as tb
from pypdf import PageObject, PdfReader, PdfWriter, PasswordType
from pypdf.generic import ArrayObject, Destination, DictionaryObject, IndirectObject, NameObject

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False


# Valuable-Run-Lesson: a PDF with about 100,000 links froze the program while pypdf resolved them, which is why link resolution is skipped here.
if hasattr(PdfWriter, "_resolve_links"):
    def _skip_link_resolution(self) -> None:
        with suppress(AttributeError):
            self._unresolved_links.clear()

    PdfWriter._resolve_links = _skip_link_resolution

APP_VERSION = "1.4.0"

USER_PINNED_BROWSE_DIR_DO_NOT_CHANGE = r"D:\Clementine\Desktop\TEST"

COLOR_SUCCESS = "#50fa7b"
COLOR_ERROR = "#ff5555"
COLOR_DEFAULT_FG = "grey"
ICON_VALID = "✅"
ICON_INVALID = "❌"
MONITOR_DEFAULTTONEAREST = 2

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_CAPTION_COLOR = 35
TITLE_BAR_COLORREF = 0x00222222
FADE_IN_STEPS = 10
FADE_IN_STEP_MS = 15

APP_ICON_SIZES = (48, 32, 16)
APP_ICON_SUPERSAMPLE = 4
APP_ICON_GRADIENT = ((0x00, 0xBC, 0x8C), (0x34, 0x98, 0xDB))
APP_ICON_PAGE = (0xF8, 0xF9, 0xFA)
APP_ICON_FOLD = (0xBE, 0xC8, 0xD0)
APP_ICON_TEXT = (0x96, 0xA0, 0xAA)
APP_ICON_CUT = (0xFF, 0xFF, 0xFF)
APP_ICON_CUT_Y = 0.53
APP_ICON_TEXT_LINES = ((0.25, 0.50), (0.35, 0.62), (0.43, 0.62), (0.63, 0.62), (0.71, 0.62), (0.79, 0.52))

POLL_INTERVAL_MS = 80
PROGRESS_BAR_LENGTH = 160
MAX_UNIQUE_PATH_ATTEMPTS = 100

OP_EXTRACT = "extract"
OP_SPLIT = "split_every"

STATUS_READY = "Ready"
STATUS_WORKING = "Working…"
STATUS_CANCELLING = "Cancelling…"
STATUS_CANCELLED = "Cancelled"

STATUS_OPENING_PDF = "Opening PDF…"
STATUS_COLLECTING_PAGES = "Collecting {count} page(s)…"
STATUS_WRITING_PARTS = "Writing {count} {unit}…"
STATUS_WRITING_OUTPUT = "Writing output file…"

MSG_NO_FILE_LOADED = "No file loaded"
MSG_ENCRYPTED_NEED_PASSWORD = "Encrypted PDF (enter password to read)"
MSG_ENCRYPTED_WRONG_PASSWORD = "Encrypted PDF: wrong or missing password."
MSG_DROP_TO_LOAD = "Release to load this PDF"
MSG_DROP_HINT = "Drop a PDF anywhere in this window to load it"

REFRESH_DEBOUNCE_MS = 400
COLLECT_FRACTION = 0.4
PROGRESS_STEP = 0.5
SKIPPED_ANNOTATION_KEYS = ("/Parent", "/StructParents")


class JobDict(TypedDict):
    input_path: str
    output_dir: str
    password: str
    base_name: str
    operation: str
    page_indices: list[int]
    chunk_size: int
    open_folder: bool


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]

_INVALID_FILENAME_CHARS = str.maketrans({c: "_" for c in '<>:"/\\|?*' + "".join(map(chr, range(32)))})

def sanitize_filename_component(name: str) -> str:
    return name.strip().translate(_INVALID_FILENAME_CHARS).strip(".") or "output"


def file_stamp(path: str) -> tuple[int, int]:
    with suppress(OSError):
        info = os.stat(path)
        return info.st_mtime_ns, info.st_size
    return (0, 0)


def make_unique_path(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return path

    stem, suffix = p.stem, p.suffix
    parent = p.parent
    for i in range(1, MAX_UNIQUE_PATH_ATTEMPTS + 1):
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return str(candidate)
    raise RuntimeError(f"Could not find unique path after {MAX_UNIQUE_PATH_ATTEMPTS} attempts.")


def parse_page_ranges(spec: str, max_pages: int) -> list[int]:
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("Page range is empty.")

    def parse_token(token: str, context: str) -> int:
        token = token.strip()
        if not token:
            raise ValueError(f"Missing page number in '{context}'.")
        if not token.isdecimal():
            raise ValueError(f"Invalid page number '{token}'.")
        value = int(token)
        if value < 1:
            raise ValueError("Page numbers start at 1.")
        return value

    pages: set[int] = set()
    for part in (p.strip() for p in spec.split(",")):
        if not part:
            continue
        if "-" in part:
            pieces = part.split("-")
            if len(pieces) != 2:
                raise ValueError(f"Invalid range '{part}'.")
            start = parse_token(pieces[0], part)
            end = parse_token(pieces[1], part)
            if start > end:
                raise ValueError(f"Invalid range '{part}' (start > end).")
        else:
            start = end = parse_token(part, part)
        if end > max_pages:
            raise ValueError(f"Page {end} is out of range (1-{max_pages}).")
        pages.update(range(start - 1, end))

    if not pages:
        raise ValueError("No pages selected.")
    return sorted(pages)


def parse_chunk_size(spec: str) -> int:
    spec = (spec or "").strip()
    if not spec:
        raise ValueError("Pages per part is empty.")
    if not spec.isdecimal():
        raise ValueError(f"Invalid number of pages '{spec}'.")
    value = int(spec)
    if value < 1:
        raise ValueError("Pages per part starts at 1.")
    return value


def split_plan(total_pages: int, chunk_size: int, base_name: str) -> list[tuple[int, int, str]]:
    total_parts = -(-total_pages // chunk_size)
    page_pad = len(str(total_pages))
    part_pad = len(str(total_parts))
    plan = []
    for idx, start in enumerate(range(0, total_pages, chunk_size), start=1):
        end = min(start + chunk_size, total_pages)
        suffix = f"p{start + 1:0{page_pad}d}" if chunk_size == 1 else f"part{idx:0{part_pad}d}_p{start + 1}-{end}"
        plan.append((start, end, f"{base_name}_{suffix}.pdf"))
    return plan


def extracted_file_name(base_name: str) -> str:
    return f"{base_name}_extracted.pdf"


def output_preview(page_count: int, file_count: int, first_name: str, last_name: str) -> str:
    pages = f"{page_count} page{'s' if page_count != 1 else ''}"
    if file_count == 1:
        return f"{pages}  →  {first_name}"
    return f"{pages}  →  {file_count} files, {first_name} to {last_name}"


def _rounded_span(y: float, top: float, bottom: float, left: float, right: float, radius: float) -> tuple[float, float] | None:
    if not top <= y <= bottom:
        return None
    inset = max(top + radius - y, y - bottom + radius, 0.0)
    shrink = radius - (radius * radius - inset * inset) ** 0.5
    return left + shrink, right - shrink


def _app_icon_row(y: float) -> list[tuple[float, float, tuple[int, int, int] | None]]:
    tile = _rounded_span(y, 0.04, 0.96, 0.04, 0.96, 0.22)
    if tile is None:
        return []
    spans: list[tuple[float, float, tuple[int, int, int] | None]] = [(*tile, None)]
    page = None if abs(y - APP_ICON_CUT_Y) <= 0.035 else _rounded_span(y, 0.15, 0.85, 0.27, 0.73, 0.05)
    if page:
        right = min(page[1], y + 0.41)
        spans.append((page[0], right, APP_ICON_PAGE))
        if y <= 0.32:
            spans.append((0.56, right, APP_ICON_FOLD))
        for line_y, line_right in APP_ICON_TEXT_LINES:
            bar = _rounded_span(y, line_y - 0.018, line_y + 0.018, 0.35, line_right, 0.018)
            if bar and not (y <= 0.32 and bar[1] > 0.56):
                spans.append((*bar, APP_ICON_TEXT))
    if abs(y - APP_ICON_CUT_Y) <= 0.016:
        spans.extend((0.1125 + k * 0.09, 0.1675 + k * 0.09, APP_ICON_CUT) for k in range(9))
    return spans


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def render_app_icon_png(size: int) -> bytes:
    grid = APP_ICON_SUPERSAMPLE
    step = 1.0 / (size * grid)
    (r0, g0, b0), (r1, g1, b1) = APP_ICON_GRADIENT
    totals = [[0, 0, 0, 0] for _ in range(size * size)]
    for sub_y in range(size * grid):
        y = (sub_y + 0.5) * step
        spans = _app_icon_row(y)
        if not spans:
            continue
        row = sub_y // grid * size
        for sub_x in range(size * grid):
            x = (sub_x + 0.5) * step
            color: tuple[int, int, int] | None = None
            hit = False
            for left, right, fill in spans:
                if left <= x <= right:
                    color, hit = fill, True
            if not hit:
                continue
            if color is None:
                t = (x + y) / 2
                color = (round(r0 + (r1 - r0) * t), round(g0 + (g1 - g0) * t), round(b0 + (b1 - b0) * t))
            total = totals[row + sub_x // grid]
            total[0] += color[0]
            total[1] += color[1]
            total[2] += color[2]
            total[3] += 1
    pixels = bytearray()
    for index, (r, g, b, hits) in enumerate(totals):
        if index % size == 0:
            pixels.append(0)
        pixels += bytes((r // hits, g // hits, b // hits, hits * 255 // (grid * grid))) if hits else bytes(4)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", header) + _png_chunk(b"IDAT", zlib.compress(bytes(pixels), 9)) + _png_chunk(b"IEND", b"")


class JobCancelled(Exception):
    pass


class _ProgressStream:
    def __init__(self, fh, expected_bytes, on_progress, cancel_check):
        self._fh = fh
        self._expected = max(int(expected_bytes), 1)
        self._on_progress = on_progress
        self._cancel_check = cancel_check
        self._last = -1.0
        self._written = 0

    def write(self, data):
        if self._cancel_check and self._cancel_check():
            raise JobCancelled()
        written = self._fh.write(data)
        self._written += written
        if self._on_progress:
            fraction = min(self._written / self._expected, 0.99)
            if fraction - self._last >= 0.01:
                self._last = fraction
                self._on_progress(fraction)
        return written

    def __getattr__(self, name):
        return getattr(self._fh, name)


def copy_annotation(
    writer: PdfWriter, annot: Any, copies: dict[int, PageObject], named_destinations: dict[str, Destination]
) -> DictionaryObject | None:
    if not isinstance(annot, DictionaryObject):
        return None
    action = annot["/A"] if "/A" in annot else None
    if "/Dest" in annot:
        key, dest = "/Dest", annot["/Dest"]
    elif isinstance(action, DictionaryObject) and action.get("/S") == "/GoTo" and "/D" in action:
        key, dest = "/A", action["/D"]
    else:
        return annot.clone(writer, ignore_fields=SKIPPED_ANNOTATION_KEYS)
    if isinstance(dest, (str, bytes)) and str(dest) in named_destinations:
        dest = named_destinations[str(dest)].dest_array
    if not isinstance(dest, ArrayObject) or not dest or not isinstance(dest[0], IndirectObject):
        return annot.clone(writer, ignore_fields=SKIPPED_ANNOTATION_KEYS)
    target = copies.get(dest[0].idnum)
    if target is None:
        return None
    moved = ArrayObject([target.indirect_reference, *dest[1:]])
    copy = annot.clone(writer, ignore_fields=(*SKIPPED_ANNOTATION_KEYS, 1, key))
    if key == "/Dest":
        copy[NameObject("/Dest")] = moved
    else:
        new_action = action.clone(writer, ignore_fields=(*SKIPPED_ANNOTATION_KEYS, 1, "/D"))
        new_action[NameObject("/D")] = moved
        copy[NameObject("/A")] = writer._add_object(new_action)
    return copy


def write_pdf_pages(
    reader: PdfReader,
    page_indices: list[int],
    out_path: str,
    expected_bytes: int = 0,
    on_progress: Callable[[float], None] | None = None,
    on_write_start: Callable[[], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    named_destinations: dict[str, Destination] | None = None,
) -> bool:
    if named_destinations is None:
        named_destinations = reader.named_destinations
    writer = PdfWriter()
    total = len(page_indices)
    copies: dict[int, PageObject] = {}
    for i, page_index in enumerate(page_indices, start=1):
        if cancel_check and cancel_check():
            return False
        source = reader.pages[page_index]
        copies[source.indirect_reference.idnum] = writer.add_page(source, excluded_keys=[1, "/Annots"])
        if on_progress:
            on_progress(i / total * COLLECT_FRACTION / 2)

    for i, page_index in enumerate(page_indices, start=1):
        if cancel_check and cancel_check():
            return False
        source = reader.pages[page_index]
        annots = ArrayObject()
        for annot in source.annotations or ():
            copy = copy_annotation(writer, annot.get_object(), copies, named_destinations)
            if copy is not None:
                annots.append(writer._add_object(copy))
        if annots:
            copies[source.indirect_reference.idnum][NameObject("/Annots")] = annots
        if on_progress:
            on_progress((0.5 + i / total / 2) * COLLECT_FRACTION)

    if on_write_start:
        on_write_start()

    def write_progress(fraction: float) -> None:
        on_progress(COLLECT_FRACTION + fraction * (1.0 - COLLECT_FRACTION))

    tmp_path = out_path + ".part"
    try:
        with open(tmp_path, "wb") as out_f:
            writer.write(_ProgressStream(out_f, expected_bytes, write_progress if on_progress else None, cancel_check))
        os.replace(tmp_path, out_path)
    except JobCancelled:
        return False
    finally:
        with suppress(OSError):
            Path(tmp_path).unlink()

    if on_progress:
        on_progress(1.0)
    return True


def write_split_parts(
    reader: PdfReader,
    plan: list[tuple[int, int, str]],
    output_dir: str,
    expected_bytes: Callable[[int], int],
    on_progress: Callable[[float], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> bool:
    total_parts = len(plan)
    named_destinations = reader.named_destinations
    created: list[str] = []
    finished = False
    try:
        for idx, (start, end, name) in enumerate(plan, start=1):
            if cancel_check and cancel_check():
                break
            out_path = make_unique_path(str(Path(output_dir) / name))
            if not write_pdf_pages(
                reader,
                list(range(start, end)),
                out_path,
                expected_bytes=expected_bytes(end - start),
                on_progress=(lambda f, done=idx - 1: on_progress((done + f) / total_parts)) if on_progress else None,
                cancel_check=cancel_check,
                named_destinations=named_destinations,
            ):
                break
            created.append(out_path)
        else:
            finished = True
    finally:
        if not finished:
            for path in created:
                with suppress(OSError):
                    Path(path).unlink()
    return finished


class EncryptedPDFError(ValueError):
    pass


@dataclass
class RangeParseResult:
    valid: bool | None
    empty: bool
    indices: list[int] | None
    error: str = ""


@contextmanager
def open_pdf_reader(path: str, password: str) -> Generator[PdfReader, None, None]:
    with open(path, "rb") as f:
        reader = PdfReader(f)
        if reader.is_encrypted and all(reader.decrypt(attempt) == PasswordType.NOT_DECRYPTED for attempt in (password, "")):
            raise EncryptedPDFError()
        yield reader


user32 = ctypes.windll.user32
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND

dwmapi = ctypes.windll.dwmapi
dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long


def use_dark_title_bar(window: tk.Tk) -> None:
    window.update_idletasks()
    hwnd = user32.GetParent(window.winfo_id())
    if not hwnd:
        return
    for attribute, value in ((DWMWA_USE_IMMERSIVE_DARK_MODE, 1), (DWMWA_CAPTION_COLOR, TITLE_BAR_COLORREF)):
        setting = ctypes.c_int(value)
        dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(setting), ctypes.sizeof(setting))


def fade_in(window: tk.Tk, step: int = 1) -> None:
    with suppress(tk.TclError):
        window.attributes("-alpha", min(step / FADE_IN_STEPS, 1.0))
        if step < FADE_IN_STEPS:
            window.after(FADE_IN_STEP_MS, fade_in, window, step + 1)


def center_window_on_cursor_monitor(window: tk.Tk) -> None:
    window.update_idletasks()

    min_w, min_h = window.minsize()
    width = max(window.winfo_reqwidth(), min_w)
    height = max(window.winfo_reqheight(), min_h)

    pt = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(pt))

    hmon = user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST)

    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(hmon, ctypes.byref(mi))

    work = mi.rcWork
    x = max(work.left, work.left + (work.right - work.left - width) // 2)
    y = max(work.top, work.top + (work.bottom - work.top - height) // 2)

    window.minsize(width, height)
    window.geometry(f"{width}x{height}+{x}+{y}")


class PDFCutterApp(tb.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master)

        self.master.title(f"PDF Cutter {APP_VERSION}")
        self.master.minsize(780, 560)

        self.input_path_var = tk.StringVar(value=USER_PINNED_BROWSE_DIR_DO_NOT_CHANGE)
        self.output_dir_var = tk.StringVar(value=USER_PINNED_BROWSE_DIR_DO_NOT_CHANGE)
        self.password_var = tk.StringVar()
        self.base_name_var = tk.StringVar()
        self.operation_var = tk.StringVar(value=OP_EXTRACT)
        self.range_spec_var = tk.StringVar(value="")
        self.chunk_size_var = tk.StringVar(value="10")
        self.open_folder_var = tk.BooleanVar(value=False)

        self.pdf_info_var = tk.StringVar(value=MSG_NO_FILE_LOADED)
        self.status_var = tk.StringVar(value=STATUS_READY)
        self.progress_var = tk.DoubleVar(value=0.0)

        self._loaded_page_count = 0
        self._current_input_path: str = ""
        self._cached_password: str = ""
        self._cached_stamp: tuple[int, int] = (0, 0)
        self._auto_base_name: str = ""
        self._auto_range_spec: str = ""

        self._job_queue: queue.Queue[tuple[Literal["status", "progress", "error", "done", "cancelled"], Any]] = queue.Queue()
        self._worker_thread: threading.Thread | None = None
        self._cancel_event = threading.Event()
        self._job_running = False
        self._last_progress = -1.0
        self._refresh_debounce_id: str | None = None
        self._active_job: JobDict | None = None
        self._drag_over = False

        self._build_ui()
        self._wire_events()
        self._update_mode_ui()

        self._setup_dnd()
        self._setup_close_handler()

        self._update_open_dir_button_state()
        self._update_file_chip()
        self.after_idle(self._show_path_ends)

    def _labeled_entry(
        self, frame, row: int, label: str, var, *, label_padx=(0, 8), label_pady=6, entry_pady=6, entry_sticky="ew", **entry_kwargs
    ) -> tb.Entry:
        tb.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=label_padx, pady=label_pady)
        entry = tb.Entry(frame, textvariable=var, **entry_kwargs)
        entry.grid(row=row, column=1, sticky=entry_sticky, pady=entry_pady)
        return entry

    def _build_ui(self) -> None:
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)

        self.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        main_frame = tb.Frame(self, padding=15)
        main_frame.grid(row=0, column=0, sticky="nsew")
        main_frame.columnconfigure(0, weight=1)

        self._app_icons = [
            tk.PhotoImage(master=self.master, data=base64.b64encode(render_app_icon_png(size)).decode("ascii"), format="png")
            for size in APP_ICON_SIZES
        ]
        self.master.iconphoto(True, *self._app_icons)

        header = tb.Frame(main_frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        _title_wrap = tb.Frame(header)
        _title_wrap.pack(side="left")
        tb.Label(_title_wrap, image=self._app_icons[0]).pack(side="left", padx=(0, 12))
        _title_stack = tb.Frame(_title_wrap)
        _title_stack.pack(side="left")
        tb.Label(_title_stack, text="PDF Cutter", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tb.Label(_title_stack, text="Extract  ·  Split  ·  Save", font=("Segoe UI", 9), bootstyle="light").pack(anchor="w")
        tb.Label(header, text=f"v{APP_VERSION}", font=("Segoe UI", 9), bootstyle="inverse-dark", padding=(10, 3)).pack(side="right")

        path_frame = tb.Labelframe(main_frame, text="Files", padding=10)
        path_frame.grid(row=1, column=0, sticky="ew")
        path_frame.columnconfigure(1, weight=1)

        self._path_entries: list[tb.Entry] = []
        for row, label, var, browse_cmd, browse_style in (
            (0, "Input PDF:", self.input_path_var, self._browse_input, "primary-outline"),
            (1, "Output folder:", self.output_dir_var, self._browse_output_dir, "secondary-outline"),
        ):
            self._path_entries.append(self._labeled_entry(path_frame, row, label, var))
            tb.Button(path_frame, text="Browse...", command=browse_cmd, bootstyle=browse_style, cursor="hand2").grid(
                row=row, column=2, sticky="ew", padx=(8, 0), pady=6
            )

        self.output_open_button = tb.Button(path_frame, text="Open", command=self._open_output_folder_now, bootstyle="secondary", cursor="hand2")
        self.output_open_button.grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=6)

        self._labeled_entry(path_frame, 2, "Password (optional):", self.password_var, show="*")

        self.file_chip = tb.Frame(path_frame, padding=(10, 7), bootstyle="dark")
        self.file_chip.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 0))
        self.file_chip.columnconfigure(1, weight=1)
        self.file_dot = tb.Label(self.file_chip, text="●", font=("Segoe UI", 10), bootstyle="inverse-dark")
        self.file_dot.grid(row=0, column=0, padx=(0, 8))
        self.file_label = tb.Label(self.file_chip, text=MSG_NO_FILE_LOADED, font=("Segoe UI", 10), bootstyle="inverse-dark")
        self.file_label.grid(row=0, column=1, sticky="w")
        self.file_hint = tb.Label(self.file_chip, text="", font=("Segoe UI", 8), bootstyle="inverse-dark")
        self.file_hint.grid(row=0, column=2, sticky="e", padx=(12, 0))

        options_frame = tb.Labelframe(main_frame, text="Operation", padding=10)
        options_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        options_frame.columnconfigure(1, weight=1)

        mode_switch = tb.Frame(options_frame)
        mode_switch.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        mode_switch.columnconfigure((0, 1), weight=1, uniform="mode")
        for column, text, value in (
            (0, "Extract pages/ranges into one PDF", OP_EXTRACT),
            (1, "Split into parts of N pages", OP_SPLIT),
        ):
            tb.Radiobutton(
                mode_switch, text=text, variable=self.operation_var, value=value, bootstyle="primary-toolbutton", cursor="hand2"
            ).grid(row=0, column=column, sticky="ew")

        range_label = tb.Label(options_frame, text="Ranges (e.g. 1-3,6,9):")
        range_label.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)

        self.range_entry = tb.Entry(options_frame, textvariable=self.range_spec_var, font=("Consolas", 11))
        self.range_entry.grid(row=1, column=1, sticky="ew", pady=4)

        self.range_icon = tb.Label(options_frame, text="", font=("Segoe UI", 12), width=3)
        self.range_icon.grid(row=1, column=2, sticky="w", padx=(8, 0), pady=4)

        chunk_label = tb.Label(options_frame, text="Pages per part (N):")
        chunk_label.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)

        chunk_wrap = tb.Frame(options_frame)
        chunk_wrap.grid(row=1, column=1, columnspan=2, sticky="w", pady=4)

        self.chunk_entry = tb.Entry(chunk_wrap, textvariable=self.chunk_size_var, font=("Consolas", 11), width=10)
        self.chunk_entry.pack(side="left")

        self.chunk_icon = tb.Label(chunk_wrap, text="", font=("Segoe UI", 12), width=3)
        self.chunk_icon.pack(side="left", padx=(8, 0))

        tb.Label(chunk_wrap, text="Use 1 for single-page PDFs", font=("Segoe UI", 9), bootstyle="light").pack(side="left", padx=(8, 0))

        options_frame.columnconfigure(0, minsize=max(range_label.winfo_reqwidth(), chunk_label.winfo_reqwidth()) + 8)
        self._mode_widgets = {OP_EXTRACT: (range_label, self.range_entry, self.range_icon), OP_SPLIT: (chunk_label, chunk_wrap)}

        self.preview_label = tb.Label(options_frame, text="", font=("Segoe UI", 9), bootstyle="light")
        self.preview_label.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))

        name_frame = tb.Labelframe(main_frame, text="Output naming", padding=10)
        name_frame.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        name_frame.columnconfigure(1, weight=1)

        self._labeled_entry(name_frame, 0, "Base name/prefix:", self.base_name_var)

        tb.Checkbutton(name_frame, text="Open output folder when done", variable=self.open_folder_var, cursor="hand2").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 2)
        )

        action_frame = tb.Frame(main_frame)
        action_frame.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        action_frame.columnconfigure(0, weight=1)

        self.start_button = tb.Button(action_frame, text="▶  Start", command=self._start_job, bootstyle="success", width=14, cursor="hand2")
        self.start_button.grid(row=0, column=0, padx=(0, 4), sticky="e")

        self.cancel_button = tb.Button(
            action_frame, text="✕  Cancel", command=self._cancel_job, bootstyle="danger-outline", width=14, state="disabled", cursor="hand2"
        )
        self.cancel_button.grid(row=0, column=1)

        self.status_frame = tb.Frame(self, padding=(10, 6), bootstyle="primary")
        self.status_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.status_frame.columnconfigure(0, weight=1)

        self.status_label = tb.Label(self.status_frame, textvariable=self.status_var, bootstyle="inverse-primary")
        self.status_label.grid(row=0, column=0, sticky="ew")

        self.percent_label = tb.Label(self.status_frame, text="", width=5, anchor="e", bootstyle="inverse-primary")
        self.percent_label.grid(row=0, column=1, padx=(8, 0))

        progress_container = tk.Frame(self.status_frame, bd=1, relief="solid", background="#666666")
        progress_container.grid(row=0, column=2, padx=(8, 0))

        self.progress = tb.Progressbar(
            progress_container,
            mode="determinate",
            variable=self.progress_var,
            maximum=100.0,
            value=0.0,
            length=PROGRESS_BAR_LENGTH,
            bootstyle="info",
        )
        self.progress.pack(padx=1, pady=1)

    def _set_status(self, message: str, level: str = "info") -> None:
        self.status_var.set(message)
        theme_color = {"info": "primary", "success": "success", "error": "danger", "warning": "warning"}.get(level, "primary")
        self._safe_configure(self.status_frame, bootstyle=theme_color)
        self._safe_configure(self.status_label, bootstyle=f"inverse-{theme_color}")
        self._safe_configure(self.percent_label, bootstyle=f"inverse-{theme_color}")

    def _set_progress_style(self, bootstyle: str) -> None:
        self._safe_configure(self.progress, bootstyle=bootstyle)

    def _safe_configure(self, widget, **kwargs) -> None:
        with suppress(tk.TclError):
            widget.configure(**kwargs)

    @property
    def _input_path(self) -> str:
        return self.input_path_var.get().strip().strip('"')

    @property
    def _output_dir(self) -> str:
        return self.output_dir_var.get().strip().strip('"')

    @property
    def _base_name(self) -> str:
        return sanitize_filename_component(self.base_name_var.get().strip() or self._auto_base_name)

    def _parse_ranges(self) -> RangeParseResult:
        page_count = self._loaded_page_count
        if self.operation_var.get() != OP_EXTRACT or page_count <= 0:
            return RangeParseResult(None, False, None)

        text = self.range_spec_var.get().strip()
        if not text:
            return RangeParseResult(None, True, None)

        try:
            indices = parse_page_ranges(text, page_count)
            return RangeParseResult(True, False, indices)
        except ValueError as e:
            return RangeParseResult(False, False, None, str(e))

    def _parse_chunk(self) -> RangeParseResult:
        if self.operation_var.get() != OP_SPLIT or self._loaded_page_count <= 0:
            return RangeParseResult(None, False, None)

        text = self.chunk_size_var.get().strip()
        if not text:
            return RangeParseResult(None, True, None)

        try:
            parse_chunk_size(text)
            return RangeParseResult(True, False, None)
        except ValueError as e:
            return RangeParseResult(False, False, None, str(e))

    def _update_open_dir_button_state(self) -> None:
        output_dir = self._output_dir
        state = "normal" if output_dir and Path(output_dir).is_dir() else "disabled"
        self._safe_configure(self.output_open_button, state=state)

    def _update_range_icon(self) -> None:
        ranges = self._parse_ranges()
        chunk = self._parse_chunk()
        styles = {
            None: ("", COLOR_DEFAULT_FG),
            True: (ICON_VALID, COLOR_SUCCESS),
            False: (ICON_INVALID, COLOR_ERROR),
        }
        for widget, state in ((self.range_icon, ranges.valid), (self.chunk_icon, chunk.valid)):
            icon, color = styles[state]
            self._safe_configure(widget, text=icon, foreground=color)
        self._update_preview(ranges, chunk)
        if self._job_running:
            return
        result = chunk if self.operation_var.get() == OP_SPLIT else ranges
        if result.valid is False:
            self._set_status(result.error, "error")
        elif self._loaded_page_count <= 0 and self.pdf_info_var.get() != MSG_NO_FILE_LOADED:
            self._set_status(self.pdf_info_var.get(), "error")
        elif result.valid is True:
            self._set_status(STATUS_READY, "success")
        else:
            self._set_status(STATUS_READY, "info")

    def _update_preview(self, ranges: RangeParseResult | None = None, chunk: RangeParseResult | None = None) -> None:
        ranges = ranges or self._parse_ranges()
        chunk = chunk or self._parse_chunk()
        text = ""
        if ranges.valid and ranges.indices:
            name = extracted_file_name(self._base_name)
            text = output_preview(len(ranges.indices), 1, name, name)
        elif chunk.valid:
            plan = split_plan(self._loaded_page_count, parse_chunk_size(self.chunk_size_var.get()), self._base_name)
            text = output_preview(self._loaded_page_count, len(plan), plan[0][2], plan[-1][2])
        self._safe_configure(self.preview_label, text=text)

    def _update_file_chip(self) -> None:
        info = self.pdf_info_var.get()
        hint = MSG_DROP_HINT if HAS_DND else ""
        if self._drag_over:
            surface, text, dot_color, text_color, hint = "info", MSG_DROP_TO_LOAD, "white", "white", ""
        elif self._loaded_page_count > 0:
            surface, text, dot_color, text_color = "dark", info, COLOR_SUCCESS, "white"
        elif info == MSG_NO_FILE_LOADED:
            surface, text, dot_color, text_color = "dark", info, COLOR_DEFAULT_FG, COLOR_DEFAULT_FG
        else:
            surface, text, dot_color, text_color = "dark", info, COLOR_ERROR, COLOR_ERROR
        self._safe_configure(self.file_chip, bootstyle=surface)
        for widget, color in ((self.file_dot, dot_color), (self.file_label, text_color), (self.file_hint, COLOR_DEFAULT_FG)):
            self._safe_configure(widget, bootstyle=f"inverse-{surface}")
            self._safe_configure(widget, foreground=color)
        self._safe_configure(self.file_label, text=text)
        self._safe_configure(self.file_hint, text=hint)

    def _show_path_ends(self) -> None:
        for entry in self._path_entries:
            with suppress(tk.TclError):
                entry.xview_moveto(1.0)

    def _open_output_folder_now(self) -> None:
        output_dir = self._output_dir
        if output_dir and Path(output_dir).is_dir():
            with suppress(OSError):
                os.startfile(output_dir)

    def _wire_events(self) -> None:
        self.operation_var.trace_add("write", lambda *_: self._update_mode_ui())
        self.input_path_var.trace_add("write", lambda *_: self._debounced_refresh_pdf_info())
        self.output_dir_var.trace_add("write", lambda *_: self._update_open_dir_button_state())
        self.range_spec_var.trace_add("write", lambda *_: self._update_range_icon())
        self.chunk_size_var.trace_add("write", lambda *_: self._update_range_icon())
        self.password_var.trace_add("write", lambda *_: self._debounced_refresh_pdf_info())
        self.base_name_var.trace_add("write", lambda *_: self._update_preview())
        self.pdf_info_var.trace_add("write", lambda *_: self._update_file_chip())

    def _setup_dnd(self) -> None:
        if not HAS_DND:
            return
        self.master.drop_target_register(DND_FILES)
        self.master.dnd_bind("<<Drop>>", self._on_drop)
        self.master.dnd_bind("<<DropEnter>>", self._on_drag_enter)
        self.master.dnd_bind("<<DropLeave>>", self._on_drag_leave)

    def _on_drag_enter(self, event) -> str:
        self._drag_over = True
        self._update_file_chip()
        return event.action

    def _on_drag_leave(self, event) -> str:
        self._drag_over = False
        self._update_file_chip()
        return event.action

    def _setup_close_handler(self) -> None:
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            self._cancel_event.set()
            self._worker_thread.join(timeout=2.0)
        self.master.destroy()

    def _on_drop(self, event) -> None:
        self._drag_over = False
        self._update_file_chip()
        data = getattr(event, "data", "")
        try:
            raw_paths = self.master.tk.splitlist(data)
        except tk.TclError:
            raw_paths = [data.strip("{}")]
        for raw_path in raw_paths:
            p = Path(raw_path)
            if p.is_file() and p.suffix.lower() == ".pdf":
                self.input_path_var.set(str(p))
                self._show_path_ends()
                return
        self._set_status("Dropped file is not a PDF", "error")

    def _debounced_refresh_pdf_info(self) -> None:
        self._cancel_pending_refresh()
        if self._job_running:
            return
        self._refresh_debounce_id = self.after(REFRESH_DEBOUNCE_MS, self._refresh_pdf_info)

    def _cancel_pending_refresh(self) -> None:
        if self._refresh_debounce_id:
            self.after_cancel(self._refresh_debounce_id)
            self._refresh_debounce_id = None

    def _update_mode_ui(self) -> None:
        op = self.operation_var.get()
        self.range_entry.state(["!disabled"] if op == OP_EXTRACT else ["disabled"])
        self.chunk_entry.state(["!disabled"] if op == OP_SPLIT else ["disabled"])
        for mode, widgets in self._mode_widgets.items():
            for widget in widgets:
                if mode == op:
                    widget.grid()
                else:
                    widget.grid_remove()
        self._update_range_icon()

    def _set_var_from_dialog(self, var, dialog, **kwargs) -> None:
        if value := dialog(**kwargs):
            var.set(str(Path(value)))
            self._show_path_ends()

    def _get_initial_dir(self) -> str:
        return self._output_dir or USER_PINNED_BROWSE_DIR_DO_NOT_CHANGE

    def _browse_input(self) -> None:
        self._set_var_from_dialog(
            self.input_path_var,
            filedialog.askopenfilename,
            title="Select PDF",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
            initialdir=self._get_initial_dir(),
        )

    def _browse_output_dir(self) -> None:
        self._set_var_from_dialog(
            self.output_dir_var,
            filedialog.askdirectory,
            title="Select output folder",
            initialdir=self._get_initial_dir(),
        )

    def _refresh_pdf_info(self) -> None:
        self._cancel_pending_refresh()
        self._update_open_dir_button_state()
        path = self._input_path
        password = self.password_var.get()
        stamp = file_stamp(path)

        if (path, password, stamp) == (self._current_input_path, self._cached_password, self._cached_stamp) and self._loaded_page_count > 0:
            return

        self._loaded_page_count = 0
        self.pdf_info_var.set(self._load_pdf_info(path, password, stamp))
        self._update_range_icon()

    def _load_pdf_info(self, path: str, password: str, stamp: tuple[int, int]) -> str:
        if not path:
            return MSG_NO_FILE_LOADED

        input_path = Path(path)
        if not input_path.is_file():
            return "Input file not found"

        try:
            with open_pdf_reader(path, password) as reader:
                page_count = len(reader.pages)
        except EncryptedPDFError:
            return MSG_ENCRYPTED_NEED_PASSWORD
        except Exception as e:
            return f"Could not read PDF: {e}"

        self._loaded_page_count = page_count
        self._current_input_path = path
        self._cached_password = password
        self._cached_stamp = stamp

        current_range = self.range_spec_var.get().strip()
        if not current_range or current_range == self._auto_range_spec:
            self._auto_range_spec = f"1-{page_count}"
            self.range_spec_var.set(self._auto_range_spec)

        current_base_name = self.base_name_var.get().strip()
        if not current_base_name or current_base_name == self._auto_base_name:
            self._auto_base_name = sanitize_filename_component(input_path.stem)
            self.base_name_var.set(self._auto_base_name)

        return f"{input_path.name}  ·  {page_count} page{'s' if page_count != 1 else ''}"

    def _validate_inputs(self) -> JobDict:
        input_path = self._input_path
        output_dir = self._output_dir
        password = self.password_var.get()
        base_name = self._base_name
        operation = self.operation_var.get()

        if not input_path:
            raise ValueError("Select an input PDF.")
        if not Path(input_path).is_file():
            raise ValueError("Input PDF not found.")
        if not output_dir:
            raise ValueError("Select an output folder.")
        if self._loaded_page_count <= 0:
            raise ValueError(self.pdf_info_var.get())

        chunk_size = 0
        page_indices: list[int] = []

        if operation == OP_EXTRACT:
            result = self._parse_ranges()
            if result.empty:
                raise ValueError("Enter page ranges (e.g. 1-3,6,9).")
            if not result.valid or result.indices is None:
                raise ValueError(result.error or "Invalid page range.")
            page_indices = result.indices
        else:
            chunk_size = parse_chunk_size(self.chunk_size_var.get())

        return {
            "input_path": input_path,
            "output_dir": output_dir,
            "password": password,
            "base_name": base_name,
            "operation": operation,
            "page_indices": page_indices,
            "chunk_size": chunk_size,
            "open_folder": self.open_folder_var.get(),
        }

    def _start_job(self) -> None:
        if self._job_running:
            return

        self._refresh_pdf_info()

        try:
            job = self._validate_inputs()
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return

        self._job_running = True
        self._active_job = job
        self._cancel_event.clear()
        self._last_progress = -1.0
        self.progress_var.set(0.0)
        self._set_status(STATUS_WORKING)
        self._set_progress_style("info-striped")
        self.start_button.state(["disabled"])
        self.cancel_button.state(["!disabled"])

        self._worker_thread = threading.Thread(target=self._worker, args=(job,), daemon=True)
        self._worker_thread.start()
        self.after(POLL_INTERVAL_MS, self._poll_queue)

    def _cancel_job(self) -> None:
        if self._job_running:
            self._cancel_event.set()
            self.cancel_button.state(["disabled"])
            self._set_status(STATUS_CANCELLING, "warning")

    def _finish_job(self, style: str, status: str, level: str) -> None:
        self._job_running = False
        self.start_button.state(["!disabled"])
        self.cancel_button.state(["disabled"])
        self.progress_var.set(0.0)
        self._safe_configure(self.percent_label, text="")
        self._set_progress_style(style)
        self._set_status(status, level)
        self._debounced_refresh_pdf_info()

    def _poll_queue(self) -> None:
        still_running = bool(self._worker_thread and self._worker_thread.is_alive())

        while True:
            try:
                kind, payload = self._job_queue.get_nowait()
            except queue.Empty:
                break

            if kind == "status":
                self._set_status(str(payload))
            elif kind == "progress":
                self.progress_var.set(float(payload))
                self._safe_configure(self.percent_label, text=f"{float(payload):.0f}%")
            elif kind == "done":
                self._finish_job("info", STATUS_READY, "info")
                self._update_open_dir_button_state()
                self._update_range_icon()
                if self._active_job and self._active_job["open_folder"]:
                    with suppress(OSError):
                        os.startfile(self._active_job["output_dir"])
                messagebox.showinfo("Completed", str(payload))
                return
            elif kind == "cancelled":
                self._finish_job("warning", STATUS_CANCELLED, "warning")
                return
            elif kind == "error":
                self._finish_job("danger", str(payload), "error")
                messagebox.showerror("Error", str(payload))
                return

        if still_running:
            self.after(POLL_INTERVAL_MS, self._poll_queue)
        else:
            self._finish_job("info", STATUS_READY, "info")
            self._update_range_icon()

    def _emit_progress(self, percent: float) -> None:
        percent = max(0.0, min(100.0, percent))
        if percent >= 100.0 or percent - self._last_progress >= PROGRESS_STEP:
            self._last_progress = percent
            self._job_queue.put(("progress", percent))

    def _worker(self, job: JobDict) -> None:
        try:
            self._job_queue.put(("status", STATUS_OPENING_PDF))

            try:
                Path(job["output_dir"]).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                raise ValueError(f"Cannot create output folder: {e}")

            source_size = Path(job["input_path"]).stat().st_size

            with open_pdf_reader(job["input_path"], job["password"]) as reader:

                total_pages = len(reader.pages)
                if total_pages == 0:
                    raise ValueError("PDF has no pages.")

                def estimate_bytes(count: int) -> int:
                    return max(source_size * count // total_pages, 1024)

                if job["operation"] == OP_EXTRACT:
                    page_indices: list[int] = job["page_indices"]
                    out_path = make_unique_path(str(Path(job["output_dir"]) / extracted_file_name(job["base_name"])))
                    self._job_queue.put(("status", STATUS_COLLECTING_PAGES.format(count=len(page_indices))))

                    if not write_pdf_pages(
                        reader,
                        page_indices,
                        out_path,
                        expected_bytes=estimate_bytes(len(page_indices)),
                        on_progress=lambda f: self._emit_progress(f * 100.0),
                        on_write_start=lambda: self._job_queue.put(("status", STATUS_WRITING_OUTPUT)),
                        cancel_check=self._cancel_event.is_set,
                    ):
                        self._job_queue.put(("cancelled", None))
                        return
                    done_summary = f"Saved: {out_path}"

                else:
                    chunk_size: int = job["chunk_size"]
                    plan = split_plan(total_pages, chunk_size, job["base_name"])
                    total_parts = len(plan)
                    self._job_queue.put(("status", STATUS_WRITING_PARTS.format(count=total_parts, unit="page(s)" if chunk_size == 1 else "part(s)")))

                    if not write_split_parts(
                        reader,
                        plan,
                        job["output_dir"],
                        estimate_bytes,
                        on_progress=lambda f: self._emit_progress(f * 100.0),
                        cancel_check=self._cancel_event.is_set,
                    ):
                        self._job_queue.put(("cancelled", None))
                        return

                    done_summary = f"Saved {total_parts} file(s) to: {job['output_dir']}"

                self._job_queue.put(("done", done_summary))

        except EncryptedPDFError:
            self._job_queue.put(("error", MSG_ENCRYPTED_WRONG_PASSWORD))
        except Exception as e:
            self._job_queue.put(("error", str(e) or type(e).__name__))


def main() -> None:
    if HAS_DND:
        root = TkinterDnD.Tk()
        tb.Style(theme="darkly")
    else:
        root = tb.Window(themename="darkly")

    root.withdraw()
    PDFCutterApp(root)
    center_window_on_cursor_monitor(root)
    with suppress(tk.TclError):
        root.attributes("-alpha", 0.0)
    root.deiconify()
    use_dark_title_bar(root)
    fade_in(root)

    root.mainloop()


if __name__ == "__main__":
    main()
