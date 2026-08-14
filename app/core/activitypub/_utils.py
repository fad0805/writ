from app.config.settings import SECRET_KEY
from app.models import User
from app.utils.crypto import encrypt_key, generate_keypair


def _get_instance_actor(session) -> User:
    """Get or create the instance actor (system account for server-level requests)."""
    actor = session.query(User).filter_by(username="actor", is_remote=False).first()
    if not actor:
        priv, pub = generate_keypair()
        actor = User(
            username="actor",
            display_name="(instance actor)",
            password_hash="",
            private_key=encrypt_key(priv, SECRET_KEY),
            public_key=pub,
            is_remote=False,
            is_admin=False,
            role="actor",
        )
        session.add(actor)
        session.commit()
    return actor
