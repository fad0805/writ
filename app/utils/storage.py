import os
import logging
from abc import ABC, abstractmethod
from urllib.parse import urlparse

logger = logging.getLogger("writ.storage")


class StorageBackend(ABC):
    @abstractmethod
    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        ...

    @abstractmethod
    def delete(self, url_or_key: str) -> bool:
        ...

    @abstractmethod
    def get(self, key: str) -> bytes:
        ...

    @abstractmethod
    def exists(self, key: str) -> bool:
        ...

    @abstractmethod
    def url(self, key: str) -> str:
        ...


class LocalStorage(StorageBackend):
    def __init__(self, base_dir: str = "uploads", url_prefix: str = "/uploads"):
        self.base_dir = os.path.abspath(base_dir)
        self.url_prefix = url_prefix.rstrip("/")

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        filepath = os.path.join(self.base_dir, key)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "wb") as f:
            f.write(data)
        return self.url(key)

    def delete(self, url_or_key: str) -> bool:
        path = self._extract_path(url_or_key)
        if path and os.path.isfile(path):
            os.remove(path)
            return True
        return False

    def get(self, key: str) -> bytes:
        filepath = os.path.join(self.base_dir, key)
        if os.path.isfile(filepath):
            with open(filepath, "rb") as f:
                return f.read()
        raise FileNotFoundError(filepath)

    def exists(self, key: str) -> bool:
        return os.path.isfile(os.path.join(self.base_dir, key))

    def url(self, key: str) -> str:
        return f"{self.url_prefix}/{key}"

    def _extract_path(self, url_or_key: str) -> str | None:
        if url_or_key.startswith("/"):
            parsed = urlparse(url_or_key)
            prefix = self.url_prefix + "/"
            if parsed.path.startswith(prefix):
                key = parsed.path[len(prefix):]
                return os.path.join(self.base_dir, key)
            return None
        return os.path.join(self.base_dir, url_or_key)

    def list_keys(self, prefix: str = "") -> list[str]:
        dir_path = os.path.join(self.base_dir, prefix)
        if not os.path.isdir(dir_path):
            return []
        result = []
        for root, _dirs, files in os.walk(dir_path):
            for fname in files:
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, self.base_dir)
                result.append(rel)
        return result

    def mtime(self, key: str) -> float | None:
        path = os.path.join(self.base_dir, key)
        if os.path.isfile(path):
            return os.path.getmtime(path)
        return None


class S3Storage(StorageBackend):
    def __init__(self, endpoint: str, region: str, access_key: str, secret_key: str,
                 bucket: str, public_url: str = ""):
        import boto3
        self.bucket = bucket
        self.endpoint = endpoint.rstrip("/")
        self.public_url = public_url.rstrip("/") if public_url else self.endpoint
        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self.client = session.client("s3", endpoint_url=endpoint)

    def save(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        return self.url(key)

    def delete(self, url_or_key: str) -> bool:
        key = self._url_to_key(url_or_key)
        if not key:
            return False
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            logger.warning("S3 delete failed for %s: %s", key, e)
            return False

    def get(self, key: str) -> bytes:
        import io
        resp = self.client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def url(self, key: str) -> str:
        return f"{self.public_url}/{key}"

    def _url_to_key(self, url_or_key: str) -> str | None:
        if not url_or_key.startswith("http"):
            return url_or_key
        parsed = urlparse(url_or_key)
        path = parsed.path.lstrip("/")
        if path.startswith(self.bucket + "/"):
            path = path.removeprefix(self.bucket + "/")
        return path if path else None


def get_storage() -> StorageBackend:
    from app.config import (
        S3_ENABLED,
        S3_ENDPOINT, S3_REGION, S3_ACCESS_KEY, S3_SECRET_KEY,
        S3_BUCKET, S3_PUBLIC_URL,
    )
    if S3_ENABLED:
        return S3Storage(
            endpoint=S3_ENDPOINT,
            region=S3_REGION,
            access_key=S3_ACCESS_KEY,
            secret_key=S3_SECRET_KEY,
            bucket=S3_BUCKET,
            public_url=S3_PUBLIC_URL,
        )
    return LocalStorage(base_dir="uploads", url_prefix="/uploads")
