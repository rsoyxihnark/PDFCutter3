import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, TextStringObject

from PDF_Cutter import (
    EncryptedPDFError,
    extracted_file_name,
    make_unique_path,
    output_preview,
    parse_chunk_size,
    open_pdf_reader,
    parse_page_ranges,
    render_app_icon_png,
    sanitize_filename_component,
    split_plan,
    write_pdf_pages,
    write_split_parts,
)


def build_pdf(path: Path, pages: int) -> None:
    writer = PdfWriter()
    for i in range(pages):
        writer.add_blank_page(100 + i, 200)
    with open(path, "wb") as f:
        writer.write(f)


def build_linked_pdf(path: Path, indirect: bool = False, named: bool = False) -> None:
    writer = PdfWriter()
    for i in range(3):
        page = writer.add_blank_page(100 + i, 200)
        content = DecodedStreamObject()
        content.set_data(f"BT (marker{i}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(content)

    def link(key, value):
        return writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): ArrayObject([FloatObject(0)] * 4),
            NameObject(key): value,
        }))

    def action(kind, key, value):
        made = DictionaryObject({NameObject("/S"): NameObject(kind), NameObject(key): value})
        return writer._add_object(made) if indirect else made

    pages = writer.pages
    if named:
        for index in (1, 2):
            writer.add_named_destination(f"page{index}", index)

    def target(index):
        if named:
            return TextStringObject(f"page{index}")
        return ArrayObject([pages[index].indirect_reference, NameObject("/Fit")])

    annots = ArrayObject([
        link("/Dest", target(1)),
        link("/A", action("/GoTo", "/D", target(1))),
        link("/A", action("/GoTo", "/D", target(2))),
        link("/A", action("/URI", "/URI", TextStringObject("https://example.com"))),
    ])
    pages[0][NameObject("/Annots")] = writer._add_object(annots) if indirect else annots
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


class ParseChunkSize(unittest.TestCase):
    def test_reads_a_plain_number(self):
        self.assertEqual(parse_chunk_size("10"), 10)

    def test_spaces_are_tolerated(self):
        self.assertEqual(parse_chunk_size("  7 "), 7)

    def test_rejects_zero(self):
        with self.assertRaises(ValueError):
            parse_chunk_size("0")

    def test_rejects_empty_and_nonsense(self):
        for spec in ("", "   ", "abc", "-1", "1.5", "1e3"):
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                parse_chunk_size(spec)


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


class SplitPlan(unittest.TestCase):
    def test_single_page_names_are_padded_so_they_sort(self):
        names = [name for _, _, name in split_plan(12, 1, "book")]
        self.assertEqual(names[0], "book_p01.pdf")
        self.assertEqual(names[-1], "book_p12.pdf")
        self.assertEqual(names, sorted(names))

    def test_part_names_are_padded_so_they_sort(self):
        names = [name for _, _, name in split_plan(100, 10, "book")]
        self.assertEqual(names[0], "book_part01_p1-10.pdf")
        self.assertEqual(names[-1], "book_part10_p91-100.pdf")
        self.assertEqual(names, sorted(names))

    def test_every_page_lands_in_exactly_one_part(self):
        for total, chunk in ((9, 3), (10, 3), (1, 1), (7, 10), (100, 1)):
            with self.subTest(total=total, chunk=chunk):
                plan = split_plan(total, chunk, "x")
                covered = [page for start, end, _ in plan for page in range(start, end)]
                self.assertEqual(covered, list(range(total)))

    def test_names_never_repeat(self):
        for total, chunk in ((100, 1), (100, 7), (11, 2), (5, 5)):
            with self.subTest(total=total, chunk=chunk):
                names = [name for _, _, name in split_plan(total, chunk, "x")]
                self.assertEqual(len(set(names)), len(names))


