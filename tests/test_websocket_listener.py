import asyncio
import logging
import threading

import pytest

from liualgotrader.common.websocket_listener import WebSocketListener

server = pytest.importorskip("websockets.asyncio.server")

logger = logging.getLogger(__name__)


class SilentServer:
    """A WebSocket server, in a thread, that greets and then stays silent."""

    def __init__(self, close_after_greeting: bool = False):
        self.close_after_greeting = close_after_greeting
        self.port: int = 0
        self._ready = threading.Event()
        self._stop: asyncio.Future
        self._thread = threading.Thread(
            target=asyncio.run, args=(self._run(),)
        )

    async def _handler(self, connection):
        await connection.send("hello")
        if self.close_after_greeting:
            await connection.close()
        await connection.wait_closed()

    async def _run(self):
        self._stop = asyncio.get_running_loop().create_future()
        async with server.serve(self._handler, "127.0.0.1", 0) as ws_server:
            self.port = ws_server.sockets[0].getsockname()[1]
            self._ready.set()
            await self._stop

    def __enter__(self):
        self._thread.start()
        self._ready.wait(5)
        return self

    def __exit__(self, *exc):
        self._stop.get_loop().call_soon_threadsafe(self._stop.set_result, None)
        self._thread.join(5)


def start_listener(port: int):
    events: list = []
    listener = WebSocketListener(
        f"ws://127.0.0.1:{port}",
        on_message=lambda ws, message: events.append(("message", message)),
        on_error=lambda ws, error: events.append(("error", error)),
        on_close=lambda ws, code, message: events.append(("close", code)),
    )
    return listener, events


async def wait_for_message(events: list) -> None:
    for _ in range(50):
        if ("message", "hello") in events:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"no message received, events {events}")


@pytest.mark.asyncio
async def test_stop_ends_listener_while_server_is_silent():
    logger.info("test_stop_ends_listener_while_server_is_silent")
    with SilentServer() as silent:
        listener, events = start_listener(silent.port)
        await wait_for_message(events)

        await asyncio.wait_for(listener.stop(), 5)

    if not listener.task.done():
        raise AssertionError("listener still running after stop")
    if any(event[0] == "error" for event in events):
        raise AssertionError(f"stop reported an error, events {events}")
    if events[-1][0] != "close":
        raise AssertionError(f"on_close not called, events {events}")


@pytest.mark.asyncio
async def test_stop_after_server_closes():
    logger.info("test_stop_after_server_closes")
    with SilentServer(close_after_greeting=True) as closing:
        listener, events = start_listener(closing.port)
        await wait_for_message(events)
        await asyncio.wait_for(asyncio.shield(listener.task), 5)

        await asyncio.wait_for(listener.stop(), 5)

    if events.count(("close", 1000)) != 1:
        raise AssertionError(f"expected one normal close, events {events}")
