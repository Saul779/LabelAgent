"""临时脚本：扫描 src/label_agent 生成类/函数清单。"""
from __future__ import annotations

import ast
from pathlib import Path

root = Path("src/label_agent")
files = sorted(root.rglob("*.py"))
out: list[str] = []


def summarize(node: ast.AST) -> str:
    doc = ast.get_docstring(node) or ""  # type: ignore[arg-type]
    first = doc.strip().split("\n")[0].strip() if doc.strip() else ""
    return first[:140]


for f in files:
    rel = f.as_posix()
    try:
        tree = ast.parse(f.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        out.append(f"FILE|{rel}|ERROR:{e}")
        continue
    mod_doc = summarize(tree)
    classes: list[tuple] = []
    funcs: list[tuple] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("_") and item.name != "__init__":
                        continue
                    methods.append(
                        (item.name, summarize(item), isinstance(item, ast.AsyncFunctionDef))
                    )
            classes.append((node.name, summarize(node), methods))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            funcs.append((node.name, summarize(node), isinstance(node, ast.AsyncFunctionDef)))
    if not classes and not funcs and not mod_doc:
        out.append(f"FILE|{rel}|EMPTY")
        continue
    out.append(f"FILE|{rel}|{mod_doc}")
    for cname, cdoc, methods in classes:
        out.append(f"  CLASS|{cname}|{cdoc}")
        for mname, mdoc, is_async in methods:
            prefix = "async " if is_async else ""
            out.append(f"    METH|{prefix}{mname}|{mdoc}")
    for fname, fdoc, is_async in funcs:
        prefix = "async " if is_async else ""
        out.append(f"  FUNC|{prefix}{fname}|{fdoc}")

dest = Path("docs/_api_inventory.txt")
dest.write_text("\n".join(out), encoding="utf-8")
print(f"wrote {len(out)} lines from {len(files)} files -> {dest}")
