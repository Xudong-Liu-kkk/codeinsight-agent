"""依赖分析引擎层测试。"""

from codeinsight.engine import run_deps
from codeinsight.cli import _build_parser


def test_run_deps_returns_report(tmp_path):
    """验证：run_deps 返回完整的依赖分析报告。"""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """\
[project]
name = "demo"
version = "0.1.0"
dependencies = ["httpx>=0.28"]

[dependency-groups]
dev = ["pytest>=8.3.0"]
""",
        encoding="utf-8",
    )

    report = run_deps(str(tmp_path))
    assert "运行时 1 个" in report.summary
    assert "开发 1 个" in report.summary
    assert report.confidence == "high"
    assert any(f.title.startswith("运行时依赖") for f in report.findings)
    assert any(f.title.startswith("开发依赖") for f in report.findings)
    assert any(f.title for f in report.findings if "锁文件" in f.title)


def test_run_deps_missing_pyproject(tmp_path):
    """验证：无 pyproject.toml 时返回结构化错误。"""
    report = run_deps(str(tmp_path))
    assert "配置文件" in report.findings[0].title


def test_run_deps_invalid_root():
    """验证：无效根目录返回结构化错误。"""
    report = run_deps("d:/not-exist-root-for-codeinsight")
    assert report.findings[0].title == "根目录路径无效"


def test_run_deps_with_lock(tmp_path):
    """验证：存在 uv.lock 时检测到锁文件。"""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='demo'\ndependencies=[]", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1", encoding="utf-8")

    report = run_deps(str(tmp_path))
    assert "锁文件已检测到" in report.summary


def test_run_deps_without_lock(tmp_path):
    """验证：无 uv.lock 时提示缺失。"""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='demo'\ndependencies=[]", encoding="utf-8")

    report = run_deps(str(tmp_path))
    assert "锁文件未检测到" in report.summary


def test_build_parser_supports_deps_command():
    """验证：CLI 已注册 deps 子命令。"""
    parser = _build_parser()
    args = parser.parse_args(["deps", "--root", "."])
    assert args.command == "deps"
    assert args.root == "."
