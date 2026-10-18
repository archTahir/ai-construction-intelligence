import hashlib
import re
from pathlib import Path

import pymupdf


MEETING_PATTERN = re.compile(
    r"Meeting\s+(M\d+)\s*\|\s*(\d{2}/\d{2}/\d{4})",
    re.IGNORECASE,
)
SOURCE_PAGE_PATTERN = re.compile(
    r"M\d+\s*/\s*SOURCE PAGE\s+(\d+)\s+OF\s+(\d+)",
    re.IGNORECASE,
)


def calculate_file_fingerprint(file_path: str | Path) -> str:
    """Calculate the SHA-256 fingerprint of a file."""
    file_fingerprint = hashlib.sha256()
    with Path(file_path).open("rb") as file_stream:
        for file_block in iter(lambda: file_stream.read(1024 * 1024), b""):
            file_fingerprint.update(file_block)
    return file_fingerprint.hexdigest()


def extract_pdf_pages(file_path: str | Path) -> list[dict]:
    """Extract text and page metadata from a text-based PDF."""
    extracted_pages = []
    with pymupdf.open(file_path) as pdf_document:
        for page_index, pdf_page in enumerate(pdf_document, start=1):
            page_text = pdf_page.get_text("text", sort=True).strip()
            extracted_pages.append(
                {
                    "pdf_page": page_index,
                    "text": page_text,
                    "character_count": len(page_text),
                }
            )
    return extracted_pages


def identify_source_pages(page_text: str) -> list[int]:
    """Read every original source-page marker from extracted page text."""
    return [
        int(source_page_match.group(1))
        for source_page_match in SOURCE_PAGE_PATTERN.finditer(page_text)
    ]


def build_meeting_record(
    meeting_id: str,
    meeting_date: str | None,
    meeting_pages: list[dict],
) -> dict:
    """Build one meeting record from a contiguous set of PDF pages."""
    text_sections = []
    source_pages = []
    for meeting_page in meeting_pages:
        page_source_pages = identify_source_pages(meeting_page["text"])
        source_pages.extend(page_source_pages)
        source_label = (
            ", ".join(str(source_page) for source_page in page_source_pages)
            if page_source_pages
            else meeting_page["pdf_page"]
        )
        text_sections.append(
            f"\n===== SOURCE PAGE {source_label} | PDF PAGE {meeting_page['pdf_page']} =====\n"
            f"{meeting_page['text']}"
        )
    return {
        "meeting_id": meeting_id,
        "meeting_date": meeting_date,
        "pdf_pages": [meeting_page["pdf_page"] for meeting_page in meeting_pages],
        "source_pages": list(dict.fromkeys(source_pages)),
        "page_count": len(meeting_pages),
        "text": "\n".join(text_sections).strip(),
        "analysis_status": "pending",
    }


def split_meetings(extracted_pages: list[dict], file_stem: str) -> list[dict]:
    """Split PDF pages into chronological meeting records."""
    meeting_records = []
    current_meeting_id = None
    current_meeting_date = None
    current_meeting_pages = []

    for extracted_page in extracted_pages:
        meeting_match = MEETING_PATTERN.search(extracted_page["text"])
        if meeting_match and current_meeting_pages:
            meeting_records.append(
                build_meeting_record(
                    current_meeting_id,
                    current_meeting_date,
                    current_meeting_pages,
                )
            )
            current_meeting_pages = []

        if meeting_match:
            current_meeting_id = meeting_match.group(1).upper()
            current_meeting_date = meeting_match.group(2)

        if current_meeting_id:
            current_meeting_pages.append(extracted_page)

    if current_meeting_pages:
        meeting_records.append(
            build_meeting_record(
                current_meeting_id,
                current_meeting_date,
                current_meeting_pages,
            )
        )

    if meeting_records:
        return meeting_records

    fallback_meeting_id = re.sub(r"[^A-Za-z0-9]+", "-", file_stem).strip("-").upper()
    return [build_meeting_record(fallback_meeting_id or "MEETING-001", None, extracted_pages)]


def read_pdf_document(file_path: str | Path) -> dict:
    """Read a PDF and return its fingerprint, pages and meeting boundaries."""
    resolved_file_path = Path(file_path).expanduser().resolve()
    extracted_pages = extract_pdf_pages(resolved_file_path)
    if not extracted_pages:
        raise ValueError("The selected PDF contains no pages.")
    if not any(page["text"] for page in extracted_pages):
        raise ValueError("The selected PDF has no extractable text.")
    file_fingerprint = calculate_file_fingerprint(resolved_file_path)
    return {
        "document_id": f"DOC-{file_fingerprint[:12].upper()}",
        "file_name": resolved_file_path.name,
        "file_path": str(resolved_file_path),
        "fingerprint": file_fingerprint,
        "page_count": len(extracted_pages),
        "meetings": split_meetings(extracted_pages, resolved_file_path.stem),
    }
