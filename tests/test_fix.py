"""自动修复工具测试。"""

from codeinsight.agent import run_fix
from codeinsight.cli import _build_parser
from codeinsight.fix_tool import apply_fix, generate_diff, rollback, run_tests


class TestApplyFix:
    """apply_fix 单元测试。"""

    def test_apply_fix_replaces_text(self, tmp_path):
        """验证：文本替换成功并创建备份。"""
        f = tmp_path / "demo.py"
        f.write_text("x = 1\n", encoding="utf-8")
        success = apply_fix(str(f), "x = 1", "x = 2")
        assert success
        assert f.read_text(encoding="utf-8") == "x = 2\n"

    def test_apply_fix_creates_backup(self, tmp_path):
        """验证：修复前创建 .bak 备份。"""
        f = tmp_path / "demo.py"
        f.write_text("x = 1\n", encoding="utf-8")
        apply_fix(str(f), "x = 1", "x = 2")
        assert (tmp_path / "demo.py.bak").exists()
        assert (tmp_path / "demo.py.bak").read_text(encoding="utf-8") == "x = 1\n"

    def test_apply_fix_returns_false_for_no_match(self, tmp_path):
        """验证：无匹配时返回 False。"""
        f = tmp_path / "demo.py"
        f.write_text("x = 1\n", encoding="utf-8")
        assert not apply_fix(str(f), "y = 2", "y = 3")

    def test_apply_fix_returns_false_for_multi_match(self, tmp_path):
        """验证：多处匹配时返回 False（防止误改）。"""
        f = tmp_path / "demo.py"
        f.write_text("pass\npass\n", encoding="utf-8")
        assert not apply_fix(str(f), "pass", "return")


class TestGenerateDiff:
    """generate_diff 单元测试。"""

    def test_generate_diff_shows_change(self):
        """验证：diff 显示修改内容。"""
        diff = generate_diff("test.py", "old", "new")
        assert "-old" in diff
        assert "+new" in diff
        assert "test.py" in diff


class TestRunFix:
    """run_fix 集成测试。"""

    def test_run_fix_rejects_empty_issue(self, tmp_path):
        """验证：空 issue 返回结构化错误。"""
        report = run_fix(str(tmp_path), "   ")
        assert report.findings[0].title == "问题描述为空"

    def test_run_fix_rejects_invalid_root(self):
        """验证：无效根目录返回错误。"""
        report = run_fix("d:/not-exist", "修复 bug")
        assert report.findings[0].title == "根目录路径无效"

    def test_build_parser_supports_fix(self):
        """验证：CLI 已注册 fix 子命令。"""
        parser = _build_parser()
        args = parser.parse_args(["fix", "--root", ".", "--issue", "空指针"])
        assert args.command == "fix"
        assert args.issue == "空指针"


class TestRollback:
    """rollback 单元测试。"""

    def test_rollback_restores_from_bak(self, tmp_path):
        """验证：回滚从 .bak 恢复原始内容并删除备份。"""
        f = tmp_path / "demo.py"
        f.write_text("original\n", encoding="utf-8")
        bak = tmp_path / "demo.py.bak"
        bak.write_text("original\n", encoding="utf-8")
        f.write_text("modified\n", encoding="utf-8")
        success = rollback(str(f))
        assert success
        assert f.read_text(encoding="utf-8") == "original\n"
        assert not bak.exists()

    def test_rollback_returns_false_without_bak(self, tmp_path):
        """验证：无 .bak 文件时返回 False。"""
        f = tmp_path / "demo.py"
        f.write_text("content\n", encoding="utf-8")
        assert not rollback(str(f))


class TestRunTests:
    """run_tests 单元测试。"""

    def test_run_tests_returns_bool_and_output(self, tmp_path):
        """验证：run_tests 能正常返回（无论测试通过与否）。"""
        # 用临时空目录运行，预期会失败（没有 pytest 配置）。
        passed, output = run_tests(str(tmp_path))
        assert isinstance(passed, bool)
        assert isinstance(output, str)
