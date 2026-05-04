"""项目长期记忆模块。

将 Agent 分析过程中的关键发现持久化到 .codeinsight/memory/ 目录，
后续 ask 时自动加载，避免重复扫描项目结构。
"""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path


# 记忆目录相对于项目根目录的路径。
MEMORY_DIR_NAME = ".codeinsight/memory"
# 最多保留的历史问答条数。
MAX_HISTORY = 5


@dataclass(slots=True)
class FileEntry:
    """一条文件元信息记录。"""

    path: str
    mtime: float


@dataclass(slots=True)
class ProjectMemory:
    """项目的长期记忆管理器。

    存储三份数据：
    - files.json：项目内文件路径及其最后扫描时的 mtime
    - imports.json：模块间导入关系 {module: [imported_modules]}
    - history.json：最近 N 条问答记录
    """

    root: Path
    memory_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.memory_dir = self.root / MEMORY_DIR_NAME

    # —— 文件操作 ——

    def _ensure_dir(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _read_json(self, filename: str, default: object = None) -> object:
        path = self.memory_dir / filename
        if not path.exists():
            return {} if default is None else default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {} if default is None else default

    def _write_json(self, filename: str, data: object) -> None:
        self._ensure_dir()
        path = self.memory_dir / filename
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # —— 文件索引 ——

    def save_file_index(self, files: list[FileEntry]) -> None:
        """保存项目文件索引，按路径为键存储 mtime。"""
        existing = self._read_json("files.json")
        for entry in files:
            existing[entry.path] = entry.mtime
        self._write_json("files.json", existing)

    def load_file_index(self) -> dict[str, float]:
        """加载文件索引，返回 {路径: mtime}。"""
        return self._read_json("files.json")

    def get_stale_files(self) -> list[str]:
        """返回 mtime 已变化的文件路径列表（文件已修改或已删除）。"""
        existing = self.load_file_index()
        stale: list[str] = []
        for file_path, cached_mtime in existing.items():
            full_path = self.root / file_path
            if not full_path.exists() or full_path.stat().st_mtime != cached_mtime:
                stale.append(file_path)
        return stale

    # —— 导入关系 ——

    def save_imports(self, imports: dict[str, list[str]]) -> None:
        """保存模块间导入关系。"""
        existing = self._read_json("imports.json")
        existing.update(imports)
        self._write_json("imports.json", existing)

    def load_imports(self) -> dict[str, list[str]]:
        """加载导入关系。"""
        return self._read_json("imports.json")

    # —— 问答历史 ——

    def add_history(self, question: str, summary: str) -> None:
        """追加一条问答记录，保留最近 N 条。"""
        raw = self._read_json("history.json", default=[])
        items: list[dict] = raw if isinstance(raw, list) else []
        items.append({
            "question": question,
            "summary": summary[:300],
            "timestamp": int(os.stat(self.memory_dir).st_mtime * 1000) if self.memory_dir.exists() else 0,
        })
        items = items[-MAX_HISTORY:]
        self._write_json("history.json", items)

    def load_history(self) -> list[dict]:
        """加载历史问答列表。"""
        raw = self._read_json("history.json", default=[])
        return raw if isinstance(raw, list) else []

    # —— 上下文字符串 ——

    def scan_and_save(self) -> list[FileEntry]:
        """扫描项目目录，保存文件索引，返回发现的文件列表。"""
        entries: list[FileEntry] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("__pycache__", ".venv", "node_modules")]
            for name in filenames:
                if name.startswith("."):
                    continue
                full = Path(dirpath) / name
                try:
                    rel = str(full.relative_to(self.root))
                    entries.append(FileEntry(path=rel, mtime=full.stat().st_mtime))
                except OSError:
                    continue
        self.save_file_index(entries)
        return entries

    def build_context(self) -> str:
        """构造可注入 system prompt 的记忆上下文。

        包含：已知模块列表、最近问答历史、变更提示。
        """
        parts: list[str] = []

        file_index = self.load_file_index()
        if file_index:
            total = len(file_index)
            sample = list(file_index)[:15]
            parts.append(
                f"[项目记忆] 已记录 {total} 个文件，"
                f"示例：{', '.join(sample)}{'…' if total > 15 else ''}"
            )

        imports = self.load_imports()
        if imports:
            parts.append(f"[项目记忆] 已记录 {len(imports)} 个模块的导入关系。")

        history = self.load_history()
        if history:
            parts.append("[项目记忆] 最近问答记录：")
            for h in history:
                parts.append(f"  问：{h['question']}")
                parts.append(f"  答：{h['summary'][:120]}")

        stale = self.get_stale_files()
        if stale:
            parts.append(
                f"[项目记忆] {len(stale)} 个文件自上次分析后已变更，"
                f"建议重新 overview：{', '.join(stale[:10])}"
            )

        return "\n".join(parts)
