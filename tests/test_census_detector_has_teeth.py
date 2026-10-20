"""附七十七 —— 普查工具自己的**牙齿**:种下真形状必须认得出,种下合法形状不得误报。

`tests/_census_comment_guards.py` 是个**候选发现器**(不是门禁)。它第一版就坏在
"正则只认双引号"上 —— 而 `ast.unparse` 输出的是**单引号** ⇒ 所有路径都被过滤掉,
它报的是 **0 候选**。如果当时我直接采信"0 命中 = 干净",就会漏掉它本该发现的形状。

故这两条用例是它的**前提**:没有它们,"0 候选"无法区分"代码干净"与"检测器坏了"。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _census():
    spec = importlib.util.spec_from_file_location(
        "census_comment_guards", REPO_ROOT / "tests" / "_census_comment_guards.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _build_tree(tmp_path: Path, *, token_in_code: bool) -> tuple[Path, Path]:
    """造一棵最小树:`mod.py`(token 在注释里 或 在代码里)+ 一条断言它的测试。"""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    mod = repo / "mod.py"
    if token_in_code:
        mod.write_text(
            'def f():\n    # 提到 FOO_TOKEN 的注释\n    return "FOO_TOKEN"\n',
            encoding="utf-8",
        )
    else:
        mod.write_text(
            'def f():\n    # 只有注释提到 FOO_TOKEN\n    return 1\n',
            encoding="utf-8",
        )
    (repo / "tests" / "test_x.py").write_text(
        "from pathlib import Path\n"
        "REPO = Path(__file__).resolve().parents[1]\n"
        "MOD = REPO / 'mod.py'\n"
        "def test_guard():\n"
        "    src = MOD.read_text(encoding='utf-8')\n"
        "    assert 'FOO_TOKEN' in src\n",
        encoding="utf-8",
    )
    return repo, repo / "tests"


def test_detector_catches_a_comment_only_guard(tmp_path) -> None:
    """真形状(词只在注释里)⇒ 必须被列出。"""
    mod = _census()
    repo, tests_dir = _build_tree(tmp_path, token_in_code=False)
    hits = mod.find_comment_only_guards(tests_dir, repo)
    assert any(h[3] == "FOO_TOKEN" for h in hits), f"没认出来:{hits}"


def test_detector_does_not_flag_a_token_that_is_in_code(tmp_path) -> None:
    """合法形状(词在代码里出现)⇒ 不得误报。"""
    mod = _census()
    repo, tests_dir = _build_tree(tmp_path, token_in_code=True)
    hits = mod.find_comment_only_guards(tests_dir, repo)
    assert not hits, f"误报了:{hits}"


def test_repo_scan_runs_and_reports_candidates() -> None:
    """对**本仓库**跑一遍:必须能跑通,并如实打印候选(不做判定)。

    当前已知的候选都是**误报**(守卫的主题本身就是注释: `# noqa: …` 标记、docstring 措辞)。
    这条只保证"工具能跑",不保证"候选为 0" —— 后者需要人工分类。
    """
    mod = _census()
    hits = mod.find_comment_only_guards(REPO_ROOT / "tests", REPO_ROOT)
    assert isinstance(hits, list)
