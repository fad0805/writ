import base64
import hashlib
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
from cryptography.fernet import Fernet


def generate_keypair():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    priv_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    pub_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return priv_pem, pub_pem


def _fernet(secret: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_key(plaintext: str, secret: str) -> str:
    return _fernet(secret).encrypt(plaintext.encode()).decode()


def decrypt_key(ciphertext: str, secret: str) -> str:
    try:
        return _fernet(secret).decrypt(ciphertext.encode()).decode()
    except Exception:
        return ciphertext


def get_private_key(user, secret: str) -> str:
    return decrypt_key(user.private_key, secret)


def sign_string(text: str, private_key_pem: str) -> str:
    private_key = serialization.load_pem_private_key(
        private_key_pem.encode("utf-8"),
        password=None,
        backend=default_backend(),
    )
    signature = private_key.sign(
        text.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def verify_signature(text: str, signature_b64: str, public_key_pem: str) -> bool:
    try:
        public_key = serialization.load_pem_public_key(
            public_key_pem.encode("utf-8"),
            backend=default_backend(),
        )
        signature = base64.b64decode(signature_b64)
        public_key.verify(
            signature,
            text.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception:
        return False
