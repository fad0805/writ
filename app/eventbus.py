import json
import asyncio
import queue

_event_queues: list[queue.Queue] = []
_ws_queues: dict[int, queue.Queue] = {}
_ws_id_counter: int = 0

def broadcast(event: str, data: dict):
    payload = f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
    for q in _event_queues[:]:
        try:
            q.put_nowait(payload)
        except queue.Full:
            pass
    ws_payload = json.dumps({"event": event, "data": data}, default=str)
    for q in list(_ws_queues.values()):
        try:
            q.put_nowait(ws_payload)
        except queue.Full:
            pass

def add_queue(q: queue.Queue):
    _event_queues.append(q)

def remove_queue(q: queue.Queue):
    try:
        _event_queues.remove(q)
    except ValueError:
        pass

def add_ws() -> tuple[int, queue.Queue]:
    global _ws_id_counter
    _ws_id_counter += 1
    q: queue.Queue = queue.Queue(maxsize=50)
    _ws_queues[_ws_id_counter] = q
    return _ws_id_counter, q

def remove_ws(ws_id: int):
    _ws_queues.pop(ws_id, None)
