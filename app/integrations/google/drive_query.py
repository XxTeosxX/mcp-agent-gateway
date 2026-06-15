from datetime import date


def _escape(literal: str) -> str:
    """Escape a string literal for a Google Drive `q` value.

    Order matters: escape backslashes before single quotes so an already
    escaped quote is not double-counted.
    """
    return literal.replace("\\", "\\\\").replace("'", "\\'")


def build_drive_query(
    *,
    name_contains: str | None = None,
    full_text: str | None = None,
    mime_type: str | None = None,
    in_folder: str | None = None,
    modified_after: date | None = None,
    include_trashed: bool = False,
) -> str:
    """Compose a safe Google Drive `q` string from structured filters.

    Callers never write Drive query syntax; every string literal is escaped.
    """
    clauses: list[str] = []
    if name_contains:
        clauses.append(f"name contains '{_escape(name_contains)}'")
    if full_text:
        clauses.append(f"fullText contains '{_escape(full_text)}'")
    if mime_type:
        clauses.append(f"mimeType = '{_escape(mime_type)}'")
    if in_folder:
        clauses.append(f"'{_escape(in_folder)}' in parents")
    if modified_after:
        clauses.append(f"modifiedTime > '{modified_after.isoformat()}T00:00:00'")
    if not include_trashed:
        clauses.append("trashed = false")
    return " and ".join(clauses)
