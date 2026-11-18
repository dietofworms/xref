"""Where published manifests live.

Keys look like `<project>/<environment>/manifest.json` under the store's root.
A store URL without a scheme (or with `file://`) is a local directory; any
other scheme goes through fsspec, so `s3://`, `gs://` and `az://` work once the
matching extra (`xref[s3]`, `xref[gcs]`, `xref[azure]`) is installed.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Protocol

from xref.errors import XrefError


class ManifestStore(Protocol):
    def read(self, key: str) -> bytes | None:
        """Return the object's bytes, or None when it does not exist."""
        ...

    def write(self, key: str, data: bytes) -> None: ...

    def describe(self, key: str) -> str:
        """A human-readable location for messages."""
        ...


def manifest_key(project: str, environment: str) -> str:
    return f"{project}/{environment}/manifest.json"


class LocalStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise XrefError(f"Store key {key!r} escapes the store root.")
        return path

    def read(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise XrefError(f"Could not read {path}: {exc}") from exc

    def write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        try:
            self._write(path, data)
        except OSError as exc:
            raise XrefError(f"Could not write {path}: {exc}") from exc

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a reader never sees a half-written file.
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".xref-", suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def describe(self, key: str) -> str:
        return str(self.root / key)


class FsspecStore:
    def __init__(self, url: str) -> None:
        try:
            import fsspec  # pyright: ignore[reportMissingTypeStubs]
        except ImportError:  # pragma: no cover - fsspec is a core dependency
            raise XrefError("fsspec is not installed.") from None
        protocol, _, rest = url.partition("://")
        try:
            self._fs: Any = fsspec.filesystem(protocol)  # pyright: ignore[reportUnknownMemberType]
        except (ImportError, ValueError) as exc:
            extra = {
                "s3": "s3",
                "s3a": "s3",
                "gs": "gcs",
                "gcs": "gcs",
                "az": "azure",
                "abfs": "azure",
            }.get(protocol)
            hint = f" Install it with `pip install 'xref[{extra}]'`." if extra else ""
            raise XrefError(f"Cannot open store {url}: {exc}.{hint}") from None
        self._protocol = protocol
        self._root = rest.rstrip("/")

    def _url(self, key: str) -> str:
        if ".." in key.split("/"):
            raise XrefError(f"Store key {key!r} escapes the store root.")
        return f"{self._protocol}://{self._root}/{key}"

    # Cloud SDKs raise their own exception types (botocore's NoCredentialsError,
    # for example), so anything other than "not found" becomes a XrefError here.

    def read(self, key: str) -> bytes | None:
        url = self._url(key)
        try:
            data: bytes = self._fs.cat_file(url)
            return data
        except FileNotFoundError:
            return None
        except Exception as exc:
            raise XrefError(f"Could not read {url}: {exc}") from exc

    def write(self, key: str, data: bytes) -> None:
        # Object stores have no directories, so no makedirs: writing needs only
        # put permission (s3:PutObject), and a missing bucket is never created.
        url = self._url(key)
        try:
            self._fs.pipe_file(url, data)
        except Exception as exc:
            raise XrefError(f"Could not write {url}: {exc}") from exc

    def describe(self, key: str) -> str:
        return self._url(key)


def open_store(url: str, base_dir: Path | None = None) -> ManifestStore:
    """Open a store from a URL. Relative local paths resolve against base_dir."""
    if "://" not in url or url.startswith("file://"):
        path = Path(url.removeprefix("file://")).expanduser()
        if not path.is_absolute() and base_dir is not None:
            path = base_dir / path
        return LocalStore(path)
    return FsspecStore(url)
