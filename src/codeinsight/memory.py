"""项目长期记忆模块。

将 Agent 分析过程中的关键发现持久化到 .codeinsight/memory/ 目录，
后续 ask 时自动加载，让 Agent 拥有跨会话的"记忆"：

  1. 文件索引（files.json）   — 记录已扫描过的文件路径和 mtime，
                                 避免每次 ask 都重新 overview。
  2. 导入关系（imports.json）  — 模块间的依赖图，帮助 Agent 快速定位
                                 影响面（如"这个函数被哪些模块引用"）。
  3. 问答历史（history.json）  — 最近 N 条问答记录，辅助上下文连续性。

目录结构：
  .codeinsight/memory/
  ├── files.json       # {文件相对路径: mtime}
  ├── imports.json     # {模块路径: [被导入的模块列表]}
  └── history.json     # [{question, summary, timestamp}]

整个目录由 .gitignore 排除，不会被提交到版本管理。
"""

from dataclasses import dataclass, field
import json
import os
import time
from pathlib import Path


# 记忆数据存储在项目根目录下的 .codeinsight/memory/ 子目录中。
# 与 ChromaDB / 其他索引数据共用一个父目录，便于统一管理。
MEMORY_DIR_NAME = ".codeinsight/memory"
# 问答历史最多保留的条数，超出后自动截断旧的。
MAX_HISTORY = 5


# —— 数据结构 ——

@dataclass(slots=True)
class FileEntry:
    """一条文件元信息记录。

    Attributes:
        path: 相对于项目根目录的文件路径。
        mtime: 文件最后修改时间（os.stat().st_mtime），用于检测变更。
    """

    path: str
    mtime: float


