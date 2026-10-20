"""§5 DSR 输入量纲守卫（审计 P3，2026-10-15）。

DSR 的收缩量取决于「检验了多少个假设」(`n_trials` = **试过的配置数**),而不是
「评估了多少个窗口」。审计发现 walk-forward 家族把窗口数当配置数传进去:

    n_trials=len(sharpes)      # sharpes 是逐个 **窗口** 的 Sharpe

后果:DSR **低估收缩、高估显著性** —— 越是被反复评估的窗口序列,越显得"显著"。
最自证的证据是 `short_reversal/walkforward.py`:它传 `n_trials=len(sharpes)`,
而同一行的输出标签写着 `n_windows={len(sharpes)}` —— 参数与标签自相矛盾。

仓库本来就记录了正确的量:preset 的 `n_comparisons` 字段(§5 Iterative-Tuning
Accounting),但该字段此前**被声明却无消费者**。现在 walk-forward 家族改用它,
`n_returns` 亦改为窗口的真实交易日数(6 个月 ≈ 126),而非硬编码 252(全年)。

本文件锁定:
  1. 所有 preset 都声明正的 `n_comparisons`(该字段有消费者才有意义)。
  2. walk-forward 家族必须用 `n_comparisons`,不得再传窗口数。
  3. 窗口交易日数常量为 126(6 个月),不是 252 —— 防止悄悄退回全年口径。
  4. `n_returns` 不得在 walk-forward 家族里硬编码 252。

注:网格类脚本(`uptrend_pullback/sweep_v33_long*.py`、`chase_up/sweep*.py`、
`short_reversal/grid_runner.py`、`cycle_price_action/sweep_thresholds.py`)的
`sharpes` **本就是逐配置**的,故它们传配置数是对的 —— 不在本文件的强制范围内,
逐处读码确认过。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WF_FAMILY = sorted((REPO_ROOT / "short_reversal").glob("wf_v*_focused.py")) + [
    REPO_ROOT / "short_reversal" / "walkforward.py",
]


def _preset_registries() -> list[tuple[str, dict]]:
    out = []
    for name, mod_name in (("chase_up", "chase_up.presets"),
                           ("uptrend_pullback", "uptrend_pullback.presets"),
                           ("short_reversal", "short_reversal.presets")):
        mod = __import__(mod_name, fromlist=["*"])
        out.append((name, mod.PRESETS))
    return out


def test_every_preset_declares_positive_n_comparisons() -> None:
    """§5 Iterative-Tuning Accounting:累计试验数必须被记录,且是正整数。"""
    total = 0
    for engine, reg in _preset_registries():
        bad = [k for k, v in reg.items()
               if not isinstance(v.get("n_comparisons"), int) or v["n_comparisons"] < 1]
        assert not bad, (
            f"§5 VIOLATION: {engine} 的 preset 缺少/非法 n_comparisons: "
            f"{bad[:5]}{'...' if len(bad) > 5 else ''} (共 {len(bad)} 个)"
        )
        total += len(reg)
    assert total >= 100, f"preset 总数异常({total})"


def _really_consumes_n_comparisons(src: str) -> bool:
    """**AST 级**:`deflated_sharpe_ratio(...)` 必须真的收到 `n_comparisons` 的**取值**。

    接受**两种形态**(仓库里两种都在用):
      ① 内联:`n_trials=int(_cfg["n_comparisons"])`;
      ② 经局部变量:`n_trials = int(_cfg["n_comparisons"])` … `deflated_sharpe_ratio(n_trials=n_trials)`
         —— `wf_v56_focused.py` 就是这一种(它的注释还记着"内联写法会让摘要打印一个未绑定的名字")。

    ⚠️ 这条判据我写**四版**才落地,前三次都栽在"判据认的东西比要保的性质弱"上,逐条留证:
      1. `"n_comparisons" in src`(**文本匹配**)⇒ 读取换成常数、只在**打印串**留名 ⇒ **绿**;
      2. AST 但"任何表达式里取过值都算" ⇒ 注入版里 **`print` 的 f-string 内嵌同一个下标** ⇒ **绿**;
      3. 收窄到"某次调用的实参" ⇒ 仍 **绿** —— **`print(...)` 本身也是调用**;
      4. 指名到 DSR 调用的实参 ⇒ **对 `wf_v56` 误报**(它走局部变量)⇒ 补上形态②才两全。
      ⇒ 教训(本会话第 N 次,但这次连错三次):**判据的"单位"要正好等于要保的性质**;
        "出现过" ⊋ "某次调用用了它" ⊋ "DSR 那次调用用了它"。每一次收窄都要拿**真实文件**复验,
        否则会在"终于有牙"和"误伤合法写法"之间反复横跳。
    """
    tree = ast.parse(src)
    read = re.compile(r"""\[\s*["']n_comparisons["']\s*\]|\.get\(\s*["']n_comparisons["']""")

    # 形态②:先收集"被赋值为 n_comparisons 取值的局部变量名"
    carriers: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and read.search(ast.unparse(node.value)):
            carriers |= {t.id for t in node.targets if isinstance(t, ast.Name)}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
        if "deflated" not in name.lower() and "dsr" not in name.lower():
            continue
        exprs = [ast.unparse(a) for a in node.args]
        exprs += [ast.unparse(k.value) for k in node.keywords if k.arg is not None]
        for e in exprs:
            if read.search(e) or (e.strip() in carriers):
                return True
    return False


def test_n_comparisons_has_a_consumer() -> None:
    """该字段必须真的被 DSR 调用点**取值消费**(否则只是装饰,§6 意义上无意义)。"""
    consumers = [p for p in WF_FAMILY if _really_consumes_n_comparisons(p.read_text(encoding="utf-8"))]
    assert len(consumers) == len(WF_FAMILY), (
        "§5 VIOLATION: 以下 walk-forward 脚本未**取值**消费 n_comparisons"
        "(只是提到它不算 —— 见 `_really_consumes_n_comparisons` 的注释): "
        f"{[p.name for p in WF_FAMILY if p not in consumers]}"
    )


@pytest.mark.parametrize("path", WF_FAMILY, ids=lambda p: p.name)
def test_walkforward_uses_configuration_count_not_window_count(path: Path) -> None:
    src = path.read_text(encoding="utf-8")
    assert "n_comparisons" in src, (
        f"§5 VIOLATION: {path.name} 未用配置数作 n_trials"
    )
    for bad in ("n_trials=len(sharpes)", "n_trials=len(all_sharpes)"):
        assert bad not in src, (
            f"§5 VIOLATION: {path.name} 仍传窗口数作 n_trials(`{bad}`)—— "
            "会把「评估了多少窗口」当成「检验了多少假设」,低估收缩"
        )


@pytest.mark.parametrize("path", WF_FAMILY, ids=lambda p: p.name)
def test_walkforward_observation_count_comes_from_the_run(path: Path) -> None:
    """§5: 观测数 T 必须由**本次运行**算出 —— 既不得是字面量,也不得是模块级常量。

    附六十:本用例原来的断言是

        assert re.search(r"^WINDOW_TRADING_DAYS = 126\b", src, re.M)

    —— 判据是"**必须存在**那个常数",而不是"不许把 T 写死"。它把当时那版实现的
    形状钉成了要求,于是:一边**放过** 16 个「T 与窗口长度不符」的脚本(它们都有那个
    常数:窗口默认 2 个月 ≈42 天,常数却是 126,DSR 因而系统性**偏乐观**),
    一边让"把 T 改成来自本次运行"的修复**变红**。

    这是本审计反复记录的那一类守卫("断言的是当时实现的形状"),只不过这一次它
    站在**缺陷那一侧**:它不是没拦住,而是**在要求缺陷存在**。
    现按**性质**断言:没有该常量、没有字面量 T、且确实消费了来自运行的 `n_trading_days`。
    """
    src = path.read_text(encoding="utf-8")
    assert not re.search(r"^WINDOW_TRADING_DAYS\s*[:=]", src, re.M), (
        f"§5 VIOLATION: {path.name} 仍有 WINDOW_TRADING_DAYS 常量 —— "
        "它与 CLI 的窗口长度无关,T 会与实际观测数不符"
    )
    for bad in ("n_returns=252", "n_returns=365", "n_returns=126"):
        assert bad not in src, f"§5 VIOLATION: {path.name} 仍硬编码 {bad}"
    # (c) 必须**真的**从 metrics 里读 T —— 用 AST 判,不用词。
    # 我第一次写的是 `assert "n_trading_days" in src`,而我刚插入的**注释**里就
    # 正好提到这个词 ⇒ 把消费那一行整个删掉,断言**仍然通过**(实测)。
    # 这就是本审计反复记录的"判词不判行为";不能自己再犯一次。
    import ast as _ast

    tree = _ast.parse(src)
    reads = [
        n for n in _ast.walk(tree)
        if isinstance(n, _ast.Subscript)
        and isinstance(n.slice, _ast.Constant)
        and n.slice.value == "n_trading_days"
    ]
    assert reads, (
        f"§5 VIOLATION: {path.name} 没有**读取**来自运行的观测数"
        "(应消费引擎发布的 metrics['n_trading_days'])"
    )


# ---------------------------------------------------------------------------
# §5 (附八十九): 声明上界 vs 自家 shipped 的 sweep 枚举数
# ---------------------------------------------------------------------------
#: 每个引擎**已 shipped 的最大一次 sweep** 枚举多少个配置。
#:
#: **这一列是"量出来的",不是推出来的** —— 各自注明来源,并逐处核对过脚本的**调用形态**
#: (同样的字典形状,笛卡尔积与逐轴扫描差一个数量级)。核错过两次:
#:   ① 把 uptrend 的具名子网格相乘 → 2.35e9(荒谬值当场露馅);
#:   ② 把单个扁平网格当成逐轴 → v5 算成 15(真值 180)。
#: 最终数字与**实跑打印的 combo 数逐位吻合**(106/246/281/436/180/25;grid_runner 27)。
SWEEP_ENUMERATION: dict[str, tuple[int, str]] = {
    "chase_up": (18, "sweep.py:--tp-mults 3 × --sl-mults 2 × --max-holds 3"
                     "(嵌套 for ⇒ 笛卡尔积;实跑 2×2×1=4 印证)"),
    "uptrend_pullback": (436, "sweep_v33_long_v4.py:3 个具名子网格各自乘积再求和"
                              "(106/246/281/436 与实跑打印逐位吻合)"),
    "short_reversal": (14, "grid_runner.py:**逐轴**扫描 ⇒ 4+3+3+3=13 与 4+3+4+3=14"
                           "(实跑合计 27 个配置)"),
    "cycle_price_action": (3, "sweep_thresholds.py:--thresholds 3 个候选"),
}

#: **登记在案的缺口**:该引擎所有 preset 的 `n_comparisons` 上界 **小于** 它自己 shipped 的
#: sweep 枚举数 ⇒ 那些 sweep 若曾参与选参,声明值就是**少计**的。
#:
#: 为什么要登记而不是直接改:据实填写需要**迭代记录**(哪些 sweep 真的跑过、跑了几次),
#: 那是使用者手上的事实;凭空填一个"够大"的数就是**精确的伪装**(附十三 已立此规矩)。
SWEEP_ENUMERATES_MORE_THAN_DECLARED: dict[str, str] = {
    "chase_up": "全部 22 个 preset 都声明 n_comparisons=10,而 sweep.py 枚举 **18** 个配置",
    "uptrend_pullback": "3 个 preset 声明 19/100/121,而 sweep_v33_long_v4.py 枚举 **436** 个",
    "cycle_price_action": "PRESET_V1 声明 1,而 sweep_thresholds.py 枚举 **3** 个"
                          "(已由 KNOWN_UNRECORDED_TRIAL_COUNTS 另记一条)",
    # short_reversal **不在**此列:它 75 个 preset 声明的上界是 45,而 grid_runner 最多枚举 14
    # ⇒ 上界 ≥ 枚举数,这一条对它**不成立**。如实留空,不为了凑整齐而把 4 个引擎都写上。
}


def _declared_trial_bounds() -> dict[str, int]:
    """每个引擎**所有 preset** 声明的 `n_comparisons` 上界。"""
    return {eng: max((c.get("n_comparisons") or 0) for c in reg.values())
            for eng, reg in _preset_registries()}


def _engines_where_sweeps_enumere_more(enumeration, declared) -> set[str]:
    """`枚举数 > 声明上界` 的引擎集合(纯函数,便于种值测试)。"""
    return {eng for eng, n in enumeration.items()
            if n > declared.get(eng, 0)}


def test_presets_declaring_too_few_trials_are_registered() -> None:
    """§5 Iterative-Tuning Accounting:声明上界小于自家 sweep 枚举数的引擎必须登记。

    这条抓的是**举证责任倒置**:引擎自带了能枚举几百个配置的 sweep,而它的 preset 声明
    只试过十来个 —— "那些 sweep 没参与选参"是个**需要证据**的断言,不是默认成立。
    """
    actual = _engines_where_sweeps_enumere_more(
        {k: v[0] for k, v in SWEEP_ENUMERATION.items()}, _declared_trial_bounds()
    )
    unregistered = sorted(actual - set(SWEEP_ENUMERATES_MORE_THAN_DECLARED))
    assert not unregistered, (
        "§5 VIOLATION: 以下引擎的 preset 声明上界 < 自家 shipped 的 sweep 枚举数,却未登记:\n  "
        + "\n  ".join(f"{e}: 枚举 {SWEEP_ENUMERATION[e][0]} vs 声明 {_declared_trial_bounds()[e]}"
                      for e in unregistered)
        + "\n请提供迭代记录据实填写 n_comparisons,或登记到 "
          "SWEEP_ENUMERATES_MORE_THAN_DECLARED 并写明为何无从得知。"
    )


def test_the_trial_bound_registry_is_not_stale() -> None:
    """登记表必须跟着现实走:声明数被改大(或 sweep 被删)之后,条目要删掉。

    (与 `KNOWN_UNRECORDED_TRIAL_COUNTS` / `KNOWN_DEAD_REFERENCES` 同型:只应当变短。)
    """
    actual = _engines_where_sweeps_enumere_more(
        {k: v[0] for k, v in SWEEP_ENUMERATION.items()}, _declared_trial_bounds()
    )
    stale = sorted(set(SWEEP_ENUMERATES_MORE_THAN_DECLARED) - actual)
    assert not stale, (
        f"以下登记项**已不再成立**(声明上界已 ≥ 枚举数)—— 请从登记表删除:{stale}"
    )


def test_the_trial_bound_detector_has_teeth() -> None:
    """**牙齿**:种一个"枚举 999 > 声明 10"的引擎必须被认出;上界足够时不得误报。"""
    declared = {"e1": 10, "e2": 500}
    enum = {"e1": 999, "e2": 400}                    # 已解包成 int(见调用点的 v[0])
    assert _engines_where_sweeps_enumere_more(enum, declared) == {"e1"}
    # 边界:相等不算(声明正好覆盖枚举)
    assert _engines_where_sweeps_enumere_more({"e2": 500}, {"e2": 500}) == set()
    # 未登记的引擎不在 declared 里 ⇒ 视作上界 0 ⇒ 也算缺口(不能因缺键而漏)
    assert _engines_where_sweeps_enumere_more({"e3": 1}, declared) == {"e3"}
