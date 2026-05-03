"""项目依赖分析工具。

本模块负责解析 Python 项目的依赖配置文件，
提取运行时依赖和开发依赖，并给出风险提示。
"""

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(slots=True)
class DepInfo:
    """单条依赖信息。"""

    name: str
    version_spec: str
    category: str  # "runtime" 或 "dev"


@dataclass(slots=True)
class DepsResult:
    """依赖分析结果。"""

    runtime_deps: list[DepInfo]
    dev_deps: list[DepInfo]
    has_lock_file: bool
    lock_file_path: str | None
    total_runtime: int
    total_dev: int


def _parse_pep508_name(requirement: str) -> tuple[str, str]:
    """从 PEP 508 格式的依赖字符串中提取名称和版本约束。"""

    # 去掉 extras 标记（如 [security]），简化解析。
    for sep in ("<=", ">=", "!=", "~=", "==", "<", ">", ";"):
        if sep in requirement:
            name_part = requirement.split(sep, 1)[0].strip()
            version_part = requirement[len(name_part):].strip()
            # 去除分号后的环境标记（如 ; sys_platform == "win32"）
            if ";" in version_part:
                version_part = version_part.split(";", 1)[0].strip()
            return name_part, version_part
    # 没有版本约束时，version_spec 返回空。
    return requirement.strip(), ""


def parse_pyproject_deps(project_root: Path) -> DepsResult:
    """解析 pyproject.toml 中的项目依赖信息。"""

    pyproject_path = project_root / "pyproject.toml"
    if not pyproject_path.exists() or not pyproject_path.is_file():
        raise FileNotFoundError(f"未找到 pyproject.toml：{pyproject_path}")

    # 检查 uv.lock 是否存在。
    uv_lock_path = project_root / "uv.lock"
    has_lock = uv_lock_path.exists() and uv_lock_path.is_file()

    with open(pyproject_path, "rb") as fh:
        data = tomllib.load(fh)

    project = data.get("project", {})
    runtime_specs: list[str] = project.get("dependencies", [])
    runtime_deps = []
    for spec in runtime_specs:
        name, version_part = _parse_pep508_name(spec)
        runtime_deps.append(DepInfo(name=name, version_spec=version_part, category="runtime"))

    # uv 项目的开发依赖位于 [dependency-groups] 表下。
    dev_deps = []
    dep_groups = data.get("dependency-groups", {})
    for group_name, group_specs in dep_groups.items():
        for spec in group_specs:
            name, version_part = _parse_pep508_name(spec)
            dev_deps.append(DepInfo(name=name, version_spec=version_part, category=f"dev/{group_name}"))

    return DepsResult(
        runtime_deps=runtime_deps,
        dev_deps=dev_deps,
        has_lock_file=has_lock,
        lock_file_path=str(uv_lock_path) if has_lock else None,
        total_runtime=len(runtime_deps),
        total_dev=len(dev_deps),
    )
