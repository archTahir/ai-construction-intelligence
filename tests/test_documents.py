import tempfile
import unittest
from pathlib import Path

import pymupdf

from construction_intelligence.documents import (
    calculate_file_fingerprint,
    identify_source_pages,
    read_pdf_document,
)


class DocumentTests(unittest.TestCase):
    def create_pdf(self, output_path: Path) -> None:
        """Create a two-meeting PDF fixture."""
        pdf_document = pymupdf.open()
        first_page = pdf_document.new_page()
        first_page.insert_text(
            (72, 72),
            "Meeting M01 | 01/04/2023\nM01 / SOURCE PAGE 01 OF 02\nFacade issue reported.",
        )
        second_page = pdf_document.new_page()
        second_page.insert_text(
            (72, 72),
            "M01 / SOURCE PAGE 02 OF 02\nSupporting document requested.",
        )
        third_page = pdf_document.new_page()
        third_page.insert_text(
            (72, 72),
            "Meeting M02 | 08/04/2023\nM02 / SOURCE PAGE 01 OF 01\nUpdated proposal submitted.",
        )
        pdf_document.save(output_path)
        pdf_document.close()

    def test_document_reader_splits_meetings(self) -> None:
        """Split a consolidated PDF into meeting records."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            pdf_path = Path(temporary_directory) / "meetings.pdf"
            self.create_pdf(pdf_path)
            document_record = read_pdf_document(pdf_path)
        self.assertEqual(document_record["page_count"], 3)
        self.assertEqual(len(document_record["meetings"]), 2)
        self.assertEqual(document_record["meetings"][0]["meeting_id"], "M01")
        self.assertEqual(document_record["meetings"][0]["source_pages"], [1, 2])
        self.assertEqual(document_record["meetings"][1]["meeting_id"], "M02")

    def test_fingerprint_is_stable(self) -> None:
        """Return the same fingerprint for unchanged content."""
        with tempfile.TemporaryDirectory() as temporary_directory:
            file_path = Path(temporary_directory) / "value.txt"
            file_path.write_text("stable", encoding="utf-8")
            first_fingerprint = calculate_file_fingerprint(file_path)
            second_fingerprint = calculate_file_fingerprint(file_path)
        self.assertEqual(first_fingerprint, second_fingerprint)

    def test_all_source_markers_are_retained(self) -> None:
        """Read multiple source markers from one consolidated page."""
        source_pages = identify_source_pages(
            "M08 / SOURCE PAGE 05 OF 15\nText\nM08 / SOURCE PAGE 06 OF 15"
        )
        self.assertEqual(source_pages, [5, 6])


if __name__ == "__main__":
    unittest.main()

