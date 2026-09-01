import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from PDF_Cutter import (
    make_unique_path,
    open_pdf_reader,
    parse_page_ranges,
    sanitize_filename_component,
    write_pdf_pages,
)


def build_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for i in range(pages):
        writer.add_blank_page(100 + i, 200)
    with open(path, "wb") as f:
        writer.write(f)


def page_widths(path: str) -> list[int]:
    return [round(float(page.mediabox.width)) for page in PdfReader(path).pages]


class ParsePageRanges(unittest.TestCase):
    def test_mixed_pages_and_ranges(self):
        self.assertEqual(parse_page_ranges("1-3,6,9", 9), [0, 1, 2, 5, 8])

    def test_spaces_are_tolerated(self):
        self.assertEqual(parse_page_ranges(" 1 - 3 , 5 ", 5), [0, 1, 2, 4])

    def test_overlaps_are_sorted_and_deduplicated(self):
        self.assertEqual(parse_page_ranges("5,1-2,2", 5), [0, 1, 4])

    def test_rejects_out_of_range(self):
        with self.assertRaises(ValueError):
            parse_page_ranges("1-11", 10)

    def test_rejects_reversed_range(self):
        with self.assertRaises(ValueError):
            parse_page_ranges("4-2", 10)

    def test_rejects_page_zero(self):
        with self.assertRaises(ValueError):
            parse_page_ranges("0", 10)

    def test_rejects_empty_and_nonsense(self):
        for spec in ("", "   ", "abc", "1-", "-3", "1-2-3"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse_page_ranges(spec, 10)


class SanitizeFilenameComponent(unittest.TestCase):
    def test_replaces_characters_windows_forbids(self):
        self.assertEqual(sanitize_filename_component('a<b>c:d"e|f?g*h'), "a_b_c_d_e_f_g_h")

    def test_strips_path_separators(self):
        for name in ("../secret", r"..\secret", "a/b"):
            with self.subTest(name=name):
                cleaned = sanitize_filename_component(name)
                self.assertNotIn("/", cleaned)
                self.assertNotIn("\\", cleaned)

    def test_falls_back_when_nothing_usable_is_left(self):
        for name in ("", "   ", "..."):
            with self.subTest(name=name):
                self.assertEqual(sanitize_filename_component(name), "output")


class MakeUniquePath(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_keeps_the_name_when_it_is_free(self):
        target = self.dir / "out.pdf"
        self.assertEqual(make_unique_path(str(target)), str(target))

    def test_never_returns_an_existing_file(self):
        target = self.dir / "out.pdf"
        target.write_bytes(b"kept")
        first = Path(make_unique_path(str(target)))
        self.assertFalse(first.exists())
        first.write_bytes(b"kept")
        self.assertFalse(Path(make_unique_path(str(target))).exists())
        self.assertEqual(target.read_bytes(), b"kept")


class WritePdfPages(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.source = self.dir / "source.pdf"
        build_pdf(self.source, 9)

    def test_writes_exactly_the_requested_pages(self):
        out = str(self.dir / "extracted.pdf")
        with open_pdf_reader(str(self.source), "") as reader:
            self.assertTrue(write_pdf_pages(reader, [0, 1, 2, 5, 8], out))
        self.assertEqual(page_widths(out), [100, 101, 102, 105, 108])

    def test_leaves_no_temporary_file_behind(self):
        out = str(self.dir / "extracted.pdf")
        with open_pdf_reader(str(self.source), "") as reader:
            write_pdf_pages(reader, [0, 1], out)
        self.assertEqual(list(self.dir.glob("*.part")), [])

    def test_cancelling_while_collecting_writes_nothing(self):
        out = self.dir / "extracted.pdf"
        with open_pdf_reader(str(self.source), "") as reader:
            self.assertFalse(write_pdf_pages(reader, [0, 1, 2], str(out), cancel_check=lambda: True))
        self.assertFalse(out.exists())
        self.assertEqual(list(self.dir.glob("*.part")), [])

    def test_cancelling_while_writing_writes_nothing(self):
        calls = []

        def cancel_after_collecting():
            calls.append(None)
            return len(calls) > 9

        out = self.dir / "extracted.pdf"
        with open_pdf_reader(str(self.source), "") as reader:
            self.assertFalse(
                write_pdf_pages(reader, list(range(9)), str(out), cancel_check=cancel_after_collecting)
            )
        self.assertFalse(out.exists())
        self.assertEqual(list(self.dir.glob("*.part")), [])

    def test_progress_runs_from_zero_to_one_without_going_backwards(self):
        seen = []
        out = str(self.dir / "extracted.pdf")
        with open_pdf_reader(str(self.source), "") as reader:
            write_pdf_pages(reader, list(range(9)), out, expected_bytes=self.source.stat().st_size, on_progress=seen.append)
        self.assertEqual(seen[-1], 1.0)
        self.assertTrue(all(b >= a for a, b in zip(seen, seen[1:])))


if __name__ == "__main__":
    unittest.main()
