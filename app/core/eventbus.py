import asyncio
import contextlib
import json

_main_loop: asyncio.AbstractEventLoop | None = None
_event_queues: list[asyncio.Queue] = []
_ws_queues: dict[int, asyncio.Queue] = {}
_ws_id_counter: int = 0

def _set_loop():
    global _main_loop
    if _main_loop is None:
        try:
            _main_loop = asyncio.get_running_loop()
        except RuntimeError:
            _main_loop = asyncio.get_event_loop()

def _enqueue(q: asyncio.Queue, item: str):
    if _main_loop and _main_loop.is_running():
        _main_loop.call_soon_threadsafe(q.put_nowait, item)
    else:
        with contextlib.suppress(asyncio.QueueFull):
            q.put_nowait(item)

def broadcast(event: str, data: dict):
    payload = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
    for q in _event_queues[:]:
        _enqueue(q, payload)
    ws_payload = json.dumps({"event": event, "data": data}, default=str)
    for q in list(_ws_queues.values()):
        _enqueue(q, ws_payload)

def add_queue(q: asyncio.Queue):
    _set_loop()
    _event_queues.append(q)

def remove_queue(q: asyncio.Queue):
    with contextlib.suppress(ValueError):
        _event_queues.remove(q)

def add_ws() -> tuple[int, asyncio.Queue]:
    global _ws_id_counter
    _set_loop()
    _ws_id_counter += 1
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _ws_queues[_ws_id_counter] = q
    return _ws_id_counter, q

def remove_ws(ws_id: int):
    _ws_queues.pop(ws_id, None)
