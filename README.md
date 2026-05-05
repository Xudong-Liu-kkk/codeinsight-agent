# CodeInsight Agent

[![Test](https://github.com/your-username/codeinsight-agent/actions/workflows/test.yml/badge.svg)](https://github.com/your-username/codeinsight-agent/actions/workflows/test.yml)

基于 LangGraph **多 Agent 协作**的代码库分析工具（CLI + REST API + SSE 流式）。

四个独立 Agent — Planner / Reader / Reviewer / Synthesizer — 各司其职，通过 LangGraph 协作图编排。支持自然语言问答、代码审查、Git PR 审查、自动修复、依赖分析、错误诊断等 11 个命令。每次回答附带**证据链追溯**，项目启动后自动加载**长期记忆**。

## 快速开始

```bash
uv sync
uv run codeinsight overview --root .
uv run codeinsight search --root . --query "run_search"
uv run codeinsight read --root . --path src/codeinsight/engine.py --start 1 --end 40
uv run codeinsight diagnose --root . --text "RuntimeError: failed"
uv run codeinsight ask --root . --question "这个项目是做什么的？" --provider ollama
uv run codeinsight review --root . --path src/codeinsight/agent.py
uv run codeinsight deps --root .
uv run codeinsight pr-review --root .
uv run codeinsight fix --root . --issue "第 85 行可能返回 None"
uv run codeinsight serve --root . --port 8888
uv run pytest
```

## 大模型 Provider 配置

V1 通过 OpenAI 兼容接口抽象 Provider，不把项目绑定到某一家模型服务。

当前支持：

- `openai`
- `deepseek`
- `qwen`
- `ollama`

通用环境变量：

```bash
CODEINSIGHT_LLM_PROVIDER=ollama
CODEINSIGHT_LLM_MODEL=qwen2.5-coder:7b
CODEINSIGHT_LLM_BASE_URL=http://localhost:11434/v1
```

也可以在命令中临时指定 Provider：

```bash
uv run codeinsight ask --root . --question "这个项目是做什么的？" --provider ollama
```

常见配置示例：

```bash
# OpenAI
set CODEINSIGHT_LLM_PROVIDER=openai
set OPENAI_API_KEY=你的_key

# DeepSeek
set CODEINSIGHT_LLM_PROVIDER=deepseek
set DEEPSEEK_API_KEY=你的_key

# 通义千问 / DashScope
set CODEINSIGHT_LLM_PROVIDER=qwen
set DASHSCOPE_API_KEY=你的_key

# 本地 Ollama
set CODEINSIGHT_LLM_PROVIDER=ollama
```

## 当前命令

### 自然语言提问

```bash
uv run codeinsight ask --root . --question "这个项目是做什么的？"
```

`ask` 是 Agent 主入口，通过四个独立 Agent 协作分析代码库：

- `overview`：获取项目结构概览
- `search`：按关键词搜索代码
- `read`：读取文件内容片段
- `diagnose`：解析 Python traceback
- `deps`：分析项目依赖配置

与固定流程不同，模型会根据问题自行判断：先调哪个工具、调几次、是否需要合并多个工具的结果，然后基于真实代码上下文生成中文分析回答。

可以指定 Provider：

```bash
uv run codeinsight ask --root . --question "run_search 是做什么的？" --provider qwen
```

### 生成项目概览

```bash
uv run codeinsight overview --root .
```

`overview` 会扫描项目目录结构，返回目录数量、文件数量和部分结构样例，适合快速了解一个代码库。

### 搜索代码关键词

```bash
uv run codeinsight search --root . --query "run_search"
```

`search` 会在项目内搜索关键词或符号名，并返回命中的文件、行号和代码片段。

可以使用 `--glob` 缩小搜索范围：

```bash
uv run codeinsight search --root . --query "AnalysisReport" --glob "*.py"
```

### 读取项目内文件片段

```bash
uv run codeinsight read --root . --path src/codeinsight/engine.py --start 1 --end 40
```

`read` 会在安全边界内读取项目内文件内容，支持指定起止行，并自动限制最大返回行数。

也可以显式控制最大返回行数：

```bash
uv run codeinsight read --root . --path README.md --start 1 --max-lines 20
```

### 诊断 Python 报错

```bash
uv run codeinsight diagnose --root . --text "ValueError: bad value"
```

`diagnose` 可以解析 Python traceback 或普通错误文本，提取异常类型、异常消息和项目内相关源码片段。

也可以从文件读取 traceback：

```bash
uv run codeinsight diagnose --root . --traceback-file traceback.txt
```

### 代码审查

```bash
uv run codeinsight review --root . --path src/codeinsight/agent.py
```

`review` 会对指定文件执行只读代码审查，基于大模型生成包含总体评价、风险点、改进建议的结构化审查报告。

可以指定 Provider 和最大读取行数：

```bash
uv run codeinsight review --root . --path src/codeinsight/agent.py --provider qwen --max-lines 200
```

### 依赖分析

```bash
uv run codeinsight deps --root .
```

`deps` 会解析 `pyproject.toml` 中的运行时依赖和开发依赖，检测 `uv.lock` 锁文件，并输出依赖统计与风险提示。

### Git PR 审查

```bash
uv run codeinsight pr-review --root .
```

`pr-review` 读取当前未提交的 git diff，结合文件内容交给大模型生成结构化审查报告（变更概要、风险评估、逐文件 Review）。

也支持审查指定 commit 或分支对比：

```bash
uv run codeinsight pr-review --root . --commit HEAD
uv run codeinsight pr-review --root . --base main --head feature-x
```

### 自动修复

```bash
uv run codeinsight fix --root . --issue "第 85 行可能返回 None，需要加空值检查"
```

`fix` 根据 issue 描述搜索相关代码、读取文件、让大模型生成精确修复方案，展示 diff 后由用户确认并应用。修改前自动创建 `.bak` 备份文件。

### 聚焦审查指定函数

```bash
uv run codeinsight review --root . --path src/codeinsight/agent.py --symbol run_ask
```

`--symbol` 用 ast 精确定位函数/类源码，只审查该符号而非整个文件。

### 清空项目记忆

```bash
uv run codeinsight memory-clear --root .
```

### REST API 服务

```bash
uv run codeinsight serve --root . --port 8888
# 打开 http://127.0.0.1:8888/docs 查看 Swagger 文档
```

`serve` 启动 FastAPI 服务，暴露 10 个 REST 端点。其中 `/ask/stream` 通过 SSE 实时推送 Agent 分析过程。

### JSON 输出

所有当前命令都支持 `--json`，便于后续接入脚本或上层系统：

```bash
uv run codeinsight overview --root . --json
uv run codeinsight search --root . --query "run_search" --json
uv run codeinsight read --root . --path src/codeinsight/engine.py --start 1 --end 40 --json
uv run codeinsight diagnose --root . --text "RuntimeError: failed" --json
uv run codeinsight ask --root . --question "这个项目是做什么的？" --json
uv run codeinsight review --root . --path src/codeinsight/agent.py --json
uv run codeinsight deps --root . --json
```

## 当前范围

- 提供 `ask`、`overview`、`search`、`read`、`diagnose`、`review`、`deps`、`pr-review`、`fix`、`serve`、`memory-clear` 十一个 CLI 命令
- 多 Agent 协作：Planner / Reader / Reviewer / Synthesizer 四个独立 Agent，各有专属 prompt 和工具集
- `ask` 附带证据链追溯 + CLI 逐 token 流式输出 + SSE 流式 API
- `serve` 启动 FastAPI 服务，10 个 REST 端点 + Swagger 文档
- `review` 支持 `--symbol` 聚焦审查函数/类
- `pr-review` 支持 commit、分支对比、工作区变更三种模式
- `fix` 自动搜索 → 生成修复 → 展示 diff → 确认 → 应用 → 跑测试 → 失败回滚
- `diagnose` 覆盖 10 种常见 Python 异常的专项排查建议
- 项目长期记忆：文件索引、问答历史持久化到 `.codeinsight/memory/`
- `.env` 自动加载 + 多 Provider 兼容（openai / deepseek / qwen / ollama）
- CI：GitHub Actions 自动测试，104 个测试用例

## 开发约定

- 使用 `uv sync` 安装依赖
- 使用 `uv run pytest` 运行测试
- 使用环境变量配置大模型 Provider，不要把 API Key 写入代码或提交到仓库
- 生成文件不应提交到仓库，例如：
  - `__pycache__/`
  - `*.pyc`
  - `.pytest_cache/`
  - `.venv/`
  - `*.egg-info/`

## 版本历程

| 版本 | 内容 |
|---|---|
| V1 | 只读 CLI（overview / search / read / diagnose / ask / review / deps） |
| V2 | LangGraph 多步分析 + 证据链追溯 + 项目长期记忆 + diagnose 增强 |
| V3 | Git PR 审查 + .env 自动加载 + 搜索过滤优化 |
| V4 | fix 自动修复（搜索→生成→确认→应用→测试→回滚） |
| V5 | 多 Agent 协作（Planner / Reader / Reviewer / Synthesizer 子 Agent） |
| API | FastAPI REST + SSE 流式接口 |

## 下一步计划

- **Docker 容器化**：`docker compose up` 一键部署
- **测试覆盖率报告**：pytest --cov 量化测试覆盖
- **支持更多项目类型**：`requirements.txt`、`Pipfile` 等依赖格式
