from __future__ import annotations

import asyncio

from leika._messages import ClientPingMessage
from leika.infra._async_message_buffer import AsyncMessageBuffer


def test_window_generator_cleans_up_flush_wait() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(asyncio.get_running_loop(), persistent_messages=False)
        generator = buffer.window_generator(client_id=0)
        next_window = asyncio.create_task(generator.__anext__())
        await asyncio.sleep(0)

        buffer.set_done()
        try:
            await next_window
        except StopAsyncIteration:
            pass

        current = asyncio.current_task()
        assert [task for task in asyncio.all_tasks() if task is not current] == []

    asyncio.run(run())


def test_closed_buffer_discards_queued_messages_and_rejects_new_ones() -> None:
    async def run() -> None:
        buffer = AsyncMessageBuffer(
            asyncio.get_running_loop(),
            persistent_messages=False,
        )
        assert buffer.push(ClientPingMessage(sent_ms=0.0)) is True
        assert len(buffer.message_from_id) == 1

        buffer.set_done()

        assert buffer.push(ClientPingMessage(sent_ms=1.0)) is False
        assert buffer.message_from_id == {}
        assert buffer.id_from_redundancy_key == {}

    asyncio.run(run())
