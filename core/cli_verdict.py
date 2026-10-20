"""§0: CLI 的**结论必须落在退出码上** —— 共享约定(单一实现)。

CLAUDE.md §0(Fail-Fast / Reproducibility):本仓库的工具是**回测、报告与共享行情库
更新**的入口,它们下游就是回测本身。因此"部分失败"若以退出码 0 结束,下游会把半成品
当成品 —— 而下一轮回测随后读到不一致的输入,**同一份代码在不同时间跑出不同结果**。

本仓库实测过的同族缺陷:

  * `tools/audit_phantom.py`(chase/uptrend)在**空输入**上报告
    `phantom ratio: 0.00%`(附五十八):空域被写成了"干净";
  * `tools/update_db_direct.py` 统计并打印 `errors` 之后仍 `return 0`
    (附六十三)—— 它写的是**共享行情库**;
  * `tools/render_top5_presets_html.py` / `rerun_top_presets.py` /
    `run_all_backtests_html.py` 都是 `except Exception → print(ERROR) → return 0`。

统一口径(四个工具共用本函数):

    0 —— 全部成功;或**确实无事可做**(`attempted == 0`);
    0 —— 处理了若干项但**无一产出结果**(单独一档 `NOTHING-DONE`,措辞必须说清
         它"不等于失败,也不等于成功" —— 静默的零正是本仓库反复吃亏的地方);
    1 —— **有项目失败**:本次产出不完整,下游必须停下来看。

纯函数、零 I/O —— 便于单测:退出码的映射不需要真的去跑回测或打网络。
"""
from __future__ import annotations


def cli_verdict(
    *, failures: int, attempted: int, succeeded: int, what: str
) -> tuple[int, str]:
    """返回 `(退出码, 结论文本)`。

    参数:
        failures  —— 失败项数(异常、更新错误…);
        attempted —— 尝试处理的项数(标的 / preset / 报告…);
        succeeded —— 真正产出了结果的项数;
        what      —— 人类可读的主体名,用于结论文本。
    """
    if failures:
        return 1, (
            f"[PARTIAL] {what}: {failures}/{attempted} 项失败 —— 本次产出**不完整**,"
            f"退出码非零。下游不要把半成品当成品。"
        )
    if attempted == 0:
        return 0, (
            f"[NO-OP] {what}: 没有可处理的项目 —— 这不等于失败,也不等于成功。"
        )
    if succeeded == 0:
        return 0, (
            f"[NOTHING-DONE] {what}: 处理了 {attempted} 项但无一产出结果 —— "
            f"这不等于失败,也不等于成功(常见于时间窗口 / 目标日期选早了)。"
        )
    return 0, f"[OK] {what}: {succeeded}/{attempted} 项成功。"


__all__ = ["cli_verdict"]
