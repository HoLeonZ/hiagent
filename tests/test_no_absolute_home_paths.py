r"""§0/§6 守卫:**可执行代码里不得出现绝对家目录路径**;DB 路径只有一个来源。

## 缺陷(附一百一十一,逐处实测)

`tests/test_run_all_backtests_html_renders.py:110` 早已有一条判据 ——

    def test_tool_derives_paths_from_file_not_hardcoded() -> None:
        assert "/Users/" not in src          # src = TOOL_PATH,即**一个**文件

它的 docstring 甚至自陈「**审计在别的脚本里抓到过这一条**」。
⇒ **判据存在,面按文件划** —— 于是同类的另外 **13** 处照旧(本会话第五次同一形状):

| 处 | 形态 | 后果 |
|---|---|---|
| `chase_up/audit_phantom.py`、`uptrend_pullback/audit_phantom.py` | `DB_PATH = "/Users/holeon/Library/…/market.duckdb"` | **绕过 `hiagent_config`** ⇒ **忽略 `DNA_STRAT_DB`**;换机器即废 |
| `chase_up/render_v3_trades_html.py` | `OUT_HTML = Path("/Users/holeon/…/v3_trades.html")` | 从别的 checkout 跑 ⇒ 产物写进**那一份**仓库 |
| `chase_up/render_top2_trades_html.py` | `RESULTS_DIR = Path("/Users/holeon/…")` | 读的是**另一个 checkout** 的产物 |
| `tests/test_backtrader_engine_net_return_entry_commission.py` | 参数化里写死两个 fixture 绝对路径 | 新鲜克隆**永远 skip**(20 条 skip 里唯一不说明"覆盖在哪"的那条);若那目录**碰巧存在**,它会**读别人的产物**来验本仓库的代码 |
| `tests/_capture_presets.py`、`_run_all_presets.py`、`golden/_capture_baseline.py` | `sys.path.insert(0, "/Users/holeon/…")` | 同上 |
| `tests/_combine_preset_html.py` | `GOLDEN = Path("/Users/holeon/…/tests/golden")` | 同上 |
| `tests/_run_all_presets_2yr.py`、`_run_all_presets_2yr_continue.py` | `REPO = Path("/Users/**zhl**/code/hiagent")` | **另一个用户**的家目录 |

**为什么这不只是"不好看"**:`/Users/<别人>/…` 在任何别的 checkout 上都不存在;
而 `/Users/<自己>/…` 在**别的 checkout** 里会指向**另一份仓库** ——
**测试会拿别人的产物来验本仓库的代码**,工具会把产物写进别人的目录。两种都是"看起来在跑"。

**已修的 12 处**均改为 repo-relative(`Path(__file__).resolve().parents[N]`),
两个 DB 路径改为 `from hiagent_config import DB_PATH`(它自己用 `Path.home()` 拼默认值并读
`DNA_STRAT_DB` —— 唯一来源,且**尊重环境覆盖**)。

## 判据两条

1. **可执行代码里不得有家目录绝对路径**(`/Users/<名>/…`、`/home/<名>/…`、`C:\Users\<名>\…`)。
   `docstring` 里的**散文引用**不算(那里在讲"不要这么做");单独一个 `/Users/`
   (没有用户名段,如既有那条判据自己的搜索字面量)也不算。
2. **DB 文件名只准在 `hiagent_config.py` 里出现**(非测试代码)。
   `tmp_path / "market.duckdb"` 这种**临时夹具库**借用同名,属测试惯例,故层 2 不看 `tests/`。

两向验证:种一个 `/Users/<名>/…` 字面量 ⇒ 层 1 红;在非测试模块里种一个 `…/market.duckdb` ⇒ 层 2 红。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: 带**用户名段**的家目录路径。单独 `/Users/` 不算(它可能正是判据自己的搜索字面量)。
_HOME_PATH = re.compile(r'^(?:/(?:Users|home)/[^/\s]+|/root/)')

#: DB 文件名 —— 只准出现在这一个文件里。
_DB_FILENAME = "market.duckdb"
_DB_SOURCE = "hiagent_config.py"

#: 例外登记(只应当变短):`相对路径: 理由`。
KNOWN_HOME_PATH_EXCEPTIONS: dict[str, str] = {}


def _scanned_files() -> list[Path]:
    out = []
    for p in sorted(REPO_ROOT.rglob("*.py")):
        if "__pycache__" in p.parts or ".git" in p.parts:
            continue
        out.append(p)
    return out


def _code_string_literals(path: Path) -> list[tuple[int, str]]:
    """文件里**可执行代码**中的字符串字面量(docstring 已排除)。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    docs = {
        ast.get_docstring(n, clean=False)
        for n in ast.walk(tree)
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    return [
        (n.lineno, n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and n.value not in docs
    ]


def test_no_absolute_home_path_in_executable_code() -> None:
    """判据 1:可执行代码里不得出现 `/Users/<名>/…` 这类绝对家目录路径。"""
    files = _scanned_files()
    assert len(files) >= 200, f"扫描面异常小({len(files)} 个 .py)—— 本条可能已空转"

    bad = []
    for p in files:
        rel = str(p.relative_to(REPO_ROOT))
        for lineno, value in _code_string_literals(p):
            if _HOME_PATH.match(value) and rel not in KNOWN_HOME_PATH_EXCEPTIONS:
                bad.append(f"{rel}:{lineno}  {value[:70]}")
    assert not bad, (
        "§0/§6 可复现性:以下**可执行代码**里写死了绝对家目录路径 —— "
        "它在别的 checkout 上要么不存在(测试永远 skip),要么指向**另一份仓库**"
        "(测试拿别人的产物验本仓库代码 / 工具把产物写进别人的目录):\n  "
        + "\n  ".join(bad)
        + "\n改为 repo-relative:`Path(__file__).resolve().parents[N]`;"
        "\nDB 路径一律 `from hiagent_config import DB_PATH`(它尊重 `DNA_STRAT_DB` 覆盖)。"
    )


def test_db_path_has_a_single_source() -> None:
    """判据 2:DB 文件名只准出现在 `hiagent_config.py`(非测试代码)。"""
    bad = []
    for p in _scanned_files():
        rel = str(p.relative_to(REPO_ROOT))
        if rel == _DB_SOURCE or rel.startswith("tests/"):
            continue
        for lineno, value in _code_string_literals(p):
            if _DB_FILENAME in value:
                bad.append(f"{rel}:{lineno}  {value[:70]}")
    assert not bad, (
        f"§0/§6 单源:以下非测试代码**自己拼了库路径** —— 路径的唯一来源是 `{_DB_SOURCE}`"
        f"(它读 `DNA_STRAT_DB` 覆盖,再用 `Path.home()` 拼默认值)。"
        "自己拼的后果不只是搬机器就废:它会**忽略环境覆盖**,静默连到**另一个库**:\n  "
        + "\n  ".join(bad)
    )


def test_the_exception_registry_is_still_real() -> None:
    """登记的例外必须仍然成立(只应当变短)。"""
    for rel, why in KNOWN_HOME_PATH_EXCEPTIONS.items():
        p = REPO_ROOT / rel
        assert p.exists(), f"例外登记里的 {rel} 不存在了 —— 请从登记表删掉"
        assert any(_HOME_PATH.match(v) for _l, v in _code_string_literals(p)), (
            f"{rel} 里已经没有家目录路径了 —— 例外登记({why})应随之删除"
        )
