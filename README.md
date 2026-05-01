# CodeInsight Agent（V1 骨架版）

CodeInsight Agent 是一个只读的代码库分析命令行工具。
第一批目标是先稳定命令协议，并坚持 uv 优先的开发流程。

## 快速开始

```bash
uv sync
uv run codeinsight overview --root .
uv run codeinsight search --root . --query "create_agent"
uv run pytest
```

## 当前范围

- 提供 `overview` 和 `search` 的只读 CLI 协议
- 提供统一报告数据结构，便于后续接入更多工具
- 提供最小冒烟测试，保证迭代过程稳定
