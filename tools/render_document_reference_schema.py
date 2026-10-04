"""Render the mirrored document/reference schema operator document."""

from __future__ import annotations

from pathlib import Path

from projectkoios.references.adapters.sql.sqlite import (
    document_reference_schema,
)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DocumentReferenceSchema = document_reference_schema.DocumentReferenceSchema
DEFAULT_OUTPUT_PATH = _REPOSITORY_ROOT / "docs/document-reference-schema.md"


def render_document_reference_schema() -> str:
    """Return the checked-in Markdown representation of the schema."""
    rules = "\n".join(f"- {rule}" for rule in DocumentReferenceSchema.RULES)
    table_names = "\n".join(
        f"- `{name}`" for name in DocumentReferenceSchema.TABLE_NAMES
    )
    checks = "\n".join(
        (
            f"### {label}\n\n"
            f"```sql\n{query}\n```\n\n"
            f"Expected rows: `{expected!r}`"
        )
        for label, query, expected in (
            DocumentReferenceSchema.VERIFICATION_QUERIES
        )
    )
    return f"""# Document/reference schema

This document mirrors the executable empty-database schema owned by
`projectkoios.references.adapters.sql.sqlite.document_reference_schema`.
The Python module is authoritative; regenerate this file with:

```bash
uv run python tools/render_document_reference_schema.py
```

The database is parallel storage only. The schema-5 catalog remains
authoritative until an explicit cutover.

## Invariants

{rules}

## Application tables

{table_names}

## Bootstrap SQL

```sql
{DocumentReferenceSchema.BOOTSTRAP_SQL}```

## Verification queries

{checks}
"""


def main() -> None:
    """Write the mirrored document."""
    DEFAULT_OUTPUT_PATH.write_text(
        render_document_reference_schema(),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
