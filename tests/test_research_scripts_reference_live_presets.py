"""§5/§6 守卫:研究脚本引用的 preset 必须**仍然存在**。

**发现**(audit 2026-10-15):short_reversal 的 preset 列表在历史迭代中被大幅裁剪
(现在 75 个),但下游的研究脚本仍在引用被删掉的 preset 名。这些脚本在运行第一行就
`SystemExit("preset ... 不在 PRESETS")` —— 它们**跑不起来**:

  `wf_v34_focused.py` → `v34_mainboard_pctchg_tight`(v34 系列已全部不存在)
  `wf_v37_focused.py` → `v37_liq_3e7_5e8`       (v37 系列已全部不存在)
  `wf_v39_focused.py` → `v39_pctchg_04_09`      (只剩 v39_pctchg_03_10)
  `wf_v41_focused.py` → `v41_pctchg_04_10`      (v41 系列已全部不存在)

**为什么值得一条守卫**:这类失效是**静默积累**的 —— 删 preset 时不会有任何东西提示
"有 N 个脚本在引用它"。而它们正是 §5 的执行层(DSR / WFV / n_trials 都在这些脚本里),
跑不起来就等于那一段纪律**没有任何执行者**。

**如何处置**:不改名 —— 被删的 preset 没有留下可推断的重命名映射
(v34/v37/v41 系列**一个都不剩**),把名字改成某个"看起来像"的 preset 就是**编造
实验记录**(见 附十三 §3)。故采用"登记债务"的处置:
  · 本文件的 `KNOWN_DEAD_REFERENCES` 是**登记表**,值 = (`名字元组`, `删除它的提交`);
  · 实际集合必须**等于**登记表 —— 新增失效会失败(被抓住),修好一个而不同步删除登记项
    也会失败(防止登记表变成永久借口);
  · 每条**出处**由 `test_each_registered_removal_commit_really_removed_it` 去问 **git**
    (该提交的父版本里有、该提交里没有)—— 不能拿登记表验登记表。

**登记表里现在有 10 条,是**两类**东西**(附一百零八 分清):

| 类 | 例 | 性质 |
|---|---|---|
| 冻结的研究脚本 | `wf_v3*_focused.py`、`bt_compare_presets.py`、`run_sizing_comparison.py` | 存在的意义就是记录一个已被删掉的 preset;**失败信息由我们撰写**(指出出处与登记位置),故 `SCRIPTS_WITH_AUTHORED_MESSAGE` 列的就是这 6 个 |
| **活工具** | `short_reversal/main.py`、`scan_signals{,_fast}.py`、`uptrend_pullback/render_trades_html.py` | `--preset` 的**默认值**或**兜底列表**指向已删的 preset ⇒ **不传参就跑不起来**;失败来自库里的 `ValueError`(同样响亮,列出全部可用名) |

第二类是 附一百零八 才**看得见**的:它们的引用写成 `default="…"` 与**字面量列表的元素**,
不在这条守卫原本认的四种**调用式**里 —— 而它们此前**连扫描面都不在**(面按文件名划)。
"""
from __future__ import annotations

import glob
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

#: 已知失效引用(债务登记)。修好其中一个 → 必须同时从这里删掉。
#:
#: **由来**(2026-10-15 从 git 史查清,不是猜的):那四个 preset 是在提交 `4b7eab0`
#: ("iter #2 CLAUDE.md fixes")中被**裁剪**的 —— 该提交对 `short_reversal/presets.py`
#: 减 212 行 / 增 66 行,是**删除而非重命名**。故**不存在**可安全回指的替代名:
#: 把脚本改成某个"看起来像"的 preset 就是编造实验记录(见附十三 §3)。
#:
#: 那四个脚本现在**自己**把这段由来写进失败信息(跑一下就会看到裁剪提交与登记位置),
#: 免得下一个人还要重查一遍 git 史。
#: 另注:`v41_pctchg_04_10` 当初是作为**单点过拟合失败案例**引入的(见 `0a80f74`),
#: 也就是说被裁掉的那个 preset 本身就是一份负面证据 —— 这是它们值得**保留**
#: 而不是删除的原因。
PRUNED_IN_COMMIT = "4b7eab0"

#: 值 = (preset 名, **删除它的那个提交**)。
#:
#: ⚠️ 附一百零八:此前只记 preset 名,而守卫里**硬断言**消息含 `4b7eab0` ——
#: 那只对最早的四个成立。实测这些 preset 来自**三个不同提交**(4b7eab0 / e3cd4f9 / 03cb590),
#: 写死一个的话,另外几条的"出处"就永远对不上(而它们本来是对的)。
#:
#: 出处的**独立性**:每一条都由 `test_each_registered_removal_commit_really_removed_it`
#: 用 git 史核对(该提交的父版本里有这个名字、该提交里没有)—— 而不是只看登记表自己怎么写。
#: (这条守卫是补上来的:此前"出处"只在脚本的失败**信息**里被断言,而信息与登记表互相印证,
#:  于是**登记错了也全绿**。)
KNOWN_DEAD_REFERENCES = {
    # ⚠️ 附一百零八 新增:这两个文件此前**不在扫描面内**(按文件名划的族漏了它们),
    # 一旦改成按内容推导就暴露出来。同 附十三 的处置:**登记而非改名** ——
    # 不存在可推断的重命名映射,改成"看起来像"的 preset 就是编造实验记录。
    "uptrend_pullback/bt_compare_presets.py": (("v33_long_reverse_v3",), "03cb590"),
    "run_sizing_comparison.py": (("v6",), "e3cd4f9"),
    # ⚠️ 附一百零八 新增的**四条**(由"引用式的识别面"从四式扩到七式后暴露,
    # 见 `_DEFAULT` / `_BARE` / `_PRESET_NAME_IDIOM` 附近的注释):
    # 它们的引用写成了**另一类形态** —— `--preset` 的 `default=` 与**字面量列表的元素**,
    # 而旧守卫只认四种"调用式",于是这四处全都看不见。
    # 与上面那批的**不同之处**(值得记下):这不是"冻结的研究脚本",而是**活工具**:
    #   · `short_reversal/main.py` 不传 `--preset` 就**跑不起来**(`-m short_reversal.main`);
    #   · `scan_signals.py` / `scan_signals_fast.py` 的**兜底 preset 列表**两项都死了;
    #   · `uptrend_pullback/render_trades_html.py` 不传 `--preset` 同样跑不起来。
    # 四处都经 `get_preset()` / `run_backtest_v3()` **响亮失败**(ValueError 会列出全部可用名),
    # 所以不是静默错误;要恢复成"裸跑可用"就必须**替它们选一个当时都想不起的**preset ——
    # 那正是 附十三 §3 不做的事(编造实验记录)。故同样只登记,并把"默认值已死"这件事说清。
    "short_reversal/main.py": (("v33_mainboard_tp6_sl005_mh5_realistic",), "4b7eab0"),
    "short_reversal/scan_signals.py": (("v33_mainboard_tp6_sl005_mh5_realistic",
                                        "v33_mainboard_tp2_sl05_dneg"), "4b7eab0"),
    "short_reversal/scan_signals_fast.py": (("v33_mainboard_tp6_sl005_mh5_realistic",
                                             "v33_mainboard_tp2_sl05_dneg"), "4b7eab0"),
    "uptrend_pullback/render_trades_html.py": (("v6",), "e3cd4f9"),
    # (以下四条是 2026-10-15 那批,出处同为 `4b7eab0`。)
    "short_reversal/wf_v34_focused.py": (("v34_mainboard_pctchg_tight",), "4b7eab0"),
    "short_reversal/wf_v37_focused.py": (("v37_liq_3e7_5e8",), "4b7eab0"),
    "short_reversal/wf_v39_focused.py": (("v39_pctchg_04_09",), "4b7eab0"),
    "short_reversal/wf_v41_focused.py": (("v41_pctchg_04_10",), "4b7eab0"),
}

