"""从 S4 商品类目工作簿加载不可变、具稳定 ID 的内存快照。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from label_agent.domain.models.s4_product import ProductCategoryRecord

_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class ProductTaxonomy:
    """校验后的商品类目快照；二级类目是唯一可检索叶子。"""

    def __init__(self, records: list[ProductCategoryRecord], *, version: str) -> None:
        self.version = version
        self.records = tuple(records)
        self._by_id = {record.category_id: record for record in records}
        self.level1 = tuple(record for record in records if record.level == 1)
        self.level2 = tuple(record for record in records if record.level == 2)

    def get(self, category_id: str | None) -> ProductCategoryRecord | None:
        return self._by_id.get(category_id or "")

    def parent_of(self, level2_id: str | None) -> ProductCategoryRecord | None:
        child = self.get(level2_id)
        if child is None or child.level != 2:
            return None
        parent = self.get(child.parent_category_id)
        return parent if parent is not None and parent.level == 1 else None


class ProductTaxonomyImporter:
    """读取 XLSX 前两列并生成内容确定性的稳定 ID/版本。

    ID 由完整业务键的 SHA-256 生成，表格重排不会改变 ID；版本由所有规范化路径
    的有序集合生成。生产环境可将相同结构持久化到类目主数据服务。
    """

    def load(self, path: str | Path) -> ProductTaxonomy:
        workbook = Path(path)
        rows = self._read_first_sheet(workbook)
        if not rows:
            raise ValueError(f"商品类目工作簿为空: {workbook}")
        header = tuple(value.strip() for value in rows[0][:2])
        if header != ("一级分类", "二级分类"):
            raise ValueError(f"商品类目表头必须为 一级分类/二级分类，实际为: {header}")

        paths: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for row_number, row in enumerate(rows[1:], start=2):
            level1 = row[0].strip() if len(row) > 0 else ""
            level2 = row[1].strip() if len(row) > 1 else ""
            if not level1 or not level2:
                raise ValueError(f"商品类目第 {row_number} 行存在空分类")
            key = (level1, level2)
            if key in seen:
                raise ValueError(f"商品类目存在重复路径: {level1}/{level2}")
            seen.add(key)
            paths.append(key)

        canonical = "\n".join(f"{a}\t{b}" for a, b in sorted(paths))
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        version = f"s4-taxonomy-{digest[:12]}"
        level1_records: dict[str, ProductCategoryRecord] = {}
        records: list[ProductCategoryRecord] = []
        for level1_name, level2_name in paths:
            parent_id = _stable_id("l1", level1_name)
            if parent_id not in level1_records:
                parent = ProductCategoryRecord(
                    category_id=parent_id,
                    category_name=level1_name,
                    level=1,
                    taxonomy_version=version,
                )
                level1_records[parent_id] = parent
                records.append(parent)
            records.append(
                ProductCategoryRecord(
                    category_id=_stable_id("l2", f"{level1_name}\x1f{level2_name}"),
                    category_name=level2_name,
                    level=2,
                    parent_category_id=parent_id,
                    parent_category_name=level1_name,
                    taxonomy_version=version,
                )
            )
        return ProductTaxonomy(records, version=version)

    def persist_snapshot(self, taxonomy: ProductTaxonomy, directory: str | Path) -> Path:
        """原子持久化名称—ID—父级映射，已存在的同版本快照不重复覆盖。"""
        target_dir = Path(directory)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / f"{taxonomy.version}.json"
        if target.exists():
            return target
        payload = {
            "taxonomy_version": taxonomy.version,
            "status": "active",
            "records": [item.model_dump(mode="json") for item in taxonomy.records],
        }
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, target)
        return target

    def _read_first_sheet(self, path: Path) -> list[list[str]]:
        if not path.exists():
            raise FileNotFoundError(f"商品类目工作簿不存在: {path}")
        with zipfile.ZipFile(path) as archive:
            shared = self._shared_strings(archive)
            sheets = sorted(
                name
                for name in archive.namelist()
                if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
            )
            if not sheets:
                raise ValueError("XLSX 缺少 worksheet XML")
            root = ET.fromstring(archive.read(sheets[0]))

        result: list[list[str]] = []
        for row in root.findall(".//x:sheetData/x:row", _NS):
            values = ["", ""]
            for cell in row.findall("x:c", _NS):
                ref = cell.attrib.get("r", "")
                column = _column_index(ref)
                if column not in {0, 1}:
                    continue
                value_node = cell.find("x:v", _NS)
                if value_node is None:
                    inline = cell.find("x:is/x:t", _NS)
                    value = (inline.text if inline is not None else "") or ""
                elif cell.attrib.get("t") == "s":
                    value = shared[int(value_node.text or "0")]
                else:
                    value = value_node.text or ""
                values[column] = value
            result.append(values)
        return result

    @staticmethod
    def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
        if "xl/sharedStrings.xml" not in archive.namelist():
            return []
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        return ["".join(node.itertext()) for node in root.findall("x:si", _NS)]


def _stable_id(level: str, business_key: str) -> str:
    digest = hashlib.sha256(business_key.encode("utf-8")).hexdigest()[:16]
    return f"cat-{level}-{digest}"


def _column_index(cell_ref: str) -> int:
    match = re.match(r"([A-Z]+)", cell_ref.upper())
    if not match:
        return -1
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1
