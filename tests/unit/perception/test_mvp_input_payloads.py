"""MVP CLI 多文件输入组装为 attachments。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPTS_DIR = Path(__file__).resolve().parents[3] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from mvp_common import read_input_payload, read_input_payloads  # noqa: E402


def test_single_image_keeps_legacy_field(tmp_path: Path) -> None:
    image = tmp_path / "a.png"
    image.write_bytes(b"png")
    assert read_input_payloads([image]) == {"image_path": str(image)}
    assert read_input_payload(image) == {"image_path": str(image)}


def test_multiple_images_become_attachments(tmp_path: Path) -> None:
    first = tmp_path / "a.png"
    second = tmp_path / "b.jpg"
    first.write_bytes(b"png")
    second.write_bytes(b"jpg")
    assert read_input_payloads([first, second]) == {
        "attachments": [
            {"type": "image", "path": str(first)},
            {"type": "image", "path": str(second)},
        ]
    }


def test_reject_payload_mixed_with_files(tmp_path: Path) -> None:
    image = tmp_path / "a.png"
    payload = tmp_path / "job.json"
    image.write_bytes(b"png")
    payload.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit, match="JSON/YAML"):
        read_input_payloads([image, payload])