#: 其中**失败信息由我们自己写**的那些(把出处与登记位置写进了 `SystemExit` 文本)。
#:
#: 只有这些能被 `test_such_a_script_reports_where_its_preset_went` **跑一遍、读它的输出**来验证;
#: 另外四条是活工具,它们的失败来自库里的 `ValueError`(同样响亮,但文本不归我们写,
#: 且跑起来会真的执行回测/写报表)。故把"信息里写了出处"这件事**限定在写过的那些**上,
#: 而不是拿它去要求所有登记项 —— 否则等于要求"每个死引用都得配一句我们编的说明"。
SCRIPTS_WITH_AUTHORED_MESSAGE = {
    "uptrend_pullback/bt_compare_presets.py",
    "run_sizing_comparison.py",
    "short_reversal/wf_v34_focused.py",
    "short_reversal/wf_v37_focused.py",
    "short_reversal/wf_v39_focused.py",
    "short_reversal/wf_v41_focused.py",
}

#: §5 Iterative-Tuning Accounting 的**未记录试验数**登记。
#:
#: 规则:若某 preset 的参数值出现在**该引擎自己 shipped 的 sweep 脚本**的默认候选里,
#: 那么"这个值不是 sweep 选出来的"就需要证据 —— 否则 `n_comparisons` 应把那次 sweep
#: 计进去。登记在案的表示"矛盾已被发现,但真实迭代数需要人提供记录"。
KNOWN_UNRECORDED_TRIAL_COUNTS = {
    "cycle_price_action/PRESET_V1": (
        "threshold=2.0 落在 sweep_thresholds.py 默认候选 1.5,2.0,2.5 内,"
        "但 n_comparisons=1(『无 sweep』的说法与仓库自身矛盾);"
        "真实累计试验数需迭代记录"
    ),
}

#: 研究脚本(sweep / walk-forward / grid)。§5 的执行层就在这些文件里。
SCRIPT_GLOBS = {
    "short_reversal": ("short_reversal/wf_*.py", "short_reversal/grid*.py",
                       "short_reversal/sweep*.py"),
    "chase_up": ("chase_up/sweep*.py", "chase_up/wf_*.py"),
    "uptrend_pullback": ("uptrend_pullback/sweep*.py",),
    "cycle_price_action": ("cycle_price_action/sweep*.py",),
}

#: **前缀 glob 抓不到的 DSR 调用点**(附八十六)。
#:
#: 上面那组 glob 是按**文件名前缀**划的族,而这一族并不是按前缀划的:
#:   · `short_reversal/wf_*.py` 匹配 `wf_v39_focused.py`,**匹配不到** `walkforward.py`
#:     (`wa` 开头;附八十五 就是栽在这个前缀上);
#:   · `iter_reverse.py` 既不是 `sweep*` 也不是 `wf_*`;
#:   · `cycle_price_action/walkforward.py` / `main.py` 同理。
#: 实测:调用 `deflated_sharpe_ratio` 的脚本共 **29** 个,而 SCRIPT_GLOBS 只覆盖 **25** 个
#: —— **这 4 个脚本对下面三条 §5 守卫完全不可见**(收益率当 Sharpe、max/n_trials 不匹配、
#: 引用已死的 preset,一条都查不到它们)。
#:
#: 故:族仍用 glob 表达(便于新增同类文件自动纳入),但**必须并上这份显式名单**;
#: 并由 `test_research_scripts_cover_every_dsr_caller` 做集合对账 —— 名单不可能再悄悄变短。
SCRIPT_EXPLICIT = (
    "short_reversal/walkforward.py",
    "uptrend_pullback/iter_reverse.py",
    "cycle_price_action/walkforward.py",
    "cycle_price_action/main.py",
    # 附一百零九: `uptrend_pullback/grid.py` 此前**不报** DSR(§5 Penalty Metrics 缺口),
    # 本批补上后它就成了一个新的 DSR 调用点 —— 而前缀 glob `uptrend_pullback/sweep*.py`
    # **匹配不到 `grid.py`**。是这条守卫自己把它抓出来的(它的职责正是这个)。
    "uptrend_pullback/grid.py",
)


def preset_referencing_scripts() -> set[str]:
    """**凡引用 preset 名的引擎脚本**(相对路径)—— 死引用守卫的扫描面。

    ⚠️ 附一百零八:此前那份扫描面是**按文件名**划的(`wf_*` / `grid*` / `sweep*` + 显式 4 个),
    于是 **`uptrend_pullback/bt_compare_presets.py` 与 `run_sizing_comparison.py` 从来不在视野里**
    —— 而两者都引用了一个**已不存在的 preset**,守卫却报"干净"。
    (这与 附八十五/八十六 同族:**扫描面 ≠ 实际集合**;那两次在 DSR 守卫上,这次在 preset 守卫上。)
    故这里改成**按内容推导**:凡出现 `PRESETS["…"]` / `get_preset("…")` / `run_one("…")`
    的引擎脚本都进扫描面 —— 名字可以随便改,判据不再依赖它。

    ⚠️ 附一百零八(第二次):**这一版内容推导自己也不全** —— 只认那三种**调用式**,
    而实测有 **11 个**文件是走模块级**赋值式**(`PRESET = "v35_agg_pctchg_04_09"`)把名字写进去的。
    其中 **2 个**(`chase_up/render_v3_trades_html.py`、`short_reversal/lookahead_trade_trace.py`)
    **既不在旧的文件名面内、也不在内容面内** —— 两个面都漏。
    (实测这两个名字**都还活着**,所以没爆出新债务;但若其中哪个被删,守卫会照样报"干净"。)
    故判据并上 `_ASSIGN`,并由 `test_preset_scan_surface_is_the_whole_set` 做集合对账。
    """
    import re as _re

    out: set[str] = set()
    for p in sorted(REPO_ROOT.rglob("*.py")):
        if "__pycache__" in p.parts or "tests" in p.relative_to(REPO_ROOT).parts:
            continue
        if p.name == "presets.py":
            continue
        src = p.read_text(encoding="utf-8")
        if _cites_something(src):
            out.add(str(p.relative_to(REPO_ROOT)))
    return out


