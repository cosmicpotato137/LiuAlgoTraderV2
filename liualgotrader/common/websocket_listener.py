"""Listen on a websocket-client connection from asynchronous code.

Classes
-------
WebSocketListener
    A WebSocket connection that a worker thread listens on, as a task.
"""

import asyncio
from typing import Any, Callable, Dict, Optional

import websocket


class WebSocketListener:
    """A WebSocket connection that a worker thread listens on, as a task.

    A websocket-client application blocks while it listens, so the listener
    runs it in a worker thread of the running event loop, and the callbacks
    run in that thread.

    Attributes
    ----------
    ws: websocket.WebSocketApp
        The WebSocket application.
    task: asyncio.Task
        The task that runs the application until the connection closes.

    Methods
    -------
    stop
        Close the connection and wait until the listener ends.
    """

    def __init__(
        self,
        url: str,
        on_message: Callable,
        on_error: Callable,
        on_close: Callable,
        header: Optional[Dict[str, str]] = None,
        **run_options: Any,
    ):
        """Connect to a URL and start listening.

        Must be called from a coroutine.

        Parameters
        ----------
        url: str
            The WebSocket URL.
        on_message: Callable
            Called with the application and each message received.
        on_error: Callable
            Called with the application and each error.
        on_close: Callable
            Called with the application, the close status code and the close
            message once the connection closes.
        header: Optional[Dict[str, str]], default None
            The headers of the opening handshake.
        run_options
            The keyword arguments of WebSocketApp.run_forever, such as
            sslopt.
        """
        self.ws = websocket.WebSocketApp(
            url,
            header=header,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        self.task = asyncio.create_task(
            asyncio.to_thread(self.ws.run_forever, **run_options)
        )

    async def stop(self) -> None:
        """Close the connection and wait until the listener ends.

        Close it in a worker thread, since closing waits up to three seconds
        for the server to acknowledge.
        """
        await asyncio.to_thread(self.ws.close)
        await self.task
