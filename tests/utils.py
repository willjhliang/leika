"""Helpers shared by the unit tests."""

from __future__ import annotations

import msgspec.msgpack

from leika._messages import MESSAGE_TYPES, Message, _record_from_wire
from leika._transport._message_buffer import AsyncMessageBuffer


def queued_messages(buffer: AsyncMessageBuffer) -> dict[int, Message]:
    """Decode a buffer's queued or, when persistent, retained messages by ID.

    The buffer keeps only encoded bytes, so this returns what a browser would
    read: tuples inside dynamic ``updates`` values arrive as lists. Unlike
    browser input, server output is decoded without size bounds.
    """
    with buffer._lock:
        records = dict(buffer._queued)
    decoded = {}
    for message_id, record in records.items():
        mapping = msgspec.msgpack.decode(record.data)
        decoded[message_id] = _record_from_wire(MESSAGE_TYPES[mapping.pop("type")], mapping)
    return decoded
