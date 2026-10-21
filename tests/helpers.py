"""Shared builders for the test suite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def apple_ns(moment: datetime) -> int:
    """Apple epoch nanoseconds for a datetime."""
    return int((moment.timestamp() - 978_307_200) * 1e9)


def minutes(count: int) -> int:
    """Apple-epoch nanoseconds `count` minutes after the fixture base time."""
    return apple_ns(BASE + timedelta(minutes=count))


def body_blob(text: str, length_prefix: bytes | None = None) -> bytes:
    """Build an attributedBody typedstream blob holding `text`."""
    payload = text.encode("utf-8")
    if length_prefix is None:
        prefix = (
            bytes([len(payload)])
            if len(payload) < 0x81
            else b"\x81" + len(payload).to_bytes(2, "little")
        )
    else:
        prefix = length_prefix
    return (
        b"\x04\x0bstreamtyped\x81\xe8\x03\x84\x01@\x84\x84\x84\x12NSString\x01\x94\x84\x01+"
        + prefix
        + payload
        + b"\x86\x84"
    )
