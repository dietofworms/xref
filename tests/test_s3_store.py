"""The S3 store against a local moto S3 server, through s3fs as in production."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import boto3
import pytest
from moto.server import ThreadedMotoServer
from mypy_boto3_s3 import S3Client
from typer.testing import CliRunner

from tests.conftest import manifest_dict, model_node, write_manifest
from uey.cli import app
from uey.errors import UeyError
from uey.store import FsspecStore, open_store

BUCKET = "uey-test"


def _client() -> S3Client:
    return boto3.client("s3")  # pyright: ignore[reportUnknownMemberType]


@pytest.fixture
def s3(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    server = ThreadedMotoServer(port=0, verbose=False)
    server.start()
    host, port = server.get_host_and_port()
    monkeypatch.setenv("AWS_ENDPOINT_URL", f"http://{host}:{port}")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    _client().create_bucket(Bucket=BUCKET)
    # fsspec caches filesystem instances; clear so each test sees this server.
    import s3fs  # pyright: ignore[reportMissingTypeStubs]

    s3fs.S3FileSystem.clear_instance_cache()
    yield f"s3://{BUCKET}/uey"
    server.stop()


def test_s3_round_trip(s3: str) -> None:
    store = open_store(s3)
    assert isinstance(store, FsspecStore)
    assert store.read("core/prod/manifest.json") is None
    store.write("core/prod/manifest.json", b"{}")
    assert store.read("core/prod/manifest.json") == b"{}"
    listing = _client().list_objects_v2(Bucket=BUCKET)
    keys = [o.get("Key") for o in listing.get("Contents", [])]
    assert keys == ["uey/core/prod/manifest.json"]


def test_publish_and_sync_through_s3(s3: str, tmp_path: Path) -> None:
    producer = tmp_path / "core"
    producer.mkdir()
    (producer / "dbt_project.yml").write_text("name: core\n")
    write_manifest(producer / "target" / "manifest.json", manifest_dict(model_node("orders")))
    consumer = tmp_path / "consumer"
    consumer.mkdir()
    (consumer / "dbt_project.yml").write_text("name: consumer\n")
    (consumer / "uey.yml").write_text(f"store: {s3}\nprojects: [core]\n")

    runner = CliRunner()
    result = runner.invoke(app, ["publish", "--project-dir", str(producer), "--store", s3])
    assert result.exit_code == 0, result.output
    body = _client().get_object(Bucket=BUCKET, Key="uey/core/prod/manifest.json")["Body"]
    assert json.loads(body.read())["project_name"] == "core"

    result = runner.invoke(app, ["sync", "--project-dir", str(consumer)])
    assert result.exit_code == 0, result.output
    assert (consumer / ".mesh" / "core" / "models" / "orders.sql").exists()


def test_missing_bucket_write_is_a_clear_error(s3: str) -> None:
    store = open_store("s3://uey-no-such-bucket/uey")
    with pytest.raises(UeyError, match="Could not write s3://uey-no-such-bucket/uey/k"):
        store.write("k", b"x")
