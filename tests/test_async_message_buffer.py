from __future__ import annotations

import asyncio

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
