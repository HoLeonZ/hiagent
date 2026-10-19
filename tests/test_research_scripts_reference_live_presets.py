"""§5/§6 守卫:研究脚本引用的 preset 必须**仍然存在**。

**发现**(audit 2026-10-15):short_reversal 的 preset 列表在历史迭代中被大幅裁剪
(现在 75 个),但下游的研究脚本仍在引用被删掉的 preset 名。这些脚本在运行第一行就
`SystemExit("preset ... 不在 PRESETS")` —— 它们**跑不起来**:

  `wf_v34_focused.py` → `v34_mainboard_pctchg_tight`(v34 系列已全部不存在)
  `wf_v37_focused.py` → `v37_liq_3e7_5e8`       (v37 系列已全部不存在)
  `wf_v39_focused.py` → `v39_pctchg_04_09`      (只剩 v39_pctchg_03_10)
  `wf_v41_focused.py` → `v41_pctchg_04_10`      (v41 系列已全部不存在)

**为什么值得一条守卫**:这类失效是**静默积累**的 —— 删 preset 时不会有任何东西提示
"有 4 个脚本在引用它"。而它们正是 §5 的执行层(DSR / WFV / n_trials 都在这些脚本里),
跑不起来就等于那一段纪律**没有任何执行者**。

**如何处置这 4 个**:我没有改它们 —— 被删的 preset 没有留下可推断的重命名映射
(v34/v37/v41 系列**一个都不剩**),把名字改成某个"看起来像"的 preset 就是**编造
实验记录**。故采用"登记债务"的处置:
  · 本文件的 `KNOWN_DEAD_REFERENCES` 是**登记表**;
  · 实际集合必须**等于**登记表 —— 新增失效会失败(被抓住),修好一个而不同步删除登记项
    也会失败(防止登记表变成永久借口)。
"""
from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

#: 已知失效引用(债务登记)。修好其中一个 → 必须同时从这里删掉。
#:
#: **由来**(2026-10-15 从 git 史查清,不是猜的):这四个 preset 是在提交 `4b7eab0`
#: ("iter #2 CLAUDE.md fixes")中被**裁剪**的 —— 该提交对 `short_reversal/presets.py`
#: 减 212 行 / 增 66 行,是**删除而非重命名**。故**不存在**可安全回指的替代名:
#: 把脚本改成某个"看起来像"的 preset 就是编造实验记录(见附十三 §3)。
#:
#: 四个脚本现在**自己**把这段由来写进失败信息(跑一下就会看到裁剪提交与登记位置),
#: 免得下一个人还要重查一遍 git 史。
#: 另注:`v41_pctchg_04_10` 当初是作为**单点过拟合失败案例**引入的(见 `0a80f74`),
#: 也就是说被裁掉的那个 preset 本身就是一份负面证据 —— 这是它们值得**保留**
#: 而不是删除的原因。
PRUNED_IN_COMMIT = "4b7eab0"

