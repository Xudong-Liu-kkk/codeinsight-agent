"""Agent 评估框架测试。"""

from codeinsight.cli import _build_parser
from codeinsight.eval import DEFAULT_CASES, EvalCase, EvalReport, EvalResult, _check_answer


class TestEvalCase:
    """评估用例单元测试。"""

    def test_default_cases_cover_core_topics(self):
        """验证：默认题库覆盖了项目核心话题。"""
        assert len(DEFAULT_CASES) >= 10
        topics = [c.question for c in DEFAULT_CASES]
        assert any("做什么" in q for q in topics)
        assert any("核心模块" in q for q in topics)
        assert any("Provider" in q or "大模型" in q for q in topics)

    def test_check_answer_all_hit(self):
        """验证：全部命中时得分 1.0。"""
        case = EvalCase(
            question="test",
            expect_keywords=["hello", "world"],
            expect_files=["demo.py"],
        )
        result = _check_answer("hello world, see demo.py for details", case, 0)
        assert result.score == 1.0
        assert result.keywords_hit == ["hello", "world"]
        assert result.files_hit == ["demo.py"]

    def test_check_answer_partial_hit(self):
        """验证：部分命中时得分为命中比例。"""
        case = EvalCase(
            question="test",
            expect_keywords=["hello", "world", "missing"],
            expect_files=[],
        )
        result = _check_answer("hello world", case, 0)
        assert result.score == 2.0 / 3.0
        assert result.keywords_miss == ["missing"]

    def test_check_answer_all_miss(self):
        """验证：全部未命中时得分 0。"""
        case = EvalCase(
            question="test",
            expect_keywords=["keyword1", "keyword2"],
        )
        result = _check_answer("nothing matches here", case, 0)
        assert result.score == 0.0

    def test_check_answer_case_insensitive(self):
        """验证：关键词匹配不区分大小写。"""
        case = EvalCase(question="test", expect_keywords=["HELLO"])
        result = _check_answer("Hello", case, 0)
        assert result.score == 1.0

    def test_default_cases_has_categories(self):
        """验证：默认题库为每道题分配了分类。"""
        categories = {c.category for c in DEFAULT_CASES}
        assert "core" in categories
        assert "tools" in categories
        assert "architecture" in categories
        assert "language" in categories


class TestCliEval:
    """CLI eval 命令测试。"""

    def test_parser_supports_eval(self):
        """验证：CLI 已注册 eval 子命令。"""
        parser = _build_parser()
        args = parser.parse_args(["eval", "--root", "."])
        assert args.command == "eval"
