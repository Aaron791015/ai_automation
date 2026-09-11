"""驗證明確案例文件的匯出優先序；不登入或執行產品測試。"""
from types import SimpleNamespace
import pytest
from tools.test_platform.collect import pytest_case_export as export

DOC = """平台案例：[功能驗證] X1：保存：值是否保留
前置條件：
- 帳號：二級代理
測試範圍：
- 彩種：香港六合彩
步驟：
1. 輸入 100 並保存。
2. 重新整理並讀取。
預期結果：
- 應顯示 100。
已知問題：
- 待補其他彩種。
實作備註：
這段不是平台顯示的步驟。
"""

def test_structured_documentation_separates_sections():
    result = export._documented_case(DOC)
    assert result["步驟"] == ["輸入 100 並保存。", "重新整理並讀取。"]
    assert result["預期結果"] == ["應顯示 100。"]
    assert result["已知問題"] == ["待補其他彩種。"]
    assert "實作備註" not in result

def test_legacy_documentation_keeps_existing_parser():
    assert export._documented_case("一般說明\n步驟：自由文字") is None

@pytest.mark.parametrize("doc", [DOC.replace("預期結果：", "缺少結果："), DOC.replace("2. 重新整理並讀取。", "")])
def test_incomplete_documentation_does_not_silently_export(doc):
    with pytest.raises(ValueError):
        export._documented_case(doc)

def test_explicit_conditions_override_inferred_restoration(monkeypatch, tmp_path):
    def case():
        pass
    case.__doc__ = DOC.replace("帳號：二級代理", "資料：本案例保留設定，不自動還原")
    item = SimpleNamespace(obj=case, path=tmp_path/'case.py', location=('case.py', 0, 'case'),
                           nodeid='case.py::case', originalname='case', name='case',
                           fixturenames=['page'], iter_markers=lambda: [])
    monkeypatch.setattr(export, 'allure_labels', lambda item: [('suite', '飞单选项明细设置')])
    monkeypatch.setattr(export, '_title', lambda item: ('標題', 'allure_title'))
    monkeypatch.setattr(export, '_static_steps', lambda item: ([], ['f"{game}"'], [], ['原始附件'], [], True))
    result = export._collect_one(item, str(tmp_path))
    assert result['preconditions'] == ['資料：本案例保留設定，不自動還原']
    assert result['steps'] == ['輸入 100 並保存。', '重新整理並讀取。']
    assert result['expected'] == ['應顯示 100。']
    assert result['known_issues'] == ['待補其他彩種。']
