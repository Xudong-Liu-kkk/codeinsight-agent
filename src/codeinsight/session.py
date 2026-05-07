"""会话级短期记忆模块。

与长期记忆（跨会话持久化）不同，短期记忆在同一个 session 内缓存
最近几轮的分析发现，让 Agent 在连续追问时无需重复搜索。

数据仅存在于进程内存中，进程退出后自动清除。
"""

import time


# 单个 session 最多缓存的轮数。
_MAX_ROUNDS = 5
# 缓存过期时间（秒），超时后自动清除。
_TTL_SECONDS = 1800  # 30 分钟


class SessionMemory:
    """会话级短期记忆管理器。

    每个 session_id 对应一个独立的记忆槽，存储最近 N 轮的
    分析发现列表（findings），供后续追问时作为上下文注入。
    """

    def __init__(self) -> None:
        # _store: {session_id: {"findings": [...], "question": str, "timestamp": float}}
        self._store: dict[str, dict] = {}

    def _clean_expired(self) -> None:
        """清理过期的 session 数据。"""
        now = time.time()
        expired = [
            sid for sid, data in self._store.items()
            if now - data.get("timestamp", 0) > _TTL_SECONDS
        ]
        for sid in expired:
            del self._store[sid]

    def save(self, session_id: str, question: str, findings: list[str]) -> None:
        """保存一轮分析发现到 session 记忆。

        Args:
            session_id: 会话标识。
            question: 用户问题。
            findings: 本轮分析发现列表。
        """
        self._clean_expired()
        if session_id not in self._store:
            self._store[session_id] = {"rounds": [], "timestamp": time.time()}
        entry = self._store[session_id]
        entry["rounds"].append({
            "question": question,
            "findings": findings,
            "timestamp": int(time.time() * 1000),
        })
        # 只保留最近 N 轮。
        entry["rounds"] = entry["rounds"][-_MAX_ROUNDS:]
        entry["timestamp"] = time.time()

    def build_context(self, session_id: str) -> str:
        """构造可注入 prompt 的上下文文本。

        将最近几轮的分析发现格式化为一段文本，
        帮助 Agent 在当前追问中复用之前的分析结果。

        Args:
            session_id: 会话标识。

        Returns:
            格式化后的上下文文本，无历史时返回空字符串。
        """
        self._clean_expired()
        entry = self._store.get(session_id)
        if not entry or not entry.get("rounds"):
            return ""

        parts: list[str] = ["[会话记忆] 本轮之前已分析的内容："]
        for i, r in enumerate(entry["rounds"], 1):
            parts.append(f"\n第 {i} 轮 问：{r['question']}")
            parts.append("答（关键发现）：")
            for finding in r["findings"]:
                # 每条发现最多取 500 字符，避免上下文膨胀。
                parts.append(f"  - {finding[:500]}")

        return "\n".join(parts)

    def clear(self, session_id: str) -> None:
        """清除指定 session 的记忆。"""
        self._store.pop(session_id, None)


# 全局单例，进程内共享。
_global_session_memory = SessionMemory()


def get_session_memory() -> SessionMemory:
    """返回全局会话记忆实例。"""
    return _global_session_memory
