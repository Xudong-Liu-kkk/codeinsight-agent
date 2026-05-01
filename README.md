# CodeInsight Agent（V1 只读版）

CodeInsight Agent 是一个基于 Python 与 uv 的只读代码库分析命令行工具。

V1 阶段的核心目标是：先稳定命令协议、报告结构和只读工具层，让后续功能可以在安全边界内逐步增强。当前版本不会修改用户代码，也不会主动执行高风险操作。

## 快速开始

```bash
uv sync
uv run codeinsight overview --root .
uv run codeinsight search --root . --query "run_search"
uv run codeinsight read --root . --path src/codeinsight/engine.py --start 1 --end 40
uv run codeinsight diagnose --root . --text "RuntimeError: failed"
uv run pytest
```

## 当前命令

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

### JSON 输出

所有当前命令都支持 `--json`，便于后续接入脚本或上层 Agent：

```bash
uv run codeinsight overview --root . --json
uv run codeinsight search --root . --query "run_search" --json
uv run codeinsight read --root . --path src/codeinsight/engine.py --start 1 --end 40 --json
uv run codeinsight diagnose --root . --text "RuntimeError: failed" --json
```

## 当前范围

- 提供 `overview`、`search`、`read`、`diagnose` 四个只读 CLI 命令
- `overview` 已接入真实目录扫描与结构证据输出
- `search` 已接入真实关键词搜索，优先使用 `rg`，不可用时回退到 Python 搜索
- `read` 已支持按行读取项目内安全文件片段
- `diagnose` 已支持解析 Python traceback，并读取项目内相关代码上下文
- 提供路径安全保护，默认禁止读取项目根目录外路径和常见敏感文件
- 提供统一报告数据结构，便于后续接入更多工具
- 提供工具层与引擎层测试，保证迭代过程稳定

## 开发约定

- 使用 `uv sync` 安装依赖
- 使用 `uv run pytest` 运行测试
- 生成文件不应提交到仓库，例如：
  - `__pycache__/`
  - `*.pyc`
  - `.pytest_cache/`
  - `.venv/`
  - `*.egg-info/`

## 下一步计划

- 增强 `diagnose`，针对 `ImportError`、`FileNotFoundError`、`ModuleNotFoundError` 等常见异常给出专门建议
- 进一步完善报告展示格式，让终端输出更适合人类阅读
- 评估是否加入更高层的分析工作流，将 `search`、`read`、`diagnose` 组合成更自动化的排查流程
