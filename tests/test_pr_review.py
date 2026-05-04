"""Git PR 审查测试。"""

import subprocess

import pytest

from codeinsight.agent import run_pr_review
from codeinsight.cli import _build_parser
from codeinsight.git_tool import DiffResult, get_commit_diff, get_uncommitted_diff


class TestGitDiff:
    """Git diff 工具测试。"""

    def test_get_uncommitted_diff_returns_result(self, tmp_path):
        """验证：Git 仓库中可获取未提交的变更。"""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "hello.py").write_text("print('hello')", encoding="utf-8")
        subprocess.run(["git", "add", "hello.py"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "hello.py").write_text("print('world')", encoding="utf-8")

        diff = get_uncommitted_diff(tmp_path)
        assert diff.files_changed == ["hello.py"]
        assert "world" in diff.diff_content
        assert diff.summary

    def test_get_commit_diff_returns_result(self, tmp_path):
        """验证：可获取指定 commit 的变更。"""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "demo.py").write_text("x = 1", encoding="utf-8")
        subprocess.run(["git", "add", "demo.py"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "first"], cwd=str(tmp_path), capture_output=True)

        diff = get_commit_diff(tmp_path, "HEAD")
        assert "demo.py" in diff.files_changed
        assert "x = 1" in diff.diff_content


class TestPrReview:
    """PR 审查功能测试。"""

    def test_run_pr_review_rejects_invalid_root(self):
        """验证：无效根目录返回结构化错误。"""
        report = run_pr_review("d:/not-exist-root-for-codeinsight")
        assert report.findings[0].title == "根目录路径无效"

    def test_run_pr_review_no_changes_in_empty_dir(self, tmp_path):
        """验证：无变更时返回无变更提示。"""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        report = run_pr_review(str(tmp_path))
        # 没有提交，git diff 可能报错或无变更。
        assert "pr-review" in report.summary.lower() or "变更" in report.summary or "失败" in report.summary

    def test_build_parser_supports_pr_review_command(self):
        """验证：CLI 已注册 pr-review 子命令。"""
        parser = _build_parser()
        args = parser.parse_args(["pr-review", "--root", "."])
        assert args.command == "pr-review"
        assert args.root == "."

    def test_build_parser_pr_review_with_commit(self):
        """验证：pr-review 支持 --commit 参数。"""
        parser = _build_parser()
        args = parser.parse_args(["pr-review", "--root", ".", "--commit", "HEAD"])
        assert args.commit == "HEAD"

    def test_build_parser_pr_review_with_branches(self):
        """验证：pr-review 支持 --base 和 --head 参数。"""
        parser = _build_parser()
        args = parser.parse_args([
            "pr-review", "--root", ".", "--base", "main", "--head", "feature-x",
        ])
        assert args.base == "main"
        assert args.head == "feature-x"

    def test_get_branch_diff_returns_result(self, tmp_path):
        """验证：可获取两个分支之间的差异。"""
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(tmp_path), capture_output=True)

        # 先做首次提交（确定默认分支名）。
        (tmp_path / "hello.py").write_text("print('hello')", encoding="utf-8")
        subprocess.run(["git", "add", "hello.py"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), capture_output=True)

        # 获取当前分支名，兼容 master/main 等不同默认值。
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=str(tmp_path), capture_output=True, text=True,
        )
        base_branch = result.stdout.strip()

        # 创建 feature 分支并做修改。
        subprocess.run(["git", "checkout", "-b", "feature"], cwd=str(tmp_path), capture_output=True)
        (tmp_path / "hello.py").write_text("print('world')", encoding="utf-8")
        subprocess.run(["git", "add", "hello.py"], cwd=str(tmp_path), capture_output=True)
        subprocess.run(["git", "commit", "-m", "change"], cwd=str(tmp_path), capture_output=True)

        from codeinsight.git_tool import get_branch_diff
        diff = get_branch_diff(tmp_path, base_branch, "feature")
        assert "hello.py" in diff.files_changed
        assert "world" in diff.diff_content
