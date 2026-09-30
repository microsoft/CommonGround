"""Run synchronous AI callers on a persistent asyncio event loop."""
import asyncio
import atexit
import logging
import threading
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from typing import Any, Coroutine, Optional, TypeVar


logger = logging.getLogger(__name__)
T = TypeVar('T')


class AsyncExecutor:
    """Execute coroutines on one lazily started background event loop."""

    def __init__(self):
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._closed = False

    @property
    def is_running(self) -> bool:
        return self.loop is not None and self.loop.is_running()

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.run_until_complete(loop.shutdown_default_executor())
            finally:
                loop.close()
                asyncio.set_event_loop(None)

    def _submit(self, coro: Coroutine[Any, Any, T]) -> Future[T]:
        if not asyncio.iscoroutine(coro):
            raise TypeError('An asyncio coroutine is required')
        with self._lock:
            if self._closed:
                coro.close()
                raise RuntimeError('The AI async executor has been shut down')
            if self.loop is None:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(
                    target=self._run_loop, args=(loop,),
                    name='commonground-ai', daemon=True,
                )
                try:
                    thread.start()
                except RuntimeError:
                    loop.close()
                    coro.close()
                    raise
                self.loop = loop
                self.thread = thread
            return asyncio.run_coroutine_threadsafe(coro, self.loop)

    def run_async(self, coro: Coroutine[Any, Any, T], timeout: Optional[float] = None) -> T:
        """Wait for a coroutine without closing its event loop afterwards."""
        if threading.current_thread() is self.thread:
            coro.close()
            raise RuntimeError("Cannot wait synchronously on the executor's own event loop")
        future = self._submit(coro)
        try:
            return future.result(timeout=timeout)
        except FutureTimeoutError:
            future.cancel()
            raise

    def run_async_in_background(self, coro, callback):
        """Run a coroutine in the same event loop and report its result."""
        def _run():
            try:
                result = self.run_async(coro)
            except Exception:
                logger.exception('Background async error')
                result = None
            callback(result)

        threading.Thread(target=_run, daemon=True).start()

    def shutdown(self, timeout: float = 5.0) -> None:
        """Stop accepting work, cancel pending tasks, and close the loop."""
        with self._lock:
            if threading.current_thread() is self.thread:
                raise RuntimeError("Cannot shut down the executor from its own event loop")
            already_closed = self._closed
            self._closed = True
            loop, thread = self.loop, self.thread
        if loop is None or thread is None:
            return
        if not already_closed and not loop.is_closed():
            loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise TimeoutError('The AI event loop did not stop before the shutdown timeout')


_shared_executor = AsyncExecutor()
atexit.register(_shared_executor.shutdown)


def get_async_executor() -> AsyncExecutor:
    """Share loop ownership across sessions that reuse the global AI client."""
    return _shared_executor
