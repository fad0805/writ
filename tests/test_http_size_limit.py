import httpx

from app.utils import http as http_mod


class ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks, yielded=None):
        self.chunks = chunks
        self.yielded = yielded if yielded is not None else []

    def __iter__(self):
        for chunk in self.chunks:
            self.yielded.append(1)
            yield chunk


def _mock_client(monkeypatch, handler):
    real_client = httpx.Client

    def factory(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(http_mod.httpx, "Client", factory)
    monkeypatch.setattr(http_mod, "validate_url", lambda url: True)
    monkeypatch.setattr(http_mod, "federation_allowed", lambda domain: True)


def _big_response(yielded):
    return httpx.Response(200, stream=ChunkStream([b"x" * 100] * 5, yielded))


def test_safe_fetch_stops_reading_oversized_body(monkeypatch):
    yielded = []
    _mock_client(monkeypatch, lambda request: _big_response(yielded))

    assert http_mod.safe_fetch("https://example.com/big", max_size=10) is None
    # 101바이트째에 중단했으므로 첫 청크만 읽어야 한다.
    assert len(yielded) == 1


def test_safe_fetch_caches_small_body(monkeypatch):
    _mock_client(
        monkeypatch,
        lambda request: httpx.Response(200, stream=ChunkStream([b"hello"])),
    )

    resp = http_mod.safe_fetch("https://example.com/ok", max_size=10)
    assert resp is not None
    assert resp.content == b"hello"


def test_validated_get_stops_reading_oversized_body(monkeypatch):
    yielded = []
    _mock_client(monkeypatch, lambda request: _big_response(yielded))

    assert http_mod.validated_get("https://example.com/big", max_size=10) is None
    assert len(yielded) == 1
