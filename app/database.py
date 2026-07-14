from app.models import Session, engine


def get_db():
    db = Session(engine, expire_on_commit=False)
    try:
        yield db
    finally:
        db.close()