def research_scripts() -> set[str]:
    """**凡调用 DSR 的研究脚本**(相对路径)。三条 §5 守卫都以此为扫描面。"""
    out = {f for f in SCRIPT_EXPLICIT}
    for patterns in SCRIPT_GLOBS.values():
        for pattern in patterns:
            for raw in glob.glob(str(REPO_ROOT / pattern)):
                out.add(str(Path(raw).relative_to(REPO_ROOT)))
    return out


#: 显式把 preset 名交给回测/取 preset 的调用,以及模块级常量赋值。
# 附一百零八: 加上 `PRESETS["x"]` / `PRESETS.get("x")` —— 此前只认四个**函数调用**,
# 于是 `bt_compare_presets.py` 的 `PRESETS["v33_long_reverse_v3"]` **从来没被看见**。
_CALL = re.compile(
    r'(?:run_one|run_backtest_v3|run_backtest|get_preset)\(\s*"([^"]+)"'
    r'|PRESETS\[\s*"([^"]+)"\s*\]'
    r'|PRESETS\.get\(\s*"([^"]+)"'
)
# 附一百零八: 原来写的是 `\s*=\s*"([^"]+)"` —— 要求引号**紧跟**等号,于是
# `preset = sys.argv[1] if len(sys.argv) > 1 else "v56_mh_10"`(`wf_v56_focused.py:35`)
# 这种"带兜底字面量"的赋值整条漏掉。
#
# ⚠️ 中间试过写成 `=[^\n]*"([^"]+)"`,**那是错的**:`[^\n]*` 贪婪,会回退到行内
# **最后一个**引号(即闭引号),于是 `preset = "v35_agg_pctchg_04_09"` 捕获到的是
# 紧跟其后的**下一行整段**(实测把 6 个 wf 脚本都捕获成了 `'\n    if preset not in …'`)。
# 故改成"**先匹配整行,再从行里抽引号 token**"(见 `_ASSIGN` + `_QUOTED`)。
_ASSIGN = re.compile(r'^[ \t]*(?:PRESET|preset|TARGET_PRESET)[ \t]*=.*$', re.M)
_QUOTED = re.compile(r'"([^"\n]+)"')
#: 附一百零八 新增三式(实测存在、且可枚举,故值得认):
#: ① `add_argument("--preset", default="…")` —— 不传参时的默认 preset,删掉它脚本就跑不动。
#:    实测:`short_reversal/main.py` 的默认值就是个**死名**,裸跑 `-m short_reversal.main`
#:    即 `ValueError: Unknown preset`(脚本本身 fail-fast 了,但守卫此前看不见这一式)。
_DEFAULT = re.compile(r'add_argument\(\s*"[^"]*preset[^"]*"[^)]*default\s*=\s*"([^"]+)"')

#: ② **整行只有一个字符串字面量** —— "字面量集合"的元素(`TOP2 = ["chase_v18…", …]`、
#:    `presets = args.preset or ["v33_mainboard…", …]`)。实测这是**真引用**:
#:    `short_reversal/scan_signals.py` / `scan_signals_fast.py` 的兜底列表里两个 preset
#:    **都已经不存在**,裸跑即 `ValueError: Unknown preset` —— 旧守卫两条都看不见。
#:
#:    ⚠️ 但这一式**不能裸用**:凡"整行只有一个字符串"之处都符合它 —— SQL 续行、HTML 模板行、
#:    日志格式串、docstring 行。实测裸用:56 条命中里 **55 条是假债**。
#:    故必须再套一层名字形态(见 `_PRESET_NAME_IDIOM`)。
_BARE = re.compile(r'^[ \t]*"([^"]+)"[ \t]*,?[ \t]*$', re.M)

#: ③ preset 名的**形态** —— 从**活名字**推导,不是拍的。
#:
#: 实测:四个引擎的活 preset 名**全部**形如 `(词_)*v<数字>[字母]?(…)_…`(外加 cycle 的 `PRESET_V1`)。
#: 故意写得比今天的名字宽,免得"按今天的集合量身裁衣":
#:   · `[A-Za-z]` 覆盖 `chase_v4_atr_tp4_sl1_ABonly` 的大写;
#:   · `v\d` 的**数字**要求把 `max_volume_participation` / `validate_price_source` 这类
#:     "恰好含 v 的词"挡在外面 —— 写成 `v[A-Za-z0-9]` 时它们的 `v` 会被吞掉、误判成 preset 名。
#:
#: 代价与收益(全库实测):套上这一层后,`_BARE` 命中 **7 个不重复字面量,全部是 preset 名**
#: (5 活 2 死),**假债 0**;不套则是 55 条假债。
#:
#: 前提由 `test_every_preset_name_matches_the_idiom` 守着 —— 将来若有人把 preset 起成
#: 不合此形态的名字(例如 `momentum_hi`),那条会红,提示回来重订识别面,
#: 而不是让守卫**静默**漏掉那一族。
_PRESET_NAME_IDIOM = re.compile(
    r'^(?:PRESET_V1|(?:[A-Za-z]+_)*v\d[A-Za-z0-9]*(?:_[A-Za-z0-9]+)*)$'
)

#: **不需要**套名字形态的那几式(它们由**语法位置**定性,不会撞上普通字符串):
#: 函数调用、`--preset` 的 `default=`。
_CALL_PATTERNS = (_CALL, _DEFAULT)


