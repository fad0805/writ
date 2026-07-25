from app.models import Session, engine, _request_session


def get_db():
    """FastAPI Depends용 - 요청마다 세션을 생성하고 자동으로 닫는다."""
    sess = Session(engine, expire_on_commit=False)
    _request_session.set(sess)
    try:
        yield sess
    finally:
        _request_session.set(None)
        sess.close()
