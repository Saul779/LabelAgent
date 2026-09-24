"""S4 商品类目工作簿导入测试。"""

from __future__ import annotations

from pathlib import Path

from label_agent.infrastructure.taxonomy.product_taxonomy import ProductTaxonomyImporter

_WORKBOOK = Path(__file__).resolve().parents[3] / "docs" / "在场电商平台商品分类信息.xlsx"


def test_imports_expected_taxonomy_snapshot_with_stable_ids() -> None:
    importer = ProductTaxonomyImporter()
    first = importer.load(_WORKBOOK)
    second = importer.load(_WORKBOOK)

    assert len(first.level1) == 41
    assert len(first.level2) == 259
    assert first.version == second.version
    assert [item.category_id for item in first.level2] == [
        item.category_id for item in second.level2
    ]
    assert all(first.parent_of(item.category_id) is not None for item in first.level2)


def test_same_level2_name_under_different_parents_has_different_ids() -> None:
    taxonomy = ProductTaxonomyImporter().load(_WORKBOOK)
    office_furniture = [item for item in taxonomy.level2 if item.category_name == "办公家具"]
    mobile_accessories = [item for item in taxonomy.level2 if item.category_name == "手机配件"]

    assert len(office_furniture) == 2
    assert len({item.category_id for item in office_furniture}) == 2
    assert len({item.parent_category_id for item in office_furniture}) == 2
    assert len(mobile_accessories) == 2
    assert len({item.category_id for item in mobile_accessories}) == 2


def test_persists_versioned_name_id_snapshot(tmp_path: Path) -> None:
    importer = ProductTaxonomyImporter()
    taxonomy = importer.load(_WORKBOOK)

    first = importer.persist_snapshot(taxonomy, tmp_path)
    second = importer.persist_snapshot(taxonomy, tmp_path)

    assert first == second
    assert first.name == f"{taxonomy.version}.json"
    content = first.read_text(encoding="utf-8")
    assert taxonomy.level2[0].category_id in content
