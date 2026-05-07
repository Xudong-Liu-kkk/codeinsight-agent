"""项目依赖分析工具。

本模块负责解析多种语言的项目依赖配置文件，
提取运行时依赖和开发依赖，并给出风险提示。

支持：pyproject.toml（Python）、package.json（Node.js）、
       pom.xml（Maven/Java）、go.mod（Go）。
"""

from dataclasses import dataclass
from pathlib import Path
import json
import re
import tomllib
from xml.etree import ElementTree


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


def _parse_npm_deps(project_root: Path) -> DepsResult | None:
    """解析 package.json（Node.js / JavaScript / TypeScript 项目）。

    Returns:
        DepsResult，文件不存在时返回 None。
    """
    pkg_path = project_root / "package.json"
    if not pkg_path.exists() or not pkg_path.is_file():
        return None

    with open(pkg_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    runtime_deps: list[DepInfo] = []
    for name, version in data.get("dependencies", {}).items():
        runtime_deps.append(DepInfo(name=name, version_spec=str(version), category="runtime"))

    dev_deps: list[DepInfo] = []
    for name, version in data.get("devDependencies", {}).items():
        dev_deps.append(DepInfo(name=name, version_spec=str(version), category="dev"))

    # 检测锁文件：npm 有 package-lock.json，yarn 有 yarn.lock。
    lock_paths = [project_root / "package-lock.json", project_root / "yarn.lock"]
    lock_file = next((str(p) for p in lock_paths if p.exists()), None)

    return DepsResult(
        runtime_deps=runtime_deps,
        dev_deps=dev_deps,
        has_lock_file=lock_file is not None,
        lock_file_path=lock_file,
        total_runtime=len(runtime_deps),
        total_dev=len(dev_deps),
    )


def _parse_maven_deps(project_root: Path) -> DepsResult | None:
    """解析 pom.xml（Maven / Java 项目）。

    Returns:
        DepsResult，文件不存在时返回 None。
    """
    pom_path = project_root / "pom.xml"
    if not pom_path.exists() or not pom_path.is_file():
        return None

    try:
        tree = ElementTree.parse(str(pom_path))
    except ElementTree.ParseError:
        return None

    root_el = tree.getroot()

    # Maven 使用命名空间，需在 findall 时传入。
    # 常见命名空间：http://maven.apache.org/POM/4.0.0
    ns = ""
    if "}" in (root_el.tag or ""):
        ns = root_el.tag.split("}", 1)[0] + "}"

    runtime_deps: list[DepInfo] = []
    dev_deps: list[DepInfo] = []

    deps_el = root_el.find(f"{ns}dependencies")
    if deps_el is not None:
        for dep_el in deps_el.findall(f"{ns}dependency"):
            gid = dep_el.findtext(f"{ns}groupId") or ""
            aid = dep_el.findtext(f"{ns}artifactId") or ""
            ver = dep_el.findtext(f"{ns}version") or "未指定"
            scope = dep_el.findtext(f"{ns}scope") or "compile"
            name = f"{gid}:{aid}" if gid else aid
            info = DepInfo(name=name, version_spec=ver, category="runtime" if scope == "compile" else f"runtime/{scope}")
            if scope in ("test", "provided", "system"):
                dev_deps.append(info)
            else:
                runtime_deps.append(info)

    # Maven 通常没有锁文件概念。
    return DepsResult(
        runtime_deps=runtime_deps,
        dev_deps=dev_deps,
        has_lock_file=False,
        lock_file_path=None,
        total_runtime=len(runtime_deps),
        total_dev=len(dev_deps),
    )


# go.mod 中的 require 块正则：匹配 `module/path vX.Y.Z` 格式。
_GO_REQUIRE_RE = re.compile(r"^\s*([\w./\-]+)\s+(v[\w.\-+]+)")


def _parse_go_deps(project_root: Path) -> DepsResult | None:
    """解析 go.mod（Go 项目）。

    Returns:
        DepsResult，文件不存在时返回 None。
    """
    gomod_path = project_root / "go.mod"
    if not gomod_path.exists() or not gomod_path.is_file():
        return None

    text = gomod_path.read_text(encoding="utf-8")
    runtime_deps: list[DepInfo] = []
    # Go 没有 dev dependencies 的区分，都算 runtime。
    for line in text.splitlines():
        match = _GO_REQUIRE_RE.match(line)
        if match:
            runtime_deps.append(DepInfo(name=match.group(1), version_spec=match.group(2), category="runtime"))

    # go.sum 为 Go 的校验和锁文件。
    go_sum = project_root / "go.sum"
    has_lock = go_sum.exists()

    return DepsResult(
        runtime_deps=runtime_deps,
        dev_deps=[],
        has_lock_file=has_lock,
        lock_file_path=str(go_sum) if has_lock else None,
        total_runtime=len(runtime_deps),
        total_dev=0,
    )


def parse_deps(project_root: Path) -> DepsResult:
    """自动检测项目类型并解析依赖。

    按优先级检测：pyproject.toml → package.json → pom.xml → go.mod。
    如果检测到多种类型，合并所有依赖结果。
    如果一种都未检测到，抛出 FileNotFoundError。

    Args:
        project_root: 项目根目录路径。

    Returns:
        合并后的 DepsResult。

    Raises:
        FileNotFoundError: 未找到任何已知的依赖配置文件。
    """
    results: list[DepsResult] = []

    try:
        results.append(parse_pyproject_deps(project_root))
    except FileNotFoundError:
        pass

    npm = _parse_npm_deps(project_root)
    if npm is not None:
        results.append(npm)

    mvn = _parse_maven_deps(project_root)
    if mvn is not None:
        results.append(mvn)

    gomod = _parse_go_deps(project_root)
    if gomod is not None:
        results.append(gomod)

    if not results:
        raise FileNotFoundError(
            f"未在 {project_root} 下找到依赖配置文件。"
            f"当前支持：pyproject.toml、package.json、pom.xml、go.mod。"
        )

    # 合并多个项目的依赖（monorepo 场景）。
    merged_runtime: list[DepInfo] = []
    merged_dev: list[DepInfo] = []
    any_has_lock = False
    lock_paths: list[str] = []

    for r in results:
        merged_runtime.extend(r.runtime_deps)
        merged_dev.extend(r.dev_deps)
        if r.has_lock_file:
            any_has_lock = True
        if r.lock_file_path:
            lock_paths.append(r.lock_file_path)

    return DepsResult(
        runtime_deps=merged_runtime,
        dev_deps=merged_dev,
        has_lock_file=any_has_lock,
        lock_file_path=", ".join(lock_paths) if lock_paths else None,
        total_runtime=len(merged_runtime),
        total_dev=len(merged_dev),
    )


def parse_pyproject_deps(project_root: Path) -> DepsResult | None:
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
