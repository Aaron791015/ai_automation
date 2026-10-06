"""主題整理須保留全部案例、原始執行 ID 與其他產品的檔案分組。"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def test_inline_case_documentation_is_exported():
    from tools.test_platform.collect.pytest_case_export import _documented_case
    doc = """平台案例：報表金額核對
    前置條件：已有結算注單。
    測試範圍：三彩種。
    步驟：
    1. 查詢報表。
    2. 核對金額。
    預期結果：金額相符。
    佐證方式：保存報表。
    已知問題：缺注單時阻塞。
    實作備註：不匯出此段。
    """
    result = _documented_case(doc)
    assert result["前置條件"] == ["已有結算注單。"]
    assert result["預期結果"] == ["金額相符。"]
    assert result["已知問題"] == ["缺注單時阻塞。"]
    assert result["步驟"] == ["查詢報表。", "核對金額。"]


def test_topics_preserve_cases_and_group_only_matching_product():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "tools/test_platform"))
    from collect.case_index import to_tree

    cfg = json.loads((root / "tools/test_platform/registry/ui_tests.tool.json").read_text(encoding="utf-8"))["cases"]

    def case(name, file, product="xzh", **labels):
        return dict(nodeid=name, title=name, file=file, product=product, allure=labels,
                    markers=[], stage=None, stage_label=None)

    rows = [
        case("setting", "tests/xzh/test_user_management.py", sub_suite="赔率差分", suite="一级代理"),
        case("general", "tests/xzh/test_user_management.py", sub_suite="一般管理", suite="一级代理"),
        case("report", "tests/xzh/test_reports.py", suite="赔率差金额"),
        {**case("acceptance[a]", "tests/xzh/test_odds_gap_acceptance.py"), "level_index": 0},
        case("acceptance[b]", "tests/xzh/test_odds_gap_acceptance.py"),
        case("other", "tests/xzh/test_odds_gap_acceptance.py", product="other"),
    ]
    tree = to_tree(rows, SimpleNamespace(cases=cfg))

    def leaves(nodes):
        return [c for n in nodes for c in ([n["case"]] if n["type"] == "case" else leaves(n["children"]))]

    assert sorted(c["nodeid"] for c in leaves(tree)) == sorted(c["nodeid"] for c in rows)
    assert all(c in rows for c in leaves(tree))
    xzh = next(n for n in tree if n["id"] == "xzh")
    management = xzh["children"][0]
    assert len(xzh["children"]) == 1
    assert management["file"] == "tests/xzh/test_user_management.py"
    assert management["counts"]["total"] == 5
    level = next(n for n in management["children"] if n["label"] == "一级代理")
    gap = next(n for n in level["children"] if n["label"] == "赔率差分")
    assert {c["nodeid"] for c in leaves([gap])} == {"setting", "acceptance[a]"}
    shared = next(n for n in management["children"] if n["label"] == "賠率差跨層與共用")
    assert {c["nodeid"] for c in leaves([shared])} == {"report", "acceptance[b]"}
    assert next(c for c in leaves([gap]) if c["nodeid"] == "acceptance[a]")["file"] == "tests/xzh/test_odds_gap_acceptance.py"
    assert next(n for n in tree if n["id"] == "other")["children"][0]["type"] == "file"
    # 沒有宣告主題時仍使用原本檔案樹。
    plain = to_tree(rows, SimpleNamespace(cases={}))
    assert all(n["type"] == "file" for p in plain for n in p["children"])


def test_variants_are_grouped_by_purpose_and_have_readable_titles():
    root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(root / "tools/test_platform"))
    from collect.case_index import annotate, to_tree
    cfg = json.loads((root / "tools/test_platform/registry/ui_tests.tool.json").read_text(encoding="utf-8"))["cases"]
    spec = SimpleNamespace(cases=cfg)
    rows = []
    for via in ("company", "parent"):
        for game in ("markSix", "ukLucky7", "bingo6"):
            rows.append(dict(nodeid=f"batch-{via}-{game}", title="原始標題", markers=[],
                             file="tests/xzh/test_odds_gap_acceptance.py", func="test_save_and_remaining_by_scope",
                             allure={}, level_index=1, case_parameters={"via": via, "game": game}))
    for via in ("company", "parent"):
        rows.append(dict(nodeid=f"main-{via}", title="B90：保存與還原", markers=[],
                         file="tests/xzh/test_user_management.py", func="test_level2_save",
                         allure={"suite": "二级代理", "sub_suite": "赔率差分"},
                         case_parameters={"via": via}))
    flat = annotate(rows, spec)
    assert len({c["title"] for c in flat}) == 8
    assert "公司操作／香港六合彩" in flat[0]["title"]
    assert rows[0]["title"] == "原始標題"
    tree = to_tree(flat, spec)
    management = next(n for p in tree for n in p["children"] if n.get("file") == "tests/xzh/test_user_management.py")
    level = next(n for n in management["children"] if n["label"] == "二级代理")
    gap = next(n for n in level["children"] if n["label"] == "赔率差分")
    main, batch = gap["children"]
    assert main["label"] == "01 主要案例（三彩種）"
    assert len(main["children"]) == 1
    assert main["children"][0]["counts"]["total"] == 2
    assert batch["label"] == "03 分批驗收（可單獨續跑）"
    assert len(batch["children"]) == 1
    assert batch["children"][0]["counts"]["total"] == 6
    assert {n["id"] for n in batch["children"][0]["children"]} == {c["nodeid"] for c in rows[:6]}
