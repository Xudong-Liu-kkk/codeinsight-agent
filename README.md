# CodeInsight Agent（V1 只读 Agent 版 · LangChain）

CodeInsight Agent 是一个基于 LangChain Agent 框架 + uv 的只读代码库分析工具。

`ask` 命令通过 LangChain 的 `create_agent` 让大模型自主决定调用哪些只读工具，每次回答附带**证据链追溯**（可查看每个结论来源于哪个文件）；项目启动后自动建立**长期记忆**，后续问答无需重复扫描。

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

`ask` 是 V1 的 Agent 主入口，通过 LangChain `create_agent` 让大模型自主决定调用哪些只读工具：

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

- 提供 `ask`、`overview`、`search`、`read`、`diagnose`、`review`、`deps` 七个只读 CLI 命令
- `ask` 通过 LangChain Agent 让模型自主选择工具，回答附带证据链追溯
- `review` 已接入大模型，对指定文件执行只读代码审查
- `deps` 已支持解析 pyproject.toml 依赖配置并检测锁文件
- 项目长期记忆：文件索引、问答历史持久化到 `.codeinsight/memory/`，后续 ask 自动加载
- Provider 抽象已兼容 `openai`、`deepseek`、`qwen`、`ollama`
- `overview` 已接入真实目录扫描与结构证据输出
- `search` 已接入真实关键词搜索，优先使用 `rg`，不可用时回退到 Python 搜索
- `read` 已支持按行读取项目内安全文件片段
- `diagnose` 已支持解析 Python traceback，并读取项目内相关代码上下文
- 提供路径安全保护，默认禁止读取项目根目录外路径和常见敏感文件
- 提供统一报告数据结构，便于 CLI、工具层和 Agent 层协作
- 提供工具层、Provider 层和 Agent 编排层测试，保证迭代过程稳定

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

## V1 完成状态

V1 已完成“只读代码库分析 Agent”的最小闭环：

1. 用户通过 `ask` 输入自然语言问题。
2. Agent 自动调用只读工具收集项目上下文。
3. 大模型基于真实代码上下文生成中文回答。
4. 所有底层能力仍保留可单独调用的 CLI 命令，便于调试和脚本化使用。

## 下一步计划（V2）

V1 已完成七个只读命令闭环，Agent 工具选择已升级为 LangChain 自主调用，证据链追溯和项目长期记忆已落地。剩余方向：

- **LangGraph 多步自主分析**：用 StateGraph 搭建 Planner → Executor → Reviewer 循环，让 Agent 自我验证、自动推进复杂任务
- **支持 `.env` 文件**：自动加载项目目录下的 `.env` 文件，简化环境变量配置
- **支持更多项目类型**：`requirements.txt`、`Pipfile` 等依赖格式的解析