def _cited_names(src: str) -> set[str]:
    """从源码里抽出**被引用的 preset 名**集合(四式并集)。

    (两处需要再套名字形态 `_PRESET_NAME_IDIOM` —— 理由见其上方注释:
      `_ASSIGN` 行里的引号 token、以及 `_BARE` 那一式的命中。)
    """
    out: set[str] = set()
    for pat in _CALL_PATTERNS:
        for m in pat.findall(src):
            out.update(g for g in (m if isinstance(m, tuple) else (m,)) if g)
    # `preset = …` 整行 → 抽出该行内所有引号 token,只留名字形态的
    for line in _ASSIGN.findall(src):
        out.update(t for t in _QUOTED.findall(line) if _PRESET_NAME_IDIOM.match(t))
    # 整行只有一个字符串字面量 → 同上
    out.update(x for x in _BARE.findall(src) if _PRESET_NAME_IDIOM.match(x))
    return out


def _cites_something(src: str) -> bool:
    """这个文件是否**引用了 preset 名**(划扫描面用,只需真/假)。"""
    if any(pat.search(src) for pat in _CALL_PATTERNS) or _ASSIGN.search(src):
        return True
    return any(_PRESET_NAME_IDIOM.match(x) for x in _BARE.findall(src))


def _preset_names(engine: str) -> set[str]:
    """某引擎的**可寻址 preset 名**集合。

    ⚠️ 附一百零八:`cycle_price_action` 的 preset 是个 **dict**(`PRESET_V1`),它的命令行
    **寻址名**是 `"v1"`(`main.py` 里 `add_argument("--preset", default="v1", choices=["v1"])`)。
    此前这里只返回 `{"PRESET_V1"} + dict 的**配置键**`,于是 `"v1"` 落进"死引用" ⇒
    **假债**(实测)。配置键不是"名字",不该进这个名字集合 —— 它们由 `_preset_names` 的
    另一用途(§5 试验数对账,见 `SWEEP_CANDIDATE_SOURCES`)按需取。
    """
    if engine == "short_reversal":
        from short_reversal.presets import PRESETS
    elif engine == "chase_up":
        from chase_up.presets import PRESETS
    elif engine == "uptrend_pullback":
        from uptrend_pullback.presets import PRESETS
    else:
        return {"PRESET_V1", "v1"}          # cycle:内部标识 + 命令行寻址名
    return set(PRESETS)


def _references() -> dict[str, set[str]]:
    """{脚本相对路径: 它引用但不存在的 preset 名集合}(只含确实失效的)。"""
    out: dict[str, set[str]] = {}
    for rel in sorted(research_scripts() | preset_referencing_scripts()):
        path = REPO_ROOT / rel
        # 附一百零八: 引擎不能只按**路径前缀**推 —— 根目录脚本(`run_sizing_comparison.py`)
        # 的 `rel.split("/")[0]` 是整个文件名 ⇒ 推不出引擎 ⇒ 此前被**静默跳过**。
        # 故再按"它 import 了哪个 engine 的 presets"推一次。
        engine = rel.split("/", 1)[0]
        if engine not in SCRIPT_GLOBS:
            src = path.read_text(encoding="utf-8")
            engine = next(
                (e for e in SCRIPT_GLOBS
                 if re.search(rf"(?:from|import)\s+{e}\.(?:presets|backtest|engine|portfolio)", src)),
                "",
            )
        known = _preset_names(engine) if engine in SCRIPT_GLOBS else set()
        if not known:
            continue
        src = path.read_text(encoding="utf-8")
        cited = _cited_names(src)
        dead = {c for c in cited if c not in known}
        if dead:
            out[rel] = dead
    return out


def _engine_of(rel: str) -> str:
    """脚本属于哪个引擎(推不出来则 `""`)。

    附一百零八: 不能只按**路径前缀**推 —— 根目录脚本(`run_sizing_comparison.py`)的
    `rel.split("/")[0]` 是整个文件名 ⇒ 推不出引擎 ⇒ 此前被**静默跳过**。
    故补一条"它 import 了哪个 engine 的 presets/backtest/engine/portfolio"。
    """
    head = rel.split("/", 1)[0]
    if head in SCRIPT_GLOBS:
        return head
    src = (REPO_ROOT / rel).read_text(encoding="utf-8")
    return next(
        (e for e in SCRIPT_GLOBS
         if re.search(rf"(?:from|import)\s+{e}\.(?:presets|backtest|engine|portfolio)", src)),
        "",
    )


def _references() -> dict[str, set[str]]:
    """{脚本相对路径: 它引用但不存在的 preset 名集合}(只含确实失效的)。"""
    out: dict[str, set[str]] = {}
    for rel in sorted(research_scripts() | preset_referencing_scripts()):
        engine = _engine_of(rel)
        if not engine:
            continue
        known = _preset_names(engine)
        dead = {c for c in _cited_names((REPO_ROOT / rel).read_text(encoding="utf-8"))
                if c not in known}
        if dead:
            out[rel] = dead
    return out


def test_no_new_dead_preset_references() -> None:
    """研究脚本不得引用已不存在的 preset —— 那会让脚本在启动即退出。

    附一百零八: 判据由"有没有**未登记的文件**"改成**逐文件集合相等** ——
    否则一个**已登记**的文件里**多出**一个死引用(例如又加了一行 `default="别的死名"`)
    也照样绿。
    """
    actual = {f: sorted(v) for f, v in _references().items()}
    registered = {f: sorted(names) for f, (names, _c) in KNOWN_DEAD_REFERENCES.items()}
    problems = [
        f"  {f}: 实际={actual.get(f, [])} 登记={registered.get(f, [])}"
        for f in sorted(set(actual) | set(registered))
        if actual.get(f, []) != registered.get(f, [])
    ]
    assert not problems, (
        "§5 VIOLATION: 死 preset 引用与登记表不一致(左=实际,右=登记):\n"
        + "\n".join(problems)
        + "\n新增失效 → 修正脚本,或(若确属历史债务)登记并说明原因;"
          "修好一个 → 必须同时从 KNOWN_DEAD_REFERENCES 删掉。"
    )


def test_registered_debt_is_still_debt() -> None:
    """登记表必须**跟着现实走**(另一方向):已修的必须从表里删掉。

    这条防的是"登记表变成永久借口":它应当只会变短。
    (方向一 —— "实际集合 == 登记集合" —— 由 `test_no_new_dead_preset_references` 负责。)
    """
    actual = _references()
    stale = []
    for f, (names, _c) in KNOWN_DEAD_REFERENCES.items():
        for name in names:
            if name not in actual.get(f, set()):
                stale.append(f"{f} -> {name}")
    assert not stale, (
        "以下登记项已不再失效(preset 已恢复或脚本已改用現存 preset)—— "
        f"请从 KNOWN_DEAD_REFERENCES 删除:{stale}"
    )


