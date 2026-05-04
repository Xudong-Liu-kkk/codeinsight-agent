"""项目长期记忆层测试。"""

from codeinsight.memory import FileEntry, ProjectMemory


def test_memory_dir_created_on_first_write(tmp_path):
    """验证：第一次写入时自动创建记忆目录。"""
    memory = ProjectMemory(root=tmp_path)
    memory.save_file_index([FileEntry(path="demo.py", mtime=12345)])
    assert (tmp_path / ".codeinsight" / "memory" / "files.json").exists()


def test_save_and_load_file_index(tmp_path):
    """验证：文件索引保存后可正确加载。"""
    memory = ProjectMemory(root=tmp_path)
    entries = [
        FileEntry(path="src/main.py", mtime=100),
        FileEntry(path="tests/test_main.py", mtime=200),
    ]
    memory.save_file_index(entries)
    loaded = memory.load_file_index()
    assert loaded["src/main.py"] == 100
    assert loaded["tests/test_main.py"] == 200
    assert len(loaded) == 2


def test_get_stale_files_detects_deleted(tmp_path):
    """验证：已删除的文件被标记为过期。"""
    memory = ProjectMemory(root=tmp_path)
    memory.save_file_index([FileEntry(path="gone.py", mtime=99999)])
    stale = memory.get_stale_files()
    assert "gone.py" in stale


def test_get_stale_files_detects_changed(tmp_path):
    """验证：mtime 变化的文件被标记为过期。"""
    real_file = tmp_path / "real.py"
    real_file.write_text("x = 1", encoding="utf-8")
    memory = ProjectMemory(root=tmp_path)
    # 存入一个过时的 mtime。
    memory.save_file_index([FileEntry(path="real.py", mtime=1)])
    stale = memory.get_stale_files()
    assert "real.py" in stale


def test_scan_and_save_finds_files(tmp_path):
    """验证：scan_and_save 扫描后保存正确的文件索引。"""
    (tmp_path / "a.py").write_text("", encoding="utf-8")
    (tmp_path / "b.py").write_text("", encoding="utf-8")
    memory = ProjectMemory(root=tmp_path)
    entries = memory.scan_and_save()
    paths = {e.path for e in entries}
    assert "a.py" in paths
    assert "b.py" in paths
    for e in entries:
        assert e.mtime > 0


def test_add_and_load_history(tmp_path):
    """验证：问答历史可追加并加载。"""
    memory = ProjectMemory(root=tmp_path)
    memory.add_history("问题1", "回答1")
    memory.add_history("问题2", "回答2")
    history = memory.load_history()
    assert len(history) == 2
    assert history[0]["question"] == "问题1"
    assert history[1]["question"] == "问题2"


def test_history_capped_at_max(tmp_path):
    """验证：历史记录自动截断，保留最近 N 条。"""
    memory = ProjectMemory(root=tmp_path)
    for i in range(10):
        memory.add_history(f"问{i}", f"答{i}")
    history = memory.load_history()
    assert len(history) == 5
    assert history[0]["question"] == "问5"
    assert history[-1]["question"] == "问9"


def test_build_context_with_memory(tmp_path):
    """验证：有记忆时 build_context 包含关键信息。"""
    (tmp_path / "main.py").write_text("", encoding="utf-8")
    memory = ProjectMemory(root=tmp_path)
    memory.scan_and_save()
    memory.add_history("这个项目做什么", "它是代码分析工具。")
    context = memory.build_context()
    assert "项目记忆" in context
    assert "main.py" in context
    assert "这个项目做什么" in context
    assert "它是代码分析工具" in context


def test_build_context_empty(tmp_path):
    """验证：无记忆时 build_context 返回空字符串。"""
    memory = ProjectMemory(root=tmp_path)
    context = memory.build_context()
    assert context == ""


def test_save_imports(tmp_path):
    """验证：导入关系可保存并加载。"""
    memory = ProjectMemory(root=tmp_path)
    memory.save_imports({"agent.py": ["engine.py", "llm.py"], "engine.py": ["tools.py"]})
    imports = memory.load_imports()
    assert imports["agent.py"] == ["engine.py", "llm.py"]
    assert len(imports) == 2
