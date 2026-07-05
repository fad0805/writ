import json
import asyncio

_event_queues: list[asyncio.Queue] = []

def broadcast(event: str, data: dict):
    payload = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
    for q in _event_queues[:]:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass

def add_queue(q: asyncio.Queue):
    _event_queues.append(q)

def remove_queue(q: asyncio.Queue):
    try:
        _event_queues.remove(q)
    except ValueError:
        pass
