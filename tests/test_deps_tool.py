"""依赖解析工具测试。"""

import pytest

from codeinsight.tools.deps_tool import _parse_pep508_name, parse_pyproject_deps


def test_parse_pep508_name_simple():
    """验证：简单依赖名提取。"""
    name, version = _parse_pep508_name("requests")
    assert name == "requests"
    assert version == ""


def test_parse_pep508_name_with_version():
    """验证：带版本约束的依赖解析。"""
    name, version = _parse_pep508_name("openai>=2.8.1")
    assert name == "openai"
    assert version == ">=2.8.1"


def test_parse_pep508_name_with_environment_marker():
    """验证：带环境标记的依赖正确去掉标记。"""
    name, version = _parse_pep508_name('colorama>=0.4; sys_platform == "win32"')
    assert name == "colorama"
    assert version == ">=0.4"


def test_parse_pyproject_deps_reads_runtime_and_dev(tmp_path):
    """验证：可从标准 uv 项目依赖中解析运行时和开发依赖。"""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """\
[project]
name = "demo"
version = "0.1.0"
dependencies = ["httpx>=0.28", "click"]

[dependency-groups]
dev = ["pytest>=8.3.0"]
test = ["coverage"]
""",
        encoding="utf-8",
    )

    result = parse_pyproject_deps(tmp_path)
    assert result.total_runtime == 2
    assert result.total_dev == 2
    runtime_names = [dep.name for dep in result.runtime_deps]
    assert "httpx" in runtime_names
    assert "click" in runtime_names
    dev_names = [dep.name for dep in result.dev_deps]
    assert "pytest" in dev_names
    assert "coverage" in dev_names


def test_parse_pyproject_deps_no_lock_file(tmp_path):
    """验证：无锁文件时返回正确标志。"""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='demo'\ndependencies=[]", encoding="utf-8")

    result = parse_pyproject_deps(tmp_path)
    assert result.has_lock_file is False
    assert result.lock_file_path is None


def test_parse_pyproject_deps_with_lock_file(tmp_path):
    """验证：存在 uv.lock 时正确检测。"""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='demo'\ndependencies=[]", encoding="utf-8")
    (tmp_path / "uv.lock").write_text("version = 1", encoding="utf-8")

    result = parse_pyproject_deps(tmp_path)
    assert result.has_lock_file is True
    assert "uv.lock" in str(result.lock_file_path)


def test_parse_pyproject_deps_missing_file(tmp_path):
    """验证：缺少 pyproject.toml 时抛出 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        parse_pyproject_deps(tmp_path)


def test_parse_pyproject_deps_empty_deps(tmp_path):
    """验证：空依赖项目返回空列表。"""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[project]\nname='demo'\ndependencies=[]", encoding="utf-8")

    result = parse_pyproject_deps(tmp_path)
    assert result.total_runtime == 0
    assert result.total_dev == 0
