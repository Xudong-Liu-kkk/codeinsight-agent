"""路径安全校验工具。

本模块用于限制文件访问范围，避免读取项目根目录之外或敏感文件。
"""

from pathlib import Path


# 敏感文件名关键字列表，命中即视为高风险读取目标。
SENSITIVE_NAME_KEYWORDS: tuple[str, ...] = (".env", "id_rsa", "credentials")
# 敏感扩展名列表，常见于私钥、证书等文件。
SENSITIVE_SUFFIXES: tuple[str, ...] = (".pem", ".key")


def ensure_within_root(root: Path, target: Path) -> Path:
    """确保目标路径位于项目根目录之内。"""

    # root_resolved 是规范化后的根目录绝对路径。
    root_resolved = root.resolve()
    # target_resolved 是规范化后的目标绝对路径。
    target_resolved = target.resolve()
    try:
        # 通过 relative_to 校验 target 是否在 root 下。
        target_resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise ValueError(f"目标路径越界：{target_resolved}") from exc
    return target_resolved


def is_sensitive_path(target: Path) -> bool:
    """判断目标路径是否属于敏感文件。"""

    # target_name 使用小写比较，避免大小写差异影响判断。
    target_name = target.name.lower()
    # 关键字命中即视为敏感文件。
    if any(keyword in target_name for keyword in SENSITIVE_NAME_KEYWORDS):
        return True
    # 扩展名命中也视为敏感文件。
    if target.suffix.lower() in SENSITIVE_SUFFIXES:
        return True
    return False


def guard_readable_path(root: Path, target: Path) -> Path:
    """执行读取前安全校验并返回可安全访问的路径。"""

    # safe_path 是通过根目录边界校验后的目标路径。
    safe_path = ensure_within_root(root, target)
    # 敏感文件默认禁止读取，避免凭据泄露。
    if is_sensitive_path(safe_path):
        raise ValueError(f"禁止读取敏感文件：{safe_path.name}")
    return safe_path