@dataclass(slots=True)
class ProjectMemory:
    """项目的长期记忆管理器。

    管理三份 JSON 持久化数据，对应三类记忆：

    files.json → 文件索引（{路径: mtime}）
        overview 工具扫描后自动写入；
        后续 ask 加载后注入 system prompt，Agent 无需重新扫描。

    imports.json → 导入关系（{模块: [被导入的模块列表]}）
        预留接口，后续 read 工具可自动解析 Python import 行来填充；
        用于快速回答"改了 X 会影响谁"类问题。

    history.json → 问答历史（[{question, summary, timestamp}]）
        每次 ask 完成后追加，保留最近 MAX_HISTORY 条；
        让 Agent 了解"刚才用户问了什么，得到了什么答案"。

    Attributes:
        root: 项目根目录路径。
        memory_dir: 记忆数据存储目录，在 __post_init__ 中自动计算。
    """

    root: Path
    memory_dir: Path = field(init=False)

    def __post_init__(self) -> None:
        self.memory_dir = self.root / MEMORY_DIR_NAME

    # —— 底层 JSON 读写 ——
    # 以下方法统一处理文件不存在、JSON 解析失败等边界情况，
    # 使得上层业务方法只需关注数据逻辑。

    def _ensure_dir(self) -> None:
        """确保记忆目录存在，不存在则递归创建。"""
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _read_json(self, filename: str, default: object = None) -> object:
        """从记忆目录读取 JSON 文件。

        Args:
            filename: 文件名，如 "files.json"。
            default: 文件不存在或解析失败时的默认返回值。
                     传 None 时返回 {}，传 [] 时返回 []。

        Returns:
            解析后的 Python 对象，失败时返回 default。
        """
        path = self.memory_dir / filename
        if not path.exists():
            return {} if default is None else default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # JSON 损坏或文件被占用时，当作空数据处理，不中断流程。
            return {} if default is None else default

    def _write_json(self, filename: str, data: object) -> None:
        """将数据以 JSON 格式写入记忆目录。

        使用 ensure_ascii=False 保留中文可读性，indent=2 便于手动排查。
        """
        self._ensure_dir()
        path = self.memory_dir / filename
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # —— 文件索引（files.json） ——
    # 记录项目内每个文件的最新 mtime，用于增量更新判断。

    def save_file_index(self, files: list[FileEntry]) -> None:
        """保存项目文件索引。

        新文件会追加到已有索引，已有文件会更新 mtime。
        不会删除已有记录——文件被删除后由 get_stale_files 识别。
        """
        existing = self._read_json("files.json")
        for entry in files:
            existing[entry.path] = entry.mtime
        self._write_json("files.json", existing)

    def load_file_index(self) -> dict[str, float]:
        """加载文件索引。

        Returns:
            {文件相对路径: mtime}，无记录时返回空 dict。
        """
        return self._read_json("files.json")

    def get_stale_files(self) -> list[str]:
        """检测自上次扫描以来已变更或已删除的文件。

        比对逻辑：
          1. 文件已被删除 → 标记为 stale。
          2. 文件的当前 mtime 不等于缓存值 → 标记为 stale（已被修改）。

        Returns:
            变更文件路径列表，可用于提示 Agent 需要重新 overview。
        """
        existing = self.load_file_index()
        stale: list[str] = []
        for file_path, cached_mtime in existing.items():
            full_path = self.root / file_path
            if not full_path.exists() or full_path.stat().st_mtime != cached_mtime:
                stale.append(file_path)
        return stale

    # —— 导入关系（imports.json） ——
    # 记录模块间的静态导入关系，帮助 Agent 快速回答影响面问题。
    # 当前为预留接口，后续在 read 工具中解析 Python import 行来填充。

    def save_imports(self, imports: dict[str, list[str]]) -> None:
        """保存模块间导入关系，合并到已有数据中。

        Args:
            imports: {模块相对路径: [它所导入的模块相对路径列表]}。
        """
        existing = self._read_json("imports.json")
        existing.update(imports)
        self._write_json("imports.json", existing)

    def load_imports(self) -> dict[str, list[str]]:
        """加载导入关系。

        Returns:
            {模块相对路径: [被导入模块列表]}，无记录时返回空 dict。
        """
        return self._read_json("imports.json")

    # —— 导入关系反向查询 ——
    # 基于已存储的 imports.json，查询"谁导入了指定模块"，
    # 帮助 Agent 快速评估修改影响面。

    def find_importers(self, module_name: str) -> list[str]:
        """查找导入了指定模块的所有文件。

        Args:
            module_name: 模块名，如 'codeinsight.engine'、'agent.py' 或 'agent'。
                         支持完整匹配和尾部匹配（如 'agent' 匹配 'codeinsight.agent'）。

        Returns:
            导入了该模块的文件路径列表，按文件名字母序排列。
        """
        imports = self.load_imports()
        result: list[str] = []
        for file_path, imported_list in imports.items():
            for imp in imported_list:
                # 尾部匹配：'engine' 可匹配 'codeinsight.engine'
                if module_name == imp or imp.endswith("." + module_name):
                    result.append(file_path)
                    break
        result.sort()
        return result

    # —— 问答历史（history.json） ——
    # 保留最近的问答对，为后续对话提供上下文连贯性。

    def add_history(self, question: str, summary: str) -> None:
        """追加一条问答记录，超出上限时自动截断旧数据。

        Args:
            question: 用户原始问题。
            summary: Agent 的回答摘要（截取前 300 字符）。
        """
        raw = self._read_json("history.json", default=[])
        items: list[dict] = raw if isinstance(raw, list) else []
        items.append({
            "question": question,
            "summary": summary[:300],
            "timestamp": int(time.time() * 1000),
        })
        # 截断到 MAX_HISTORY 条，保留最新的。
        items = items[-MAX_HISTORY:]
        self._write_json("history.json", items)

    def load_history(self) -> list[dict]:
        """加载历史问答列表。

        Returns:
            [{question, summary, timestamp}]，无记录时返回空列表。
        """
        raw = self._read_json("history.json", default=[])
        return raw if isinstance(raw, list) else []

    # —— 构建上下文字符串 ——
    # 将各类记忆数据格式化为一段文本，可直接注入 Agent 的 system prompt。

    def scan_and_save(self) -> list[FileEntry]:
        """扫描项目目录，保存文件索引并返回发现的文件列表。

        扫描时跳过：
          - 以 . 开头的隐藏文件和目录
          - __pycache__、.venv、node_modules 等常见无关目录

        Returns:
            所有已索引的 FileEntry 列表。
        """
        entries: list[FileEntry] = []
        for dirpath, dirnames, filenames in os.walk(self.root):
            # 在 os.walk 中原地修改 dirnames 可以阻止递归进入无关目录。
            dirnames[:] = [
                d for d in dirnames
                if not d.startswith(".")
                and d not in ("__pycache__", ".venv", "node_modules")
            ]
            for name in filenames:
                if name.startswith("."):
                    continue
                full = Path(dirpath) / name
                try:
                    rel = str(full.relative_to(self.root))
                    entries.append(FileEntry(path=rel, mtime=full.stat().st_mtime))
                except OSError:
                    # 文件可能在遍历过程中被删除，跳过即可。
                    continue
        self.save_file_index(entries)
        return entries

    def build_context(self) -> str:
        """构造可注入 system prompt 的记忆上下文字符串。

        聚合三类信息：
          1. 文件索引：已记录多少个文件，列举前 15 个示例。
          2. 导入关系：已记录多少个模块的依赖图。
          3. 问答历史：最近几个问答对（问题和答案摘要）。
          4. 变更提示：哪些文件的 mtime 已过期，建议重新扫描。

        Returns:
            格式化后的上下文文本，无记忆时返回空字符串。
        """
        parts: list[str] = []

        # 文件索引 → 告诉 Agent 项目有哪些文件、是否需要重新扫描。
        file_index = self.load_file_index()
        if file_index:
            total = len(file_index)
            sample = list(file_index)[:15]
            parts.append(
                f"[项目记忆] 已记录 {total} 个文件，"
                f"示例：{', '.join(sample)}{'…' if total > 15 else ''}"
            )

        # 导入关系 → 告诉 Agent 模块间的依赖链路。
        imports = self.load_imports()
        if imports:
            parts.append(f"[项目记忆] 已记录 {len(imports)} 个模块的导入关系，可用 find_usages 工具查询。")

        # 问答历史 → 告诉 Agent 之前聊过什么，保持上下文连贯。
        history = self.load_history()
        if history:
            parts.append("[项目记忆] 最近问答记录：")
            for h in history:
                parts.append(f"  问：{h['question']}")
                parts.append(f"  答：{h['summary'][:120]}")

        # 变更提示 → 提醒 Agent 某些文件的记忆已过期，需要重新 overview。
        stale = self.get_stale_files()
        if stale:
            parts.append(
                f"[项目记忆] {len(stale)} 个文件自上次分析后已变更，"
                f"建议重新 overview：{', '.join(stale[:10])}"
            )

        return "\n".join(parts)

    # —— 记忆清空 ——

    def clear(self) -> None:
        """清空所有项目记忆数据。

        删除整个 .codeinsight/memory/ 目录，包括文件索引、
        导入关系和问答历史。下次 ask 时将从头构建记忆。
        """
        if not self.memory_dir.exists():
            return
        for f in self.memory_dir.iterdir():
            try:
                f.unlink()
            except OSError:
                pass
        try:
            self.memory_dir.rmdir()
        except OSError:
            pass