KNOWN_DEAD_REFERENCES = {
    "short_reversal/wf_v34_focused.py": "v34_mainboard_pctchg_tight",
    "short_reversal/wf_v37_focused.py": "v37_liq_3e7_5e8",
    "short_reversal/wf_v39_focused.py": "v39_pctchg_04_09",
    "short_reversal/wf_v41_focused.py": "v41_pctchg_04_10",
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

#: 显式把 preset 名交给回测/取 preset 的调用,以及模块级常量赋值。
_CALL = re.compile(r'(?:run_one|run_backtest_v3|run_backtest|get_preset)\(\s*"([^"]+)"')
_ASSIGN = re.compile(r'^\s*(?:PRESET|preset|TARGET_PRESET)\s*=\s*"([^"]+)"', re.M)


def _preset_names(engine: str) -> set[str]:
    if engine == "short_reversal":
        from short_reversal.presets import PRESETS
    elif engine == "chase_up":
        from chase_up.presets import PRESETS
    elif engine == "uptrend_pullback":
        from uptrend_pullback.presets import PRESETS
    else:
        from cycle_price_action.presets import PRESET_V1
        return {"PRESET_V1", *PRESET_V1}
    return set(PRESETS)


def _references() -> dict[str, set[str]]:
    """{脚本相对路径: 它引用但不存在的 preset 名集合}(只含确实失效的)。"""
    out: dict[str, set[str]] = {}
    for engine, patterns in SCRIPT_GLOBS.items():
        known = _preset_names(engine)
        for pattern in patterns:
            for raw in sorted(glob.glob(str(REPO_ROOT / pattern))):
                path = Path(raw)
                src = path.read_text(encoding="utf-8")
                cited = set(_CALL.findall(src)) | set(_ASSIGN.findall(src))
                dead = {c for c in cited if c not in known}
                if dead:
                    out[str(path.relative_to(REPO_ROOT))] = dead
    return out


def test_no_new_dead_preset_references() -> None:
    """研究脚本不得引用已不存在的 preset —— 那会让脚本在启动即退出。"""
    actual = {f: sorted(v) for f, v in _references().items()}
    registered = {f: [n] for f, n in KNOWN_DEAD_REFERENCES.items()}
    new = {f: v for f, v in actual.items() if f not in registered}
    assert not new, (
        "§5 VIOLATION: 以下研究脚本引用了**不存在**的 preset(运行即 SystemExit):\n  "
        + "\n  ".join(f"{f} -> {v}" for f, v in new.items())
        + "\n修正脚本,或(若确属历史债务)登记到 KNOWN_DEAD_REFERENCES 并说明原因。"
    )


def test_registered_debt_is_still_debt() -> None:
    """登记表必须**跟着现实走**:修好一个却不同步删登记项 → 失败。

    这条防的是"登记表变成永久借口":它应当只会变短。
    """
    actual = _references()
    stale = []
    for f, name in KNOWN_DEAD_REFERENCES.items():
        if name not in actual.get(f, set()):
            stale.append(f"{f} -> {name}")
    assert not stale, (
        "以下登记项已不再失效(preset 已恢复或脚本已改用現存 preset)—— "
        f"请从 KNOWN_DEAD_REFERENCES 删除:{stale}"
    )


def test_research_scripts_are_actually_scanned() -> None:
    """自检:扫描面不能为空 —— 否则前两条会空转通过。"""
    total = sum(len(glob.glob(str(REPO_ROOT / p)))
                for pats in SCRIPT_GLOBS.values() for p in pats)
    assert total >= 20, f"研究脚本扫描面异常小({total} 个文件)—— 守卫可能已空转"


def test_registered_scripts_still_exist() -> None:
    """登记表引用的脚本不能凭空消失(否则登记的是幽灵)。"""
    missing = [f for f in KNOWN_DEAD_REFERENCES if not (REPO_ROOT / f).exists()]
    assert not missing, f"登记表引用了不存在的脚本:{missing}"


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


@pytest.mark.parametrize("script,expected", sorted(KNOWN_DEAD_REFERENCES.items()))
def test_such_a_script_fails_loudly_rather_than_silently(script: str, expected: str) -> None:
    """这些脚本虽然失效,但必须**响亮地**失败(而不是跑出个空结果)。

    它们已经是 `SystemExit("preset ... 不在 PRESETS")` —— 本用例把这一点钉住:
    若将来有人把它改成"找不到就跳过",失效就又会变成静默的。
    """
    src = (REPO_ROOT / script).read_text(encoding="utf-8")
    assert "不在 PRESETS" in src or "SystemExit" in src, (
        f"{script} 引用失效 preset 却不再响亮失败 —— "
        "静默跳过会让「脚本没跑」看起来像「脚本跑了且没结论」。"
    )


@pytest.mark.parametrize("script", sorted(KNOWN_DEAD_REFERENCES))
def test_such_a_script_reports_where_its_preset_went(script: str) -> None:
    """**运行**脚本,断言失败**信息**里带着由来(裁剪提交 + 登记位置)。

    注意这里是**执行**而不是查源码:第一版我写的是
    `assert PRUNED_IN_COMMIT in src` —— 而该字符串在文件里还出现在**注释**中,
    于是把失败信息里的提交号删掉,测试**仍然通过**(一条空转守卫)。
    只有真正跑一遍、只看它吐出来的那句话,才验得了"读者看得到"这件事。
    """
    import subprocess

    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / script)],
        capture_output=True, text=True, cwd=str(REPO_ROOT),
    )
    msg = (proc.stdout or "") + (proc.stderr or "")

    assert proc.returncode != 0, f"{script} 未以非零码退出(应 fail-fast)"
    assert PRUNED_IN_COMMIT in msg, (
        f"{script} 的**失败信息**未给出裁剪提交({PRUNED_IN_COMMIT})—— "
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
    for engine, patterns in SCRIPT_GLOBS.items():
        for pattern in patterns:
            for raw in sorted(glob.glob(str(REPO_ROOT / pattern))):
                path = Path(raw)
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
    for engine, patterns in SCRIPT_GLOBS.items():
        for pattern in patterns:
            for raw in sorted(glob.glob(str(REPO_ROOT / pattern))):
                path = Path(raw)
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