class OpenPdfReader(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.source = self.dir / "source.pdf"
        build_pdf(self.source, 3)

    def encrypted(self, name, **passwords):
        path = self.dir / name
        writer = PdfWriter(clone_from=str(self.source))
        writer.encrypt(**passwords)
        with open(path, "wb") as f:
            writer.write(f)
        return str(path)

    def test_reads_a_protected_pdf_given_the_right_password(self):
        path = self.encrypted("locked.pdf", user_password="secret")
        with open_pdf_reader(path, "secret") as reader:
            self.assertEqual(len(reader.pages), 3)

    def test_refuses_a_protected_pdf_without_the_right_password(self):
        path = self.encrypted("locked.pdf", user_password="secret")
        for password in ("", "wrong"):
            with self.subTest(password=password), self.assertRaises(EncryptedPDFError):
                with open_pdf_reader(path, password):
                    pass

    def test_reads_a_pdf_that_only_restricts_the_owner(self):
        path = self.encrypted("owner_only.pdf", user_password="", owner_password="boss")
        with open_pdf_reader(path, "") as reader:
            self.assertEqual(len(reader.pages), 3)

    def test_a_password_left_from_another_pdf_does_not_block_one_that_needs_none(self):
        path = self.encrypted("owner_only.pdf", user_password="", owner_password="boss")
        with open_pdf_reader(path, "secret") as reader:
            self.assertEqual(len(reader.pages), 3)


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
        writing = []
        out = self.dir / "extracted.pdf"
        with open_pdf_reader(str(self.source), "") as reader:
            self.assertFalse(
                write_pdf_pages(
                    reader,
                    list(range(9)),
                    str(out),
                    on_write_start=lambda: writing.append(True),
                    cancel_check=lambda: bool(writing),
                )
            )
        self.assertTrue(writing)
        self.assertFalse(out.exists())
        self.assertEqual(list(self.dir.glob("*.part")), [])

    def test_progress_runs_from_zero_to_one_without_going_backwards(self):
        seen = []
        out = str(self.dir / "extracted.pdf")
        with open_pdf_reader(str(self.source), "") as reader:
            write_pdf_pages(reader, list(range(9)), out, expected_bytes=self.source.stat().st_size, on_progress=seen.append)
        self.assertEqual(seen[-1], 1.0)
        self.assertTrue(all(b >= a for a, b in zip(seen, seen[1:])))


    LINK_STYLES = ((False, False), (True, False), (False, True))

    def extract_linked(self, indirect, named):
        source = self.dir / f"linked_{indirect}_{named}.pdf"
        build_linked_pdf(source, indirect, named)
        out = self.dir / f"extracted_{indirect}_{named}.pdf"
        with open_pdf_reader(str(source), "") as reader:
            self.assertTrue(write_pdf_pages(reader, [0, 2], str(out)))
        return out

    def test_a_link_to_a_page_left_out_does_not_bring_that_page_along(self):
        for indirect, named in self.LINK_STYLES:
            with self.subTest(indirect=indirect, named=named):
                self.assertNotIn(b"marker1", self.extract_linked(indirect, named).read_bytes())

    def test_links_to_extracted_pages_and_web_links_keep_working(self):
        for indirect, named in self.LINK_STYLES:
            with self.subTest(indirect=indirect, named=named):
                pages = PdfReader(str(self.extract_linked(indirect, named))).pages
                actions = [annot.get_object()["/A"] for annot in pages[0]["/Annots"]]
                self.assertEqual(len(actions), 2)
                self.assertEqual(actions[0]["/D"][0].idnum, pages[1].indirect_reference.idnum)
                self.assertEqual(actions[1]["/URI"], "https://example.com")


class WriteSplitParts(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.source = self.dir / "source.pdf"
        build_pdf(self.source, 6)
        self.out = self.dir / "out"
        self.out.mkdir()

    def split(self, plan, **kwargs):
        with open_pdf_reader(str(self.source), "") as reader:
            return write_split_parts(reader, plan, str(self.out), lambda count: 1024, **kwargs)

    def test_writes_every_part_of_the_plan(self):
        plan = split_plan(6, 2, "book")
        self.assertTrue(self.split(plan))
        self.assertEqual(sorted(p.name for p in self.out.iterdir()), sorted(name for _, _, name in plan))
        self.assertEqual(page_widths(str(self.out / plan[1][2])), [102, 103])

    def test_cancelling_partway_clears_away_the_parts_it_had_written(self):
        plan = split_plan(6, 2, "book")
        self.assertFalse(self.split(plan, cancel_check=lambda: len(list(self.out.iterdir())) >= 2))
        self.assertEqual(list(self.out.iterdir()), [])

    def test_a_part_that_cannot_be_written_clears_away_the_earlier_ones(self):
        plan = split_plan(6, 2, "book")
        plan[2] = (*plan[2][:2], "gone/book_part3.pdf")
        with self.assertRaises(OSError):
            self.split(plan)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_it_never_clears_away_a_file_it_did_not_write(self):
        plan = split_plan(6, 2, "book")
        kept = self.out / plan[0][2]
        kept.write_bytes(b"kept")
        plan[2] = (*plan[2][:2], "gone/book_part3.pdf")
        with self.assertRaises(OSError):
            self.split(plan)
        self.assertEqual([p.name for p in self.out.iterdir()], [kept.name])
        self.assertEqual(kept.read_bytes(), b"kept")

    def test_progress_runs_from_zero_to_one_without_going_backwards(self):
        seen = []
        self.assertTrue(self.split(split_plan(6, 2, "book"), on_progress=seen.append))
        self.assertEqual(seen[-1], 1.0)
        self.assertTrue(all(b >= a for a, b in zip(seen, seen[1:])))


class OutputPreview(unittest.TestCase):
    def test_one_file_names_it(self):
        name = extracted_file_name("book")
        self.assertEqual(output_preview(5, 1, name, name), "5 pages  →  book_extracted.pdf")

    def test_a_single_page_is_not_called_pages(self):
        self.assertEqual(output_preview(1, 1, "a.pdf", "a.pdf"), "1 page  →  a.pdf")

    def test_many_files_name_the_first_and_the_last(self):
        plan = split_plan(45, 10, "book")
        self.assertEqual(
            output_preview(45, len(plan), plan[0][2], plan[-1][2]),
            "45 pages  →  5 files, book_part1_p1-10.pdf to book_part5_p41-45.pdf",
        )


class RenderAppIcon(unittest.TestCase):
    def decode(self, data):
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        chunks, offset = {}, 8
        while offset < len(data):
            length, kind = struct.unpack(">I4s", data[offset:offset + 8])
            body = data[offset + 8:offset + 8 + length]
            self.assertEqual(struct.unpack(">I", data[offset + 8 + length:offset + 12 + length])[0], zlib.crc32(kind + body))
            chunks[kind] = chunks.get(kind, b"") + body
            offset += 12 + length
        width, height, depth, color_type = struct.unpack(">IIBB", chunks[b"IHDR"][:10])
        raw = zlib.decompress(chunks[b"IDAT"])
        rows = [raw[y * (width * 4 + 1):(y + 1) * (width * 4 + 1)] for y in range(height)]
        return width, height, depth, color_type, rows

    def test_every_size_is_a_square_rgba_png(self):
        for size in (16, 32, 48, 256):
            with self.subTest(size=size):
                width, height, depth, color_type, rows = self.decode(render_app_icon_png(size))
                self.assertEqual((width, height, depth, color_type), (size, size, 8, 6))
                self.assertTrue(all(row[0] == 0 and len(row) == size * 4 + 1 for row in rows))

    def test_corners_are_clear_and_the_middle_is_solid(self):
        _, _, _, _, rows = self.decode(render_app_icon_png(32))
        alpha = lambda x, y: rows[y][1 + x * 4 + 3]
        self.assertEqual([alpha(0, 0), alpha(31, 0), alpha(0, 31), alpha(31, 31)], [0, 0, 0, 0])
        self.assertEqual(alpha(16, 8), 255)


if __name__ == "__main__":
    unittest.main()