@pytest.mark.parametrize("script,entry", sorted(KNOWN_DEAD_REFERENCES.items()))
def test_each_registered_removal_commit_really_removed_it(script: str, entry: tuple) -> None:
    """**出处要用 git 史验**,不是只看登记表自己怎么写(附一百零八)。

    为什么值得:上一条批次的登记表里,每一条的"删除提交"只被**脚本自己的失败信息**提及,
    而那条测试断言的正是"信息里含**登记表写的**提交" —— 于是**登记错了也全绿**。
    本用例改成去问 git:该提交的**父版本**里有这个名字、该提交里**没有** ⇒ 就是它删的。

    (需要 git 与仓库历史;拿不到就 skip —— 同 §6"证据不在就跳过,不假装通过"。)
    """
    names, removal_commit = entry
    engine = _engine_of(script)
    assert engine, f"{script}: 推不出引擎,无法定位它的 presets.py"
    presets_path = f"{engine}/presets.py"

    def content(rev: str) -> str | None:
        proc = subprocess.run(
            ["git", "show", f"{rev}:{presets_path}"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        return proc.stdout if proc.returncode == 0 else None

    probe = subprocess.run(
        ["git", "rev-parse", "--git-dir"], capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    if probe.returncode != 0:
        pytest.skip("不在 git 仓库里,无法核对出处")
    before, after = content(f"{removal_commit}^"), content(removal_commit)
    if before is None or after is None:
        pytest.skip(f"{removal_commit} 或 {presets_path} 在本地历史里取不到(浅克隆?)")

    for name in names:
        needle = f'"{name}"'
        assert needle in before, (
            f"{script}: 登记说 `{name}` 由 {removal_commit} 删除,"
            f"但该提交的**父版本**里就没有这个名字 —— 出处记错了(或名字拼错)。"
        )
        assert needle not in after, (
            f"{script}: 登记说 `{name}` 由 {removal_commit} 删除,但该提交之后**它还在** —— "
            f"真正的删除提交在 {removal_commit} 之后。"
        )


def test_the_authored_message_set_is_a_subset_of_the_registry() -> None:
    """`SCRIPTS_WITH_AUTHORED_MESSAGE` 必须是登记表的子集(否则断言的对象不存在)。"""
    ghosts = sorted(SCRIPTS_WITH_AUTHORED_MESSAGE - set(KNOWN_DEAD_REFERENCES))
    assert not ghosts, (
        f"以下脚本被列为「失败信息由我们撰写」,却不在死引用登记表里(幽灵项):{ghosts}"
    )


def test_research_scripts_are_actually_scanned() -> None:
    """自检:扫描面不能为空 —— 否则前几条会空转通过。

    (非空转**不等于**覆盖完整:附八十六 实测过"25 个 > 20 所以通过"而实际漏了 4 个。
     覆盖完整性由 `test_research_scripts_cover_every_dsr_caller` 负责。)
    """
    total = len(research_scripts())
    assert total >= 20, f"研究脚本扫描面异常小({total} 个文件)—— 守卫可能已空转"
    # 显式名单里的每一项都必须真的进入扫描面(防止 helper 将来被改坏)
    missing = [f for f in SCRIPT_EXPLICIT if f not in research_scripts()]
    assert not missing, f"显式名单未进入扫描面:{missing}"


def test_registered_scripts_still_exist() -> None:
    """登记表引用的脚本不能凭空消失(否则登记的是幽灵)。"""
    missing = [f for f in KNOWN_DEAD_REFERENCES if not (REPO_ROOT / f).exists()]
    assert not missing, f"登记表引用了不存在的脚本:{missing}"


def test_preset_scan_surface_is_the_whole_set() -> None:
    """**集合对账**(附一百零八):扫描面必须盖住**凡引用过 preset 名的引擎脚本**。

    判据**故意换一套机制** —— 不用那四式(它们是**被验对象**),而是
    「**活着的 preset 名**有没有以任意形态的**引号字符串**出现在这个文件里」。
    这样它不关心引用写成什么样子:`PRESETS["x"]`、`get_preset("x")`、`PRESET = "x"`、
    `default="x"`、列表元素 `"x"`、乃至注释里提到 —— 只要**提了这个名字**,文件就必须进扫描面。

    (为什么值得一条:附一百零八 实测「按文件名划的扫描面」漏了 2 个文件、
     「按内容推导」的第一版又漏了另一批 —— **两个面都漏**。它们引用的名字当时还活着所以没事,
     但那是运气,不是覆盖。这一条把"扫描面自己也会缩"钉住 ——
     与 附八十六 对 DSR 面做的是同一件事,只是这次在 preset 面上。)
    """
    engines = sorted(SCRIPT_GLOBS)
    covered = preset_referencing_scripts()
    citing: set[str] = set()
    for engine in engines:
        names = _preset_names(engine)      # cycle 由 `_preset_names` 自己收成 {"PRESET_V1", "v1"}
        pat = re.compile(
            r"""["'](""" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
            + r""")["']"""
        )
        for p in sorted((REPO_ROOT / engine).rglob("*.py")):
            if p.name == "presets.py":
                continue
            if pat.search(p.read_text(encoding="utf-8")):
                citing.add(str(p.relative_to(REPO_ROOT)))

    invisible = sorted(citing - covered)
    assert not invisible, (
        "§5/§6: 以下脚本**引用了 preset 名**却不在死引用守卫的扫描面内 —— "
        "把它引用的 preset 删掉时,没有任何东西会提示:\n  "
        + "\n  ".join(invisible)
        + "\n请让 `preset_referencing_scripts()` 收录它们(或让判据覆盖这种引用形态)。"
    )
    # 非空转:对账面本身不能是空的
    assert len(citing) >= 5, f"对账面异常小({len(citing)} 个文件)—— 本条可能已空转"


def test_every_preset_name_matches_the_idiom() -> None:
    """**前提守卫**:`_PRESET_NAME_IDIOM` 是 `_BARE` 那一式的过滤器,它必须盖住**全部**活名字。

    为何要这条:`_BARE` 判据(整行只有一个字符串)若不加形态过滤,会被 SQL 续行/HTML 模板/
    日志串淹掉(实测 56 条里 55 条假债);加了过滤之后**假债为 0**,代价是
    "过滤器的形态必须真的覆盖所有 preset 名"。**这条就是那个代价的守卫** ——
    将来有人把 preset 起成 `momentum_hi` 这种名字时,这里会红,
    提示回来重订识别面,而不是让守卫**静默**看不见那一族。
    """
    offenders = []
    for engine in sorted(SCRIPT_GLOBS):
        names = _preset_names(engine)     # cycle 由 `_preset_names` 自己收成 {"PRESET_V1", "v1"}
        for n in sorted(names):
            if not _PRESET_NAME_IDIOM.match(n):
                offenders.append(f"{engine}: {n}")
    assert not offenders, (
        "以下 preset 名的形态**不被** `_PRESET_NAME_IDIOM` 认(⇒ 它们若写在字面量集合里,"
        "死引用守卫会看不见):\n  " + "\n  ".join(offenders)
        + "\n请把 `_PRESET_NAME_IDIOM` 放宽到能覆盖它(并复验假债仍为 0),或改名。"
    )


# ---------------------------------------------------------------------------
# §5: preset 的值落在自家 sweep 的默认候选里 → `n_comparisons=1` 需要证据
# ---------------------------------------------------------------------------
#: (引擎, preset 属性名, 参数键, 该引擎的 sweep 脚本, 脚本里候选列表的选项名)
SWEEP_CANDIDATE_SOURCES = [
    ("cycle_price_action", "PRESET_V1", "threshold",
     "cycle_price_action/sweep_thresholds.py", "--thresholds"),
]


def _unrecorded_trial_counts() -> dict[str, str]:
    """检出「参数值 ∈ 自家 sweep 默认候选,却声明 n_comparisons=1」的 preset。"""
    import importlib
    import re as _re

    out: dict[str, str] = {}
    for engine, preset_attr, key, script, opt in SWEEP_CANDIDATE_SOURCES:
        mod = importlib.import_module(f"{engine}.presets")
        preset = getattr(mod, preset_attr, None)
        if preset is None or preset.get("n_comparisons") != 1:
            continue
        src = (REPO_ROOT / script).read_text(encoding="utf-8")
        if f'"{opt}"' not in src:
            continue
        seg = src[src.index(f'"{opt}"'):][:400]
        m = _re.search(r'default="([^"]+)"', seg)
        if not m:
            continue
        try:
            cands = {float(x) for x in m.group(1).split(",")}
        except ValueError:
            continue
        value = preset.get(key)
        if isinstance(value, (int, float)) and float(value) in cands:
            out[f"{engine}/{preset_attr}"] = (
                f"{key}={value} 落在 {sorted(cands)} 内,但 n_comparisons=1"
            )
    return out


def test_swept_parameters_have_their_trials_accounted_or_are_registered() -> None:
    """§5 Iterative-Tuning Accounting:值若可能是 sweep 选出来的,试验数就要记。

    这条惩罚的是**举证责任倒置**:preset 声称"无 sweep",而自家 shipped 的 sweep
    脚本默认候选里就有这个值 —— 声称需要证据,不是默认成立。
    """
    actual = _unrecorded_trial_counts()
    new = {k: v for k, v in actual.items() if k not in KNOWN_UNRECORDED_TRIAL_COUNTS}
    assert not new, (
        "§5 VIOLATION: 以下 preset 的参数值落在自家 sweep 的默认候选内,却声明 "
        "n_comparisons=1(即『未做过 sweep』):\n  "
        + "\n  ".join(f"{k}: {v}" for k, v in new.items())
        + "\n请提供迭代记录据实填写 n_comparisons,或登记到 "
        "KNOWN_UNRECORDED_TRIAL_COUNTS 并说明为何无从得知。"
    )


def test_registered_unrecorded_trial_counts_are_still_unresolved() -> None:
    """登记表必须跟着现实走:一旦迭代记录补齐(或数值改了),就要从表里删掉。"""
    actual = _unrecorded_trial_counts()
    stale = [k for k in KNOWN_UNRECORDED_TRIAL_COUNTS if k not in actual]
    assert not stale, (
        f"以下登记项已不再是问题(n_comparisons 已补或值已改)—— 请从登记表删除:{stale}"
    )


@pytest.mark.parametrize("script,entry", sorted(KNOWN_DEAD_REFERENCES.items()))
def test_such_a_script_fails_loudly_rather_than_silently(script: str, entry: tuple) -> None:
    """这些脚本虽然失效,但必须**响亮地**失败(而不是跑出个空结果)。

    ⚠️ 附一百零八:判据从"源码里有没有 `SystemExit` 字样"改成
    **"这个名字是否走了一条会校验它的解析路径"** —— 后者才是"响亮"的**机制**:
      · `get_preset("死名")` / `run_backtest_v3("死名")` → `ValueError: Unknown preset: … Available: […]`
        (实测:信息里连全部可用名都列出来了);
      · 或脚本自己对 `PRESETS` 做成员检查后 `SystemExit`。
    旧判据用字样当代理:它**过宽**(任何 `raise SystemExit(main())` 都能满足,哪怕死名是被静默忽略的),
    而 `uptrend_pullback/render_trades_html.py` 这种**没有** `SystemExit` 字样的又会被**误判为红**
    —— 而它其实是响亮的(`render_trades_html.py:1210` 调 `get_preset`)。
    """
    src = (REPO_ROOT / script).read_text(encoding="utf-8")
    resolves = (
        "get_preset(" in src
        or "run_backtest_v3(" in src
        or re.search(r"not in\s+(?:_p\.)?PRESETS", src)
    )
    assert resolves, (
        f"{script} 引用失效 preset,却看不到任何**会校验它**的解析路径 —— "
        "静默跳过会让「脚本没跑」看起来像「脚本跑了且没结论」。"
    )


@pytest.mark.parametrize(
    "script,entry", sorted(
        (k, v) for k, v in KNOWN_DEAD_REFERENCES.items()
        if k in SCRIPTS_WITH_AUTHORED_MESSAGE
    )
)
def test_such_a_script_reports_where_its_preset_went(script: str, entry: tuple) -> None:
    """**运行**脚本,断言失败**信息**里带着由来(裁剪提交 + 登记位置)。

    注意这里是**执行**而不是查源码:第一版我写的是
    `assert PRUNED_IN_COMMIT in src` —— 而该字符串在文件里还出现在**注释**中,
    于是把失败信息里的提交号删掉,测试**仍然通过**(一条空转守卫)。
    只有真正跑一遍、只看它吐出来的那句话,才验得了"读者看得到"这件事。

    ⚠️ 附一百零八:参数化只覆盖 `SCRIPTS_WITH_AUTHORED_MESSAGE` ——
    即"失败信息由我们撰写"的那些。另外四条(活工具)的失败来自库里的 `ValueError`,
    文本不归我们写,而且**跑起来会真的执行回测/写报表**,不该在这条里跑。
    """
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / script)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    msg = (proc.stdout or "") + (proc.stderr or "")

    assert proc.returncode != 0, f"{script} 未以非零码退出(应 fail-fast)"
    # ⚠️ 附一百零八: 断言**该 preset 自己的**删除提交,而不是一个写死的 `4b7eab0` ——
    # 实测三个被删的 preset 来自**三个不同提交**(4b7eab0 / e3cd4f9 / 03cb590),
    # 写死一个的话,另外两条的"出处"就永远对不上(而它们本来是对的)。
    _names, removal_commit = entry
    assert removal_commit in msg, (
        f"{script} 的**失败信息**未给出裁剪提交({removal_commit})—— "
        "读者无法判断这是「被删除」还是「被改名后忘了更新」。\n"
        f"实际输出: {msg.strip()[:200]}"
    )
    assert "KNOWN_DEAD_REFERENCES" in msg, (
        f"{script} 的失败信息未指向登记表 —— 债务应有一个可查的归属处。"
    )


# ---------------------------------------------------------------------------
# §5: DSR 的输入必须是**年化 Sharpe**,不能是收益率
# ---------------------------------------------------------------------------
def test_no_script_feeds_a_return_percentage_as_observed_sharpe() -> None:
    """§5: `observed_sharpe` 的单位契约是**年化 Sharpe**。

    `chase_up/wf_sweep_all.py` 原先把 `median_return_pct / 100`(窗口中位**总收益**)
    当成 Sharpe 传进 DSR。后果不是数值误差而是**结论错误**:收益率(0.1~1)比典型
    Sharpe 量级低一到两个数量级,实测同一批数字下
        12% 当 Sharpe=0.12 → DSR=0.034, p=0.966("毫无优势")
        真 Sharpe=1.20    → DSR=0.228, p=0.772
    也就是说,它会把**有边际优势**的结论稳定地印成"无优势",而它照样被当作显著性
    结果打印出来。

    检查方式:对每个调用 DSR 的研究脚本,取其调用点前 20 行的**非注释**代码,
    断言其中不出现 `return_pct` 之类的收益率来源。
    """
    offenders = []
    for rel in sorted(research_scripts()):
        path = REPO_ROOT / rel
        if True:
                lines = path.read_text(encoding="utf-8").splitlines()
                for i, line in enumerate(lines):
                    if "deflated_sharpe_ratio(" not in line:
                        continue
                    window = [
                        l for l in lines[max(0, i - 20): i]
                        if not l.strip().startswith("#")
                    ]
                    if any("return_pct" in l for l in window):
                        offenders.append(
                            f"{path.relative_to(REPO_ROOT)}:{i + 1}"
                        )
    assert not offenders, (
        "§5 VIOLATION: 以下调用点疑似把**收益率**当作 `observed_sharpe` 传入 DSR"
        f"(DSR 契约要求年化 Sharpe):{offenders}"
    )


# ---------------------------------------------------------------------------
# §5: `max` 取了几项,n_trials 就必须数几项
# ---------------------------------------------------------------------------
def test_dsr_max_and_n_trials_describe_the_same_collection() -> None:
    """§5: **max 取 N 项就必须按 N 折减**。

    DSR 的契约(docstring):`n_trials` 是 "selecting the best Sharpe from **k
    trials**" 里的 k。所以「对多少个候选取 max」与「按多少折减」必须同一。

    已修的两种不匹配:
      · 14 个 WF 脚本:`observed = max(sharpes)`(**窗口**上的最大)而
        `n_trials = n_comparisons`(**配置**数)→ 窗口那层没被折减;
      · `cycle_price_action/sweep_thresholds.py`:`observed = max(all_sharpes)`
        (阈值 × 窗口展平后的每一格)而 `n_trials = len(thresholds)` → 按 T 折减、
        却取了 T×W 项里的最大。

    正确的是 `uptrend_pullback/sweep_v33_long*.py` 那种:`max(all_sharpes)` 配
    `n_trials=len(all_sharpes)` —— 取 N 项、折减 N 项 ✓。故本守卫**只**惩罚
    "展平网格上取 max,却按其中一维的个数折减"这一种组合。
    """
    offenders = []
    for rel in sorted(research_scripts()):
        path = REPO_ROOT / rel
        if True:
                src = path.read_text(encoding="utf-8")
                code = "\n".join(
                    l for l in src.splitlines() if not l.strip().startswith("#")
                )
                if "deflated_sharpe_ratio(" not in code:
                    continue
                flattened_max = "max(all_sharpes)" in code
                # 按"其中一维"折减:n_trials 取自 thresholds/configs 这类单维集合
                one_dim_trials = (
                    "n_trials=len(thresholds)" in code
                    or "n_trials=len(configs)" in code
                )
                if flattened_max and one_dim_trials:
                    offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "§5 VIOLATION: 以下脚本在**展平网格**上取 max,却只按其中一维折减 —— "
        f"max 取 N 项、折减 T 项,窗口那一层选择没被计入:{offenders}"
    )


#: WF 族:分子取**跨窗口均值**(附十三 定的口径),`n_trials` 取配置数。
#: **显式列出**而不是按文件名前缀 glob —— `walkforward.py` 是 `wa` 开头,前缀 glob
#: 匹配不到它,而它恰恰就是 附十三 漏掉的那一个(附八十五)。
_WF_FAMILY = [
    "short_reversal/walkforward.py",
    *[f"short_reversal/wf_v{v}_focused.py" for v in
      (34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 56)],
]

#: 逐配置网格:分子分母都取自**同一批逐配置**的 Sharpe ⇒ 本来就是同源,`max` 正确。
_PER_CONFIG_GRID = ["short_reversal/grid_runner.py"]


def test_wf_family_no_longer_selects_the_best_window() -> None:
    """**WALK-FORWARD 族**不得再用 `max(sharpes)`(跨窗口最大)作 DSR 输入。

    本条取代了原先按文件名前缀划名单的版本 —— 那是它漏掉 `walkforward.py` 的**原因**:
    原 glob 是 `short_reversal/wf_v*_focused.py`,而 `walkforward.py` 是 `wa` 开头,
    **匹配不到**。于是 附十三(`5a413d8`)的修复漏了它,而这条守卫**也永远看不见它**
    —— 修复与守卫用同一份不完整的名单(附八十五)。

    现改为**显式名单 + 元断言**:凡 `short_reversal/` 下调用 `deflated_sharpe_ratio`
    的脚本,必须落在 `_WF_FAMILY`(分子取跨窗口均值)或 `_PER_CONFIG_GRID`
    (分子分母都是**逐配置**,本来就同源)之一;新脚本漏在两边之外即失败
    —— 名单不可能再次悄悄变短。

    按**去注释后**的代码判断 —— 修复说明里引用旧语句是正常的,不应被当成回归。
    """
    for rel in _WF_FAMILY:
        code = "\n".join(
            l for l in (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
            if not l.strip().startswith("#")
        )
        assert "observed = max(sharpes)" not in code, (
            f"§5 VIOLATION: {rel} 又用「最好的那个窗口」当 DSR 输入 —— "
            "窗口那层选择不会被任何折减覆盖。"
        )


def test_the_wf_family_list_is_the_whole_family() -> None:
    """**元断言**:名单必须等于实际集合(附十三 立的规矩)。

    没有这条,上面那条守卫的强度就取决于名单有没有漏人 —— 而它已经漏过一次。
    """
    callers = {
        str(p.relative_to(REPO_ROOT))
        for p in sorted((REPO_ROOT / "short_reversal").glob("*.py"))
        if "deflated_sharpe_ratio" in p.read_text(encoding="utf-8")
    }
    known = set(_WF_FAMILY) | set(_PER_CONFIG_GRID)
    assert callers == known, (
        "§5: `short_reversal/` 下调用 DSR 的脚本与登记名单不一致 —— "
        f"名单外新增:{sorted(callers - known)};名单里已不存在:{sorted(known - callers)}。"
        "新增脚本必须显式归入 WF 族(分子取跨窗口均值)或逐配置网格(分子分母同源)。"
    )


def test_walkforward_feeds_the_cross_window_mean_to_dsr(monkeypatch, tmp_path) -> None:
    """**数值验证**(不只判源码文本):DSR 收到的是**跨窗口均值**,不是最大那个窗口。

    起因:`walkforward.py` 此前传 `max(sharpes)` —— 而它的 `sharpes` 是同一个 preset 跨
    **窗口**的 Sharpe,`n_trials` 却是**配置**数 ⇒ 窗口那层没被折减。附十三 定的口径是
    "分子取跨窗口均值",本条把口径钉在**行为**上:桩成 4 个窗口的 Sharpe 为
    `[0.4, 1.9, 0.7, 0.6]`,断言 DSR 收到 **0.9**(均值)而不是 **1.9**(最大窗口)。
    """
    import importlib
    import sys

    import pytest

    mod = importlib.import_module("short_reversal.walkforward")
    per_window = [0.4, 1.9, 0.7, 0.6]          # 均值 0.9,最大 1.9
    seen = {"n": 0}

    def fake_run_backtest(preset, start, end, db_path, **kw):
        s = per_window[seen["n"]]
        seen["n"] += 1
        return {
            "preset": preset, "start": start, "end": end,
            "trades_count": 5, "win_rate": 0.5, "total_yield": 0.01, "cagr": 0.1,
            "sharpe": s, "max_dd": 0.05, "avg_pnl": 0.01, "avg_hold_days": 3.0,
            "tp_count": 2, "sl_count": 2, "time_count": 1,
            "final_capital": 1_000_000.0, "n_trading_days": 42,
        }

    monkeypatch.setattr(mod, "run_backtest_v3", fake_run_backtest)

    captured: dict[str, float] = {}
    real_dsr = mod.deflated_sharpe_ratio

    def spy(observed_sharpe, n_trials, **kw):
        captured["observed"] = observed_sharpe
        captured["n_trials"] = n_trials
        return real_dsr(observed_sharpe, n_trials, **kw)

    monkeypatch.setattr(mod, "deflated_sharpe_ratio", spy)
    monkeypatch.setattr(
        sys, "argv",
        ["walkforward", "--preset", "v50_slope",
         "--start", "2026-01-01", "--end", "2026-09-01",
         "--window-months", "2", "--step-months", "2",
         "--db-path", str(tmp_path)],
    )
    mod.main()

    assert seen["n"] >= 2, f"夹具失效:只跑了 {seen['n']} 个窗口"
    assert "observed" in captured, "夹具失效:DSR 根本没被调用"
    assert captured["observed"] != pytest.approx(1.9), (
        "§5 VIOLATION: DSR 收到的是**最好的那个窗口**(1.9)—— 那是 附十三 之前的口径,"
        "窗口那一层选择不会被任何折减覆盖。"
    )
    expected_mean = sum(per_window[:seen["n"]]) / seen["n"]
    assert captured["observed"] == pytest.approx(expected_mean), (
        f"DSR 应收到跨窗口均值 {expected_mean},实际 {captured['observed']}"
    )


def test_research_scripts_cover_every_dsr_caller() -> None:
    """**集合对账**(附八十六):扫描面必须盖住**凡调用 `deflated_sharpe_ratio` 的引擎脚本**。

    上面三条 §5 守卫(收益率当 Sharpe / max 与 n_trials 不匹配 / 引用已死 preset)都以
    `research_scripts()` 为扫描面。实测它此前漏了 **4 个**:`short_reversal/walkforward.py`、
    `uptrend_pullback/iter_reverse.py`、`cycle_price_action/walkforward.py`、
    `cycle_price_action/main.py` —— 它们对这四条守卫**完全不可见**。

    这与 附八十五 同一个根:**按文件名前缀划的族,漏掉了不按前缀命名的成员**。
    区别只是"漏在哪一层":那里漏在守卫里,这里漏在**四条守卫共用的扫描面**里 ——
    一处漏,四处瞎。
    """
    callers: set[str] = set()
    for engine in SCRIPT_GLOBS:
        for p in sorted((REPO_ROOT / engine).glob("*.py")):
            if "deflated_sharpe_ratio" in p.read_text(encoding="utf-8"):
                callers.add(str(p.relative_to(REPO_ROOT)))

    covered = research_scripts()
    invisible = sorted(callers - covered)
    assert not invisible, (
        "§5: 以下脚本调用 DSR 却**不在扫描面内** —— 上面几条守卫都看不见它们:\n  "
        + "\n  ".join(invisible)
        + "\n把它们加进 `SCRIPT_EXPLICIT`(或让前缀 glob 覆盖到)。"
    )


def test_the_explicit_scan_list_is_real_and_load_bearing() -> None:
    """显式名单的每一项都必须:①文件存在 ②确实调用 DSR(否则它是虚胖的白名单)。"""
    bad = []
    for rel in SCRIPT_EXPLICIT:
        p = REPO_ROOT / rel
        if not p.exists():
            bad.append(f"{rel}: 文件不存在")
        elif "deflated_sharpe_ratio" not in p.read_text(encoding="utf-8"):
            bad.append(f"{rel}: 并没有调用 DSR")
    assert not bad, "§5: 显式扫描名单有问题(幽灵项或虚胖项):\n  " + "\n  ".join(bad)
