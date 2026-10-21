"""Export macOS Messages.app history to portable JSONL, CSV and transcripts.

>>> from imsg_export import export_history, verify_export
>>> summary = export_history("~/imessage-export")   # doctest: +SKIP
>>> verify_export("~/imessage-export").ok            # doctest: +SKIP
True
"""

from __future__ import annotations

__version__ = "0.1.0"

from .apple import (
    APPLE_EPOCH,
    apple_timestamp,
    clean_text,
    decode_attributed_body,
    iso_utc,
)
from .exporter import (
    ExportError,
    default_db_path,
    export_history,
    iter_messages,
)
from .readme import write_readme
from .verify import VerifyResult, verify_export

__all__ = [
    "APPLE_EPOCH",
    "ExportError",
    "VerifyResult",
    "__version__",
    "apple_timestamp",
    "clean_text",
    "decode_attributed_body",
    "default_db_path",
    "export_history",
    "iso_utc",
    "iter_messages",
    "verify_export",
    "write_readme",
]
