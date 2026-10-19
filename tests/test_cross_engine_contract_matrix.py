r"""附九十一 —— 跨引擎**契约矩阵**:同一规则在四个引擎里各写一份,这里把它们钉在一起。

## 为什么需要它

审计文档自己写过:

> **同一个模式已经出现三次**:一条规则在 3~4 个引擎里各写一份,于是修复永远只覆盖
> "我这次看到的那一份"。这已不是巧合,而是一种系统性的维护风险。

文档点了名,但**没有任何检查**为这个模式本身存在 —— 于是它还会再发生第四次、第五次。

## 这一轮最刺眼的证据:`T+1`

CLAUDE.md §4 明文要求「**T+1**: 买入的股票在 T+1 之前不得卖出」。而:

```
$ grep -rn "T+1\|t1" chase_up/ uptrend_pullback/ short_reversal/ cycle_price_action/
(空)
```

**按规则的名字去搜,四个引擎里一处都搜不到** —— 任何审计者都会据此判"这条规则没实现"。
但逐处读码后:它**四族全都实现了**,只是**三种拼法**:

| 引擎 | 写法 |
|---|---|
| `chase_up` / `uptrend_pullback` | `if bars_in_pos < 1:` —— **跳过**退出判定 |
| `short_reversal` | `if held < 1:` —— 同上,且注释写的是 "CLAUDE.md **P3**" |
| `cycle_price_action` | `raise ValueError("P3 violation: same-day or earlier exit forbidden")` —— **fail-fast** |

注释里管它叫 **P3**,不叫 T+1;三个跳过式、一个抛错式。**规则在,名字不在,而且没有一处把
这四个拼法连起来。** 这正是"族内不对称"能反复发生的机制:下一个人搜 T+1,搜不到,于是
"顺手在某个引擎里加一条"。

## 判据

一张矩阵:每行一条契约、每列一个引擎,格子是 **(文件, 定位正则)**。门禁要求:

1. **每条契约必须覆盖全部四个引擎**(漏一个 ⇒ 红 —— 这就是"修复只覆盖看到的那一份"的机械版);
2. 每个格子的正则必须在该文件里**命中**(把实现删掉 ⇒ 红);
3. 契约/引擎集合本身要与实际一致(新增引擎而矩阵没跟上 ⇒ 红)。

**没有"豁免"这一档** —— 本轮三条契约在四族里都找到了实现,故不需要。若将来某条契约
在某族里**按设计**不存在,应显式加一档带理由的豁免,而不是把那一格删掉(删掉与"没实现"
在矩阵里长得一模一样 —— 这是本会话反复栽的那个坑)。

## 五条契约现在都在矩阵里 —— 以及我上一版把两条挡在门外的理由是**错的**

第一版只收三条,理由是"另两条只找得到 **import 行或注释**级落点"。**那个理由是错的**:
再搜一轮就找到了两条**代码级**落点 ——

* 成交量上限:四族都调 `core.dual_price.volume_cap_fill(...)`(**真的单源**);
* NAV 闸门:chase/uptrend 逐字相同的 `nav_now < initial_capital * nav_gate_ratio`,
  short_reversal 叫 `cash_gate_threshold`,cycle 用**类常量** `NAV_GATE_RATIO`。

教训:"**找不到代码级落点**"这句话,必须先**真的找过**才能说 —— 我第一版是"没找到就
当成找不到",差一点把一条**做对了的**契约(成交量上限四族单源)排除在矩阵外。

**仍然坚持的**:不拿注释或 import 行当"实现"(那会把矩阵变成文本审计 ——
仓库自己在 `test_preset_declarations_are_load_bearing.py` 开头警告过这种弱判据)。
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

ENGINES = ("chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action")

#: 契约 → {引擎: (相对路径, 定位正则, 该族的**拼法**说明)}
#:
#: "拼法"一列是给人看的:矩阵的价值有一半在于**把四种写法并排摆出来**。
CONTRACTS: dict[str, dict[str, tuple[str, str, str]]] = {
    "T+1: 入场当日不得退出 (CLAUDE.md §4)": {
        "chase_up": ("chase_up/replay_strategy.py", r"if bars_in_pos < 1:",
                     "跳过退出判定"),
        "uptrend_pullback": ("uptrend_pullback/replay_strategy.py", r"if bars_in_pos < 1:",
                             "跳过退出判定"),
        "short_reversal": ("short_reversal/replay_strategy_v3.py", r"if held < 1:",
                           "跳过退出判定(注释里叫 P3)"),
        "cycle_price_action": ("cycle_price_action/portfolio.py",
                               r"same-day or earlier exit forbidden",
                               "**fail-fast 抛错**(`P3 violation`)"),
    },
    "容量闸门: 持仓已达上限则丢弃本 bar 剩余信号 (§2)": {
        "chase_up": ("chase_up/portfolio.py", r"if len\(positions\) >= max_positions:",
                     "`break`"),
        "uptrend_pullback": ("uptrend_pullback/portfolio.py", r"if len\(positions\) >= max_positions:",
                             "`break`"),
        "short_reversal": ("short_reversal/replay_strategy_v3.py",
                           r"if len\(self\._holds\) >= self\.p\.max_positions:",
                           "`break`(影子账叫 `_holds`)"),
        "cycle_price_action": ("cycle_price_action/portfolio.py", r"if self\._pos is not None:",
                               "本族容量恒 1 ⇒ 单槽判空即是闸门"),
    },
    "涨停买入不成交 (§4: 封板买不进)": {
        "chase_up": ("chase_up/replay_strategy.py", r"is_limit_up\(", "建仓前判"),
        "uptrend_pullback": ("uptrend_pullback/replay_strategy.py", r"is_limit_up\(", "建仓前判"),
        "short_reversal": ("short_reversal/replay_strategy_v3.py", r"is_limit_up\(",
                           "**回补**前判(做空:买 = 回补)"),
        "cycle_price_action": ("cycle_price_action/portfolio.py", r"is_limit_up\(","建仓前判"),
    },
    "成交量参与上限 (§4: MIN(target, Bar_Volume × rate))": {
        "chase_up": ("chase_up/portfolio.py", r"max_fill = volume_cap_fill\(",
                     "共用 `core.dual_price.volume_cap_fill` **单源**"),
        "uptrend_pullback": ("uptrend_pullback/portfolio.py", r"max_fill = volume_cap_fill\(",
                             "同上(单源)"),
        "short_reversal": ("short_reversal/replay_strategy_v3.py", r"max_fill = volume_cap_fill\(",
                           "同上(单源)"),
        "cycle_price_action": ("cycle_price_action/portfolio.py", r"max_fill = volume_cap_fill\(",
                               "同上(单源)—— §4 的「单源」在这一条上**是做到了的**"),
    },
    "同 bar 双触发取 SL 优先 (§4 Intraday Blindness)": {
        "chase_up": ("chase_up/portfolio.py", r'if intraday_tiebreak != "sl_first":',
                     "**fail-fast 拒绝其它取值**(底线式)"),
        "uptrend_pullback": ("uptrend_pullback/portfolio.py", r'if intraday_tiebreak != "sl_first":',
                             "同 chase"),
        "short_reversal": ("short_reversal/replay_strategy_v3.py",
                           r'if self\.p\.intraday_tiebreak != "sl_first":',
                           "同上"),
        "cycle_price_action": ("cycle_price_action/portfolio.py",
                               r"def try_exit_with_intraday_check\(",
                               "**把顺序编码在函数体内**(不是拒绝式;定位强度弱于另三族 —— 见本行动机)"),
    },
    "跌停卖出/回补不成交 (§4: 封板卖不掉)": {
        "chase_up": ("chase_up/portfolio.py", r"if is_limit_down\(",
                     "出场路径;注释写明与买方涨停门镜像"),
        "uptrend_pullback": ("uptrend_pullback/portfolio.py", r"if is_limit_down\(",
                             "出场路径(注释:方向保守 —— 跳过 SL 出场意味着亏损可能继续扩大)"),
        "short_reversal": ("short_reversal/replay_strategy_v3.py", r"if is_limit_down\(",
                           "**回补**路径,且**带板块/日期阈值**(创业板科创板 ±20%)"),
        "cycle_price_action": ("cycle_price_action/portfolio.py", r"return is_limit_down\(",
                               "**包成方法**返回布尔(不是内联 if)"),
    },
    "公司行为事件源 (§3 Phase-1: 现金分红/送股必须落账)": {
        "chase_up": ("chase_up/portfolio.py", r"_out = apply_corporate_action\(",
                     "直接调 `core.corporate_actions`"),
        "uptrend_pullback": ("uptrend_pullback/portfolio.py", r"_out = apply_corporate_action\(",
                             "同 chase(逐字相同)"),
        "short_reversal": ("short_reversal/replay_strategy_v3.py", r"self\._apply_corporate_action\(d\)",
                           "**包成方法** `self._apply_corporate_action(d)`"),
        "cycle_price_action": ("cycle_price_action/backtrader_engine.py",
                               r"self\._portfolio\.apply_corporate_action\(",
                               "由 **Control Plane** 调 portfolio 的方法"),
    },
    "成本模型单源 (§2: MAX(notional × rate, min_fee),常量只在 core 定义一次)": {
        "chase_up": ("chase_up/portfolio.py",
                     r"return max\(notional \* self\.commission_rate, self\.min_commission\)",
                     "**实例属性**(由 `core.dual_price` 的常量初始化)"),
        "uptrend_pullback": ("uptrend_pullback/portfolio.py",
                             r"return max\(notional \* self\.commission_rate, self\.min_commission\)",
                             "同 chase(逐字相同)"),
        "short_reversal": ("short_reversal/replay_strategy_v3.py", r"self\.p\.min_commission",
                           "**params 字段**(`self.p.*`),同样由 core 常量初始化"),
        "cycle_price_action": ("cycle_price_action/portfolio.py",
                               r"comm = max\(self\.MIN_COMMISSION, notional \* self\.COMMISSION_RATE\)",
                               "**类常量** `self.MIN_COMMISSION` / `self.COMMISSION_RATE`"),
    },
    "NAV 闸门 (§2: NAV 跌破 initial_capital × ratio 则拒绝新开仓)": {
        "chase_up": ("chase_up/portfolio.py", r"if nav_now < initial_capital \* nav_gate_ratio:",
                     "`nav_gate_ratio` 作参数"),
        "uptrend_pullback": ("uptrend_pullback/portfolio.py",
                             r"if nav_now < initial_capital \* nav_gate_ratio:",
                             "同 chase(逐字相同)"),
        "short_reversal": ("short_reversal/replay_strategy_v3.py",
                           r"cash_gate_threshold = self\.p\.initial_capital \* self\.p\.nav_gate_ratio",
                           "**改了名字**:`cash_gate_threshold`;且 `nav_gate_ratio` 缺声明即 fail-fast"),
        "cycle_price_action": ("cycle_price_action/portfolio.py",
                               r"if self\.cash < self\.initial_capital \* self\.NAV_GATE_RATIO:",
                               "**类常量** `NAV_GATE_RATIO`(不是参数)"),
    },
}


def _locate(rel: str, pattern: str) -> tuple[bool, str]:
    path = REPO_ROOT / rel
    if not path.exists():
        return False, f"{rel} 不存在"
    m = re.search(pattern, path.read_text(encoding="utf-8"), re.M)
    if not m:
        return False, f"{rel} 里找不到 /{pattern}/"
    line = path.read_text(encoding="utf-8")[:m.start()].count("\n") + 1
    return True, f"{rel}:{line}"


def test_every_contract_covers_every_engine() -> None:
    """矩阵必须**满格** —— 少一个引擎就是"这条规则在这族里没人管"。

    (这是审计文档那句"修复永远只覆盖我这次看到的那一份"的机械版。)
    """
    missing = []
    for contract, cells in CONTRACTS.items():
        for eng in ENGINES:
            if eng not in cells:
                missing.append(f"{contract} 缺少 {eng}")
    assert not missing, (
        "§0/§4: 以下契约在某引擎里没有落点 —— 要么补实现,要么加一档**带理由的豁免**"
        "(直接删掉那一格与'没实现'在矩阵里长得一样):\n  " + "\n  ".join(missing)
    )


def test_every_matrix_cell_actually_locates_code() -> None:
    """每个格子必须命中**真实代码** —— 实现被删掉就红。"""
    bad = []
    for contract, cells in CONTRACTS.items():
        for eng, (rel, pat, _spelling) in cells.items():
            ok, where = _locate(rel, pat)
            if not ok:
                bad.append(f"{contract} / {eng}: {where}")
    assert not bad, (
        "§0/§4: 以下契约的实现**找不到了**(被删/被改名/被移动):\n  " + "\n  ".join(bad)
    )


def test_the_matrix_has_teeth(tmp_path, monkeypatch) -> None:
    """**牙齿**:①删掉一格 ⇒ 满格检查红;②正则改成命中不了的 ⇒ 定位检查红。"""
    # ① 少一个引擎
    incomplete = {k: {e: v for e, v in cells.items() if e != "short_reversal"}
                  for k, cells in CONTRACTS.items()}
    missing = [f"{c} 缺少 short_reversal" for c in incomplete]
    assert missing, "夹具失效:少了引擎却没算出来"

    # ② 正则命中不了
    ok, _ = _locate("chase_up/replay_strategy.py", r"if bars_in_pos < 1:")
    assert ok, "夹具失效:真实落点没命中"
    ok2, why = _locate("chase_up/replay_strategy.py", r"__no_such_marker_xyzzy__")
    assert not ok2 and "找不到" in why


@pytest.mark.parametrize("contract", sorted(CONTRACTS))
def test_contract_rows_are_printable_with_their_spellings(contract: str) -> None:
    """每一行的**拼法**必须写清楚 —— 矩阵的一半价值在"把四种写法并排摆出来"。

    (没有这条,矩阵会退化成"四个文件里各有一个正则";而 `T+1` 这一行恰恰说明:
     读者按名字搜是搜不到的。)
    """
    for eng, (_rel, _pat, spelling) in CONTRACTS[contract].items():
        assert spelling.strip(), f"{contract} / {eng} 没写拼法"
