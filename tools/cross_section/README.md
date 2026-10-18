# `tools/cross_section/` —— 登记册 **§7(横截面方向)** 的复现装置

> **本目录下不写任何历史数字。** 按 CLAUDE.md §7:文档只写**怎么复现**,从不写**曾经观察到什么**。
> 要数字就跑脚本。

## 为什么会有这个目录 (2026-10-19, §13.41)

登记册 §7 是全部挖掘里**唯一的非族方向**,也是**最载重的结论之一**(样本内通过多重比较校正与成本、
样本外归零 ⇒ 该方向关闭)。但在 2026-10-19 之前:

* 它的分析**没有任何提交进仓库的脚本** —— 只存在于 `/tmp/hiagent_mining/`,一个**设计上易失**的
  位置(`/tmp` 被清、换台机器、换个 clone 就没了);
* 它的核心变量 `amt_ratio` 在仓库**任何 `.py` 文件里都不存在**;
* 登记册 §7 内部有 17 处「复现」字样,但**全部是统计意义**的(两窗口同号 / 外部队列复现 /
  端到端可复现),**没有一处是可以运行的命令**。

⇒ 也就是说: **全篇最载重的结论当时是不可复现的。** 本目录把三支权威脚本抢救进来,修补这一点。

**来源**: `/tmp/hiagent_mining/{cross_section2,cs_final,cs_holdout}.py`,逐字摘取。

## 抢救时**只动了三处**, 都为了"可复现"这一个目标

| # | 改动 | 为什么必须改 |
|---|---|---|
| 1 | `sys.path.insert(0, "/Users/holeon/code/hiagent")` → `str(Path(__file__).resolve().parents[2])` | 硬编码绝对路径在别的 clone 上直接跑不起来 |
| 2 | 外层 `SELECT` 补 `ORDER BY date, thscode` | 行序未定 ⇒ 下游 `rank(method="first")` 的**并列打破随行序变** ⇒ 逐次运行的末位不同 |
| 3 | `cross_section2.py` 的 `ntile(10) OVER (PARTITION BY date ORDER BY sig)` → `ORDER BY sig, thscode` | `ntile` 的并列打破**未定义** ⇒ 档位归属逐次变动 |

**改动 2/3 的依据是 CLAUDE.md §0 的 Reproducibility Mandate**:
> Identical inputs MUST produce byte-identical outputs.

**验证方式**: 把每个脚本**连跑三遍**,对输出做 `diff` —— 三份逐字节相同。
(改动前 `cross_section2.py` 两遍就不同,末位会变。)

## 三支脚本各复现什么

| 脚本 | 复现登记册的哪一节 |
|---|---|
| `cross_section2.py` | **§7.4 / §7.6** —— 横截面**按日聚合**的 t 统计量(样本内 `IND` / `W2`) |
| `cs_final.py` | **§7.12** —— **价格中性**构造(层内取低量能、**层间等权**)+ §4 参与上限的**容量咬合**归因 |
| `cs_holdout.py` | **§7.13** —— **样本外** `2017-07..2022-09`(三段 + 全段),**逐段报告, 不做任何挑选** |

**跑法**:
```bash
python tools/cross_section/cross_section2.py
python tools/cross_section/cs_final.py
python tools/cross_section/cs_holdout.py
```

## 读它们时要注意的一件事

三支都**只读** `raw_kline_daily` / `hiagent_config.DB_PATH`,不依赖任何引擎代码。
⇒ 它们复现的是**横截面这条线本身**,**不是**四个引擎的回测。
若引擎或数据层变了,这三支的输出**不一定会跟着变** —— 那是预期的。

## 未抢救的部分 (如实说明)

`/tmp/hiagent_mining/` 里另有约 80 个脚本(`cs_diag.py` / `cs_min_vs_dec.py` / `cs_boards*.py` …),
记录的是**被否决的中间步骤**与诊断。它们**没有**进仓库 —— 登记册已经用文字记下了那条路径
(哪一步被否、为什么),再提交一遍脚本属于重复,且会把 82 个一次性脚本倒进 `tools/`。
⇒ **只抢救能复现"结论"的三支; 诊断路径留在 §7 的文字里。**
