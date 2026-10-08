"""CAS backend for an isolated local website served by a test HTTP server."""
import os
from pathlib import Path
import tempfile

from .html_updater import digest
from .lifecycle import http_health


class FileBackend:
    def __init__(self, path: Path, url: str):
        self.path = path.resolve()
        self.url = url

    def read(self) -> str:
        return self.path.read_bytes().decode("utf-8")

    def publish(self, content: str, expected_hash: str) -> str:
        lock = self.path.with_suffix(self.path.suffix + ".deployment-lock")
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        temporary = None
        try:
            if digest(self.read()) != expected_hash:
                raise ValueError("Base changed during publication")
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(content.encode("utf-8"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            return digest(content)
        finally:
            os.close(descriptor)
            lock.unlink()
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def healthy(self, content: str) -> bool:
        return http_health(self.url, content)
