"""PaddleOCR 版本兼容解析测试。"""

from label_agent.perception.image.ocr import _major_version, _parse_v3_results


def test_parse_paddleocr_v3_result() -> None:
    results = [
        {
            "rec_texts": ["软件工程师证书", "Python 认证"],
            "rec_scores": [0.98, 0.87],
            "rec_polys": [
                [[10, 20], [210, 20], [210, 50], [10, 50]],
                [[12, 70], [180, 70], [180, 100], [12, 100]],
            ],
        }
    ]

    segments = _parse_v3_results(results, "certificate-1")

    assert [segment.text for segment in segments] == ["软件工程师证书", "Python 认证"]
    assert segments[0].asset_id == "certificate-1"
    assert segments[0].confidence == 0.98
    assert segments[0].bbox == [10.0, 20.0, 210.0, 20.0, 210.0, 50.0, 10.0, 50.0]
    assert [segment.reading_order for segment in segments] == [0, 1]


def test_major_version_is_tolerant() -> None:
    assert _major_version("3.5.0") == 3
    assert _major_version("unknown") == 0
