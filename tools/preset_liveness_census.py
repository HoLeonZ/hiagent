"""preset 键的**惰性普查**: 一个键在一族里到底有没有信息? (§13.145)

"惰性键"有**两种**, 判据不同, 此前本册只记了第一种:

| 种类 | 判据 | 例 |
|---|---|---|
| **① 引擎不读** | AST: 该键在引擎包里有**读点**吗 (`obj.get("KEY")` / `obj["KEY"]` / 关键字实参) | §13.128/§13.144 |
| **② 读了但永远等于默认** | **解析后**: 该键在所有 preset 里变过吗 (不写 = 取引擎默认) | 本节 |

⚠️ 第二种只有**解析**才看得见 —— 因为 preset 是**部分覆盖**:
  实测 `short_reversal` 的 43 个键里**只有 10 个出现在全部 55 个 preset 里**。
  ⇒ 两个"看起来不同"的 preset 可能**行为完全相同** (一个只是把引擎默认值又写了一遍),
    而**表面距离**会把它算成 1。**这正是 §13.128「声明 ≠ 做到」的同一形状。**

本工具做三件事:
  1. 抽引擎默认值 (AST: `cfg.get("KEY", <literal>)`);
  2. 把每个 preset **解析成行为配置** ⇒ 数**不同的配置** (暴露行为等价的 preset);
  3. 报**"写了也等于没写"的键** (所有 preset 要么不写、要么写的正是默认值)。

用法:
    python3 tools/preset_liveness_census.py --family short_reversal
    python3 tools/preset_liveness_census.py --family chase_up
    python3 tools/preset_liveness_census.py            # 四族各跑一遍
"""
from __future__ import annotations

import argparse
import ast
import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# §13.90/§13.13: 本工具 `--family all` 会把**四族的结果并排在一份输出里** ⇒
# **必须**静态导入各族自披露的 `METRICS_BASIS` 并报出来 (不走豁免)。
from chase_up.backtest import METRICS_BASIS as _BASIS_CHASE  # noqa: E402
from cycle_price_action.allocator import METRICS_BASIS as _BASIS_CYCLE  # noqa: E402
from short_reversal.engine import METRICS_BASIS as _BASIS_SHORT  # noqa: E402
from uptrend_pullback.backtest import METRICS_BASIS as _BASIS_UPTREND  # noqa: E402

_BASIS = {"chase_up": lambda: dict(_BASIS_CHASE),
          "uptrend_pullback": lambda: dict(_BASIS_UPTREND),
          "short_reversal": lambda: dict(_BASIS_SHORT),
          "cycle_price_action": lambda: dict(_BASIS_CYCLE)}

META = {"n_comparisons", "METRICS_BASIS", "_name"}


def _defaults(pkg: str) -> dict:
    """从引擎包抽 `cfg.get("KEY", <literal>)` 的默认值 (presets.py 不计)。"""
    out: dict = {}
    for p in (ROOT / pkg).rglob("*.py"):
        if p.name == "presets.py":
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "get" and len(n.args) >= 2
                    and isinstance(n.args[0], ast.Constant)
                    and isinstance(n.args[0].value, str)):
                try:
                    out.setdefault(n.args[0].value, ast.literal_eval(n.args[1]))
                except (ValueError, TypeError):
                    pass
    return out


def _presets(pkg: str) -> dict:
    if pkg == "chase_up":
        from chase_up.presets import PRESETS
        return dict(PRESETS)
    if pkg == "uptrend_pullback":
        from uptrend_pullback.presets import PRESETS
        return dict(PRESETS)
    if pkg == "short_reversal":
        from short_reversal.presets import PRESETS
        return dict(PRESETS)
    from cycle_price_action.presets import PRESET_V1
    return {"PRESET_V1": dict(PRESET_V1)}


def run(pkg: str) -> None:
    P = _presets(pkg)
    D = _defaults(pkg)
    print(f"=== {pkg}: {len(P)} 个 preset, 引擎默认值抽到 {len(D)} 个键 ===")
    if len(P) < 2:
        print("  (该族只有 1 个 preset ⇒ ②类惰性键无从谈起)"); return

    allk = sorted({k for p in P.values() for k in p} - META)
    common = set.intersection(*[set(p) for p in P.values()]) - META
    # ⚠️ 第一版漏了 `- META` ⇒ 打出「键并集 16; 出现在全部 preset 里的 17」这个
    # **自相矛盾的数字** (并集比交集还小) —— 因为它把 `_name` 算进了交集。
    # 任何一个「子集比全集大」的读数都说明判据写错了, 不是数据怪。
    print(f"  键并集 {len(allk)}; **出现在全部 preset 里的 {len(common)}** "
          f"⇒ preset 是**部分覆盖**, 不是完整配置")

    MISSING = object()
    def resolve(p):
        return json.dumps({k: p.get(k, D.get(k, "<无默认>")) for k in allk},
                          sort_keys=True, default=str)
    g = collections.defaultdict(list)
    for n, p in P.items():
        g[resolve(p)].append(n)
    print(f"  解析成**行为配置**后: **{len(g)} 个不同** "
          f"(表面 {len(P)} 个 ⇒ 有 {len(P)-len(g)} 个是行为等价的重复)")
    for _, v in [x for x in g.items() if len(x[1]) > 1]:
        print(f"    行为等价: {v}")

    noop = [k for k in allk if k in D
            and all(p.get(k, MISSING) in (MISSING, D[k]) for p in P.values())]
    print(f"  **「写了也等于没写」的键 {len(noop)} 个** (所有 preset 要么不写、要么写的正是默认值):")
    for k in noop:
        print(f"    {k:<44} 默认 {D[k]!r}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--family", default="all",
                    choices=["all", "chase_up", "uptrend_pullback",
                             "short_reversal", "cycle_price_action"])
    args = ap.parse_args()
    fams = (["chase_up", "uptrend_pullback", "short_reversal", "cycle_price_action"]
            if args.family == "all" else [args.family])
    print("=== 口径披露 (§13.13/§13.90: 四族同名**指标**定义不同, 不得跨族比较) ===")
    for f in fams:
        print(f"  {f:<22} {_BASIS[f]()}")
    print("  ⚠️ 本表并列的是**preset 键的惰性普查** (声明/读点/取值变化) —— 由源码与 preset\n"
          "     直接得出, 不经任何族的指标口径 ⇒ **可横比**; 本工具**不报**任何族的 metrics.\n")
    for f in fams:
        run(f); print()
    print("读法: ②类惰性键是**扫描白跑**的来源 —— 扫它们既得不到效应, 又会让报告看起来\n"
          "      「我动了 X 但没变」。它与 §13.128 的①类 (引擎不读) 合计, 构成本册的惰性键清单。\n"
          "⚠️ 默认值来自 AST 抽的 `cfg.get(\"KEY\", <lit>)`; 用非字面量默认值的键抽不到 ⇒ 会偏保守。")


if __name__ == "__main__":
    main()
