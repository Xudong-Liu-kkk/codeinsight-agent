"""ask CLI 参数测试。"""

from codeinsight.cli import _build_parser


def test_build_parser_supports_ask_command():
    """验证：CLI 已注册 ask 子命令。"""

    parser = _build_parser()
    args = parser.parse_args([
        "ask",
        "--root",
        ".",
        "--question",
        "这个项目是做什么的？",
        "--provider",
        "ollama",
    ])
    assert args.command == "ask"
    assert args.root == "."
    assert args.question == "这个项目是做什么的？"
    assert args.provider == "ollama"
