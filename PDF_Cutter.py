import os
import queue
import threading
import ctypes
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Generator, Literal, TypedDict
from ctypes import wintypes
from contextlib import contextmanager, suppress
import tkinter as tk
from tkinter import filedialog, messagebox
import ttkbootstrap as tb
from pypdf import PdfReader, PdfWriter, PasswordType

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False


if hasattr(PdfWriter, "_resolve_links"):
    def _skip_link_resolution(self) -> None:
        with suppress(AttributeError):
            self._unresolved_links.clear()

    PdfWriter._resolve_links = _skip_link_resolution

APP_VERSION = "1.1.0"

USER_PINNED_BROWSE_DIR_DO_NOT_CHANGE = r"D:\Clementine\Desktop\TEST"

COLOR_SUCCESS = "#50fa7b"
COLOR_ERROR = "#ff5555"
COLOR_DEFAULT_FG = "grey"
ICON_VALID = "✅"
ICON_INVALID = "❌"
MONITOR_DEFAULTTONEAREST = 2

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

REFRESH_DEBOUNCE_MS = 400
COLLECT_FRACTION = 0.4
PROGRESS_STEP = 0.5


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


def write_pdf_pages(
    reader: PdfReader,
    page_indices: list[int],
    out_path: str,
    expected_bytes: int = 0,
    on_progress: Callable[[float], None] | None = None,
    on_write_start: Callable[[], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> bool:
    writer = PdfWriter()
    total = len(page_indices)
    for i, page_index in enumerate(page_indices, start=1):
        if cancel_check and cancel_check():
            return False
        writer.add_page(reader.pages[page_index])
        if on_progress:
            on_progress(i / total * COLLECT_FRACTION)

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
        if reader.is_encrypted and reader.decrypt(password or "") == PasswordType.NOT_DECRYPTED:
            raise EncryptedPDFError()
        yield reader


user32 = ctypes.windll.user32
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL


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

        self._build_ui()
        self._wire_events()
        self._update_mode_ui()

        self._setup_dnd()
        self._setup_close_handler()

        self._update_open_dir_button_state()

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

        header = tb.Frame(main_frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))

        _title_wrap = tb.Frame(header)
        _title_wrap.pack(side="left")
        tb.Label(_title_wrap, text="✂", font=("Segoe UI Symbol", 26)).pack(side="left", padx=(0, 10))
        _title_stack = tb.Frame(_title_wrap)
        _title_stack.pack(side="left")
        tb.Label(_title_stack, text="PDF Cutter", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tb.Label(_title_stack, text="Extract  ·  Split  ·  Save", font=("Segoe UI", 9), bootstyle="secondary").pack(anchor="w")

        path_frame = tb.Labelframe(main_frame, text="Files", padding=10)
        path_frame.grid(row=1, column=0, sticky="ew")
        path_frame.columnconfigure(1, weight=1)

        for row, label, var, browse_cmd, browse_style in (
            (0, "Input PDF:", self.input_path_var, self._browse_input, "primary-outline"),
            (1, "Output folder:", self.output_dir_var, self._browse_output_dir, "secondary-outline"),
        ):
            self._labeled_entry(path_frame, row, label, var)
            tb.Button(path_frame, text="Browse...", command=browse_cmd, bootstyle=browse_style).grid(
                row=row, column=2, sticky="ew", padx=(8, 0), pady=6
            )

        self.output_open_button = tb.Button(path_frame, text="Open", command=self._open_output_folder_now, bootstyle="secondary")
        self.output_open_button.grid(row=1, column=3, sticky="ew", padx=(8, 0), pady=6)

        self._labeled_entry(path_frame, 2, "Password (optional):", self.password_var, show="*")

        if HAS_DND:
            tb.Label(
                path_frame,
                text="Drop a PDF anywhere in this window to load it",
                font=("Segoe UI", 8),
                bootstyle="secondary",
            ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(6, 0))

        tb.Label(main_frame, textvariable=self.pdf_info_var, font=("Segoe UI", 9), bootstyle="secondary").grid(row=2, column=0, sticky="w", pady=(8, 0))

        tb.Separator(main_frame, orient="horizontal").grid(row=3, column=0, sticky="ew", pady=15)

        options_frame = tb.Labelframe(main_frame, text="Operation", padding=10)
        options_frame.grid(row=4, column=0, sticky="ew")
        options_frame.columnconfigure(1, weight=1)

        tb.Radiobutton(
            options_frame, text="Extract pages/ranges into one PDF",
            variable=self.operation_var, value=OP_EXTRACT
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(2, 2))

        tb.Radiobutton(
            options_frame, text="Split into parts of N pages (use 1 for single-page PDFs)",
            variable=self.operation_var, value=OP_SPLIT
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 2))

        self.range_entry = self._labeled_entry(
            options_frame,
            1,
            "Ranges (e.g. 1-3,6,9):",
            self.range_spec_var,
            label_padx=(18, 8),
            label_pady=4,
            entry_pady=4,
            font=("Consolas", 11),
        )

        self.range_icon = tb.Label(options_frame, text="", font=("Segoe UI", 12), width=3)
        self.range_icon.grid(row=1, column=2, sticky="w", padx=(8, 0), pady=4)

        self.chunk_entry = self._labeled_entry(
            options_frame,
            3,
            "Pages per part (N):",
            self.chunk_size_var,
            label_padx=(18, 8),
            label_pady=4,
            entry_pady=4,
            entry_sticky="w",
            font=("Consolas", 11),
            width=10,
        )

        name_frame = tb.Labelframe(main_frame, text="Output naming", padding=10)
        name_frame.grid(row=5, column=0, sticky="ew", pady=(10, 0))
        name_frame.columnconfigure(1, weight=1)

        self._labeled_entry(name_frame, 0, "Base name/prefix:", self.base_name_var)

        tb.Checkbutton(name_frame, text="Open output folder when done", variable=self.open_folder_var).grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 2)
        )

        action_frame = tb.Frame(main_frame)
        action_frame.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        action_frame.columnconfigure(0, weight=1)

        self.start_button = tb.Button(action_frame, text="▶  Start", command=self._start_job, bootstyle="success", width=14)
        self.start_button.grid(row=0, column=0, padx=(0, 4), sticky="e")

        self.cancel_button = tb.Button(action_frame, text="✕  Cancel", command=self._cancel_job, bootstyle="danger-outline", width=14, state="disabled")
        self.cancel_button.grid(row=0, column=1)

        self.status_frame = tb.Frame(self, padding=(10, 6), bootstyle="primary")
        self.status_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.status_frame.columnconfigure(0, weight=1)

        self.status_label = tb.Label(self.status_frame, textvariable=self.status_var, bootstyle="inverse-primary")
        self.status_label.grid(row=0, column=0, sticky="ew")

        progress_container = tk.Frame(self.status_frame, bd=1, relief="solid", background="#666666")
        progress_container.grid(row=0, column=1, padx=(8, 0))

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

    def _update_open_dir_button_state(self) -> None:
        output_dir = self._output_dir
        state = "normal" if output_dir and Path(output_dir).is_dir() else "disabled"
        self._safe_configure(self.output_open_button, state=state)

    def _update_range_icon(self) -> None:
        result = self._parse_ranges()
        styles = {
            None: ("", COLOR_DEFAULT_FG),
            True: (ICON_VALID, COLOR_SUCCESS),
            False: (ICON_INVALID, COLOR_ERROR),
        }
        icon, color = styles[result.valid]
        self._safe_configure(self.range_icon, text=icon, foreground=color)
        if self._job_running:
            return
        if result.valid is False:
            self._set_status(result.error, "error")
        elif self._loaded_page_count <= 0 and self.pdf_info_var.get() != MSG_NO_FILE_LOADED:
            self._set_status(self.pdf_info_var.get(), "error")
        elif result.valid is True:
            self._set_status(STATUS_READY, "success")
        else:
            self._set_status(STATUS_READY, "info")

    def _open_output_folder_now(self) -> None:
        if Path(self._output_dir).is_dir():
            with suppress(OSError):
                os.startfile(self._output_dir)

    def _wire_events(self) -> None:
        self.operation_var.trace_add("write", lambda *_: self._update_mode_ui())
        self.input_path_var.trace_add("write", lambda *_: self._debounced_refresh_pdf_info())
        self.output_dir_var.trace_add("write", lambda *_: self._update_open_dir_button_state())
        self.range_spec_var.trace_add("write", lambda *_: self._update_range_icon())
        self.password_var.trace_add("write", lambda *_: self._debounced_refresh_pdf_info())

    def _setup_dnd(self) -> None:
        if not HAS_DND:
            return
        self.master.drop_target_register(DND_FILES)
        self.master.dnd_bind("<<Drop>>", self._on_drop)

    def _setup_close_handler(self) -> None:
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            self._cancel_event.set()
            self._worker_thread.join(timeout=2.0)
        self.master.destroy()

    def _on_drop(self, event) -> None:
        data = getattr(event, "data", "")
        try:
            raw_paths = self.master.tk.splitlist(data)
        except tk.TclError:
            raw_paths = [data.strip("{}")]
        for raw_path in raw_paths:
            p = Path(raw_path)
            if p.is_file() and p.suffix.lower() == ".pdf":
                self.input_path_var.set(str(p))
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
        self._update_range_icon()

    def _set_var_from_dialog(self, var, dialog, **kwargs) -> None:
        if value := dialog(**kwargs):
            var.set(str(Path(value)))

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
        base_name = sanitize_filename_component(self.base_name_var.get().strip() or self._auto_base_name)
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
            chunk_size_raw = self.chunk_size_var.get().strip()
            if not chunk_size_raw.isdecimal() or int(chunk_size_raw) == 0:
                raise ValueError("Pages per part (N) must be a positive integer.")
            chunk_size = int(chunk_size_raw)

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
                    out_path = make_unique_path(str(Path(job["output_dir"]) / f"{job['base_name']}_extracted.pdf"))
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
                    total_parts = -(-total_pages // chunk_size)
                    part_span = 100.0 / total_parts
                    is_single = chunk_size == 1
                    self._job_queue.put(("status", STATUS_WRITING_PARTS.format(count=total_parts, unit="page(s)" if is_single else "part(s)")))

                    page_pad = len(str(total_pages))
                    part_pad = len(str(total_parts))
                    output_dir = Path(job["output_dir"])
                    created_files: list[str] = []
                    finished = False
                    try:
                        for idx, start in enumerate(range(0, total_pages, chunk_size), start=1):
                            if self._cancel_event.is_set():
                                break
                            end = min(start + chunk_size, total_pages)
                            suffix = f"p{start + 1:0{page_pad}d}" if is_single else f"part{idx:0{part_pad}d}_p{start + 1}-{end}"
                            out_path = make_unique_path(str(output_dir / f"{job['base_name']}_{suffix}.pdf"))
                            base = (idx - 1) * part_span
                            if not write_pdf_pages(
                                reader,
                                list(range(start, end)),
                                out_path,
                                expected_bytes=estimate_bytes(end - start),
                                on_progress=lambda f, b=base: self._emit_progress(b + part_span * f),
                                cancel_check=self._cancel_event.is_set,
                            ):
                                break
                            created_files.append(out_path)
                        else:
                            finished = True
                    finally:
                        if not finished:
                            for created in created_files:
                                with suppress(OSError):
                                    Path(created).unlink()

                    if not finished:
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
    root.deiconify()

    root.mainloop()


if __name__ == "__main__":
    main()
