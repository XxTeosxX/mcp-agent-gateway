from datetime import date

from app.integrations.google.drive_query import build_drive_query


def test_full_text_clause_and_default_trashed():
    q = build_drive_query(full_text="proposals")
    assert q == "fullText contains 'proposals' and trashed = false"


def test_name_contains_clause():
    q = build_drive_query(name_contains="report")
    assert q == "name contains 'report' and trashed = false"


def test_mime_type_clause():
    q = build_drive_query(mime_type="application/pdf")
    assert q == "mimeType = 'application/pdf' and trashed = false"


def test_in_folder_clause():
    q = build_drive_query(in_folder="FOLDER123")
    assert q == "'FOLDER123' in parents and trashed = false"


def test_modified_after_clause():
    q = build_drive_query(modified_after=date(2025, 1, 1))
    assert q == "modifiedTime > '2025-01-01T00:00:00' and trashed = false"


def test_multiple_clauses_joined_with_and():
    q = build_drive_query(name_contains="plan", mime_type="application/pdf")
    assert q == "name contains 'plan' and mimeType = 'application/pdf' and trashed = false"


def test_include_trashed_omits_trashed_clause():
    q = build_drive_query(full_text="x", include_trashed=True)
    assert q == "fullText contains 'x'"


def test_escapes_single_quote():
    q = build_drive_query(name_contains="O'Brien")
    assert q == "name contains 'O\\'Brien' and trashed = false"


def test_escapes_backslash_before_quote():
    q = build_drive_query(name_contains="a\\b'c")
    assert q == "name contains 'a\\\\b\\'c' and trashed = false"
