"""Shared builders for the test suite."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

BASE = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

#: Minimal chat.db schema: every column the exporter reads, nothing more.
SCHEMA = """
create table message (
    ROWID integer primary key, guid text, text text, attributedBody blob,
    handle_id integer, service text, account text, date integer, date_read integer,
    is_from_me integer, is_read integer, is_sent integer, is_delivered integer,
    item_type integer, cache_has_attachments integer, associated_message_type integer,
    associated_message_guid text, associated_message_emoji text, balloon_bundle_id text,
    reply_to_guid text, thread_originator_guid text, date_edited integer,
    date_retracted integer, is_spam integer, is_system_message integer,
    expressive_send_style_id text, group_title text
);
create table handle (ROWID integer primary key, id text, service text, country text);
create table chat (
    ROWID integer primary key, guid text, chat_identifier text,
    display_name text, service_name text
);
create table chat_message_join (chat_id integer, message_id integer);
create table chat_handle_join (chat_id integer, handle_id integer);
create table attachment (
    ROWID integer primary key, guid text, filename text, uti text, mime_type text,
    transfer_name text, total_bytes integer, is_sticker integer, hide_attachment integer
);
create table message_attachment_join (message_id integer, attachment_id integer);
"""


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
