"""pytest 共享测试配置（适配 src 布局）。

该配置的目标是让测试阶段可以直接导入本地源码，
无需先把项目打包安装为 wheel。
"""

import sys
from pathlib import Path


# PROJECT_ROOT 表示项目根目录（tests 的上一级）。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
# SRC_PATH 指向源码目录，后续会加入 Python 模块搜索路径。
SRC_PATH = PROJECT_ROOT / "src"
# 将源码目录插入 sys.path 开头，保证优先导入当前工作区代码。
sys.path.insert(0, str(SRC_PATH))

