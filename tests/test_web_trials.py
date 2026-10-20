"""trial 账本：append-only，且 **preview 也要记**（§5）。"""
from __future__ import annotations

import json

import pytest

from web.trials import (
    _read_all,
    append_trial,
    count_trials,
    distinct_manual_configs,
    recent_runs,
)


@pytest.fixture
def home(monkeypatch, tmp_path):
    monkeypatch.setenv("HIAGENT_PLATFORM_HOME", str(tmp_path))
    return tmp_path


def test_append_returns_a_monotonic_trial_number(home):
    a = append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                     param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01",
                     mode="full")
    b = append_trial(run_id="r2", engine="short_reversal", preset="v50_slope",
                     param_diff={"tp_pct": 0.10}, start="2024-01-01", end="2025-01-01",
                     mode="full")
    assert (a, b) == (1, 2)


def test_preview_runs_are_also_recorded(home):
    """preview 也要落账本（设计文档 §7.2）。

    漏记 preview 等于开了一个不提记账的调参后门——而 preview 正是调参循环里
    用得最多的模式，所以这个后门最容易被踩。

    ⚠️ 但**不要**把这理解成"窗口与 §5 无关"。原 docstring 曾这么写，是错的：
    §5 原文有一句 *"including changes to the evaluation window itself"*，
    换窗口**本身**就是一次迭代。两者是两件事：本条说的是"preview 要落账本"，
    窗口计入去重键由 `test_a_different_evaluation_window_is_a_new_trial` 守。
    """
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={"tp_pct": 0.09}, start="2025-01-01", end="2025-03-01",
                 mode="preview")
    assert count_trials("short_reversal", "v50_slope") == 1


def test_the_ledger_is_append_only_jsonl(home):
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    append_trial(run_id="r2", engine="short_reversal", preset="v50_slope",
                 param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    lines = (home / "trials.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2, "两条记录不能互相覆盖"
    assert all(json.loads(l)["run_id"] for l in lines)


def test_a_plain_reproduction_is_not_a_trial(home):
    """不带覆盖的运行只是复现一个已声明的 preset，不是一次迭代（§5）。"""
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    assert count_trials("short_reversal", "v50_slope") == 1                 # 审计条数
    assert distinct_manual_configs("short_reversal", "v50_slope") == 0      # 试验数


def test_the_same_overrides_twice_count_once(home):
    """同一组覆盖跑两次是同一个配置，只计一次。"""
    for rid in ("r1", "r2"):
        append_trial(run_id=rid, engine="short_reversal", preset="v50_slope",
                     param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01",
                     mode="full")
    assert count_trials("short_reversal", "v50_slope") == 2
    assert distinct_manual_configs("short_reversal", "v50_slope") == 1


def test_different_overrides_count_separately(home):
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01", mode="full")
    append_trial(run_id="r2", engine="short_reversal", preset="v50_slope",
                 param_diff={"tp_pct": 0.10}, start="2024-01-01", end="2025-01-01", mode="full")
    assert distinct_manual_configs("short_reversal", "v50_slope") == 2


def test_a_different_evaluation_window_is_a_new_trial(home):
    """**换窗口本身就是一次迭代。**（§5 明写，此处是它的守门测试）

    CLAUDE.md §5 原文：*"Every iteration — including changes to the evaluation
    window itself — increments `n_trials`."*

    去重键若只看 `param_diff`，同一组覆盖扫 20 个窗口去找最好看的那个，
    账本会显示"1 次试验"——**那正是 §5 最防的低报方向**，等于开了一个不提记账的调参后门。

    实跑复现（2026-10-19，修复前）：三个不同窗口 + 同一组覆盖 → 返回 **1**，§5 要求 **3**。

    判别力：把去重键里的 `start`/`end` 去掉，这条立刻变红。
    """
    for rid, s, e in (("r1", "2024-01-01", "2025-01-01"),
                      ("r2", "2023-01-01", "2024-01-01"),
                      ("r3", "2022-01-01", "2023-01-01")):
        append_trial(run_id=rid, engine="short_reversal", preset="v50_slope",
                     param_diff={"tp_pct": 0.09}, start=s, end=e, mode="full")
    assert distinct_manual_configs("short_reversal", "v50_slope") == 3, \
        "同一组覆盖换了三个窗口 = 三次迭代（§5：窗口变更也算迭代）"


def test_preview_and_full_are_separate_trials_for_the_same_overrides(home):
    """`mode` 也进去重键：preview 与 full 是同覆盖、**不同窗口**（preview 缩窗）。

    设计文档 §7.2 明写 preview 也计入账本；既然计入，它就必须是一次**独立的**迭代，
    而不是被 full 那次合并掉。
    """
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01", mode="full")
    append_trial(run_id="r2", engine="short_reversal", preset="v50_slope",
                 param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01", mode="preview")
    assert distinct_manual_configs("short_reversal", "v50_slope") == 2


def test_the_exact_same_run_twice_still_counts_once(home):
    """反向守门：**同覆盖 + 同窗口 + 同 mode** 才是"同一个配置"，必须仍然去重。

    没有这条，上面两条可以靠"干脆不去重"变绿——那样 n_trials 会虚高，
    虚增 DSR/Bonferroni 惩罚，同样使判据失真。
    """
    for rid in ("r1", "r2"):
        append_trial(run_id=rid, engine="short_reversal", preset="v50_slope",
                     param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01",
                     mode="full")
    assert distinct_manual_configs("short_reversal", "v50_slope") == 1


def test_count_is_per_engine_and_preset(home):
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    append_trial(run_id="r2", engine="chase_up", preset="v19",
                 param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    assert count_trials("short_reversal", "v50_slope") == 1
    assert count_trials("chase_up", "v19") == 1
    assert count_trials("short_reversal", "v44_ratio02_buf07") == 0


def test_recent_runs_returns_newest_first_and_honours_the_limit(home):
    """`recent_runs` 是"历史/对比"面板的数据源：**倒序**，且 `limit` 只截尾部。

    它是 `web.trials` 的公开 API，却一度没有任何测试——改坏了没人知道。
    账本是 append-only，故"最近"就是文件尾部；倒序错了面板会把最老的运行
    当成"最近一次"，`limit` 失效则会把整部账本倒给前端。
    """
    for rid in ("r1", "r2", "r3"):
        append_trial(run_id=rid, engine="short_reversal", preset="v50_slope",
                     param_diff={}, start="2024-01-01", end="2025-01-01", mode="full")
    assert [r["run_id"] for r in recent_runs()] == ["r3", "r2", "r1"], "必须是倒序"
    assert [r["run_id"] for r in recent_runs(limit=2)] == ["r3", "r2"], "limit 取最近的 N 条"


def test_one_torn_line_does_not_take_the_whole_ledger_down(home):
    """**一行坏数据的代价不该是"整个记账不可用"。**

    账本是 append-only 的，所以半行是**正常会发生的**：进程被杀、磁盘写满、断电，
    都会在文件尾留下一条不完整的 JSON。实测（2026-10-19）：手工追加一行撕裂记录后，
    `count_trials` / `distinct_manual_configs` / `recent_runs` **全部抛
    JSONDecodeError** —— §5 唯一的记账机制在最需要它的时候消失了。

    这条断言：坏行被**跳过**，其余记录照常可读。
    """
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01", mode="full")
    append_trial(run_id="r2", engine="short_reversal", preset="v50_slope",
                 param_diff={"tp_pct": 0.10}, start="2024-01-01", end="2025-01-01", mode="full")

    # 撕裂：追加一条**不完整**的 JSON（模拟进程被杀 / 磁盘写满）
    with (home / "trials.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"trial_no": 3, "run_id": "r3", "ban')

    assert count_trials("short_reversal", "v50_slope") == 2, \
        "坏行让整个账本不可读了——§5 的 n_trials 会凭空消失"
    assert distinct_manual_configs("short_reversal", "v50_slope") == 2
    assert [r["run_id"] for r in recent_runs(10)] == ["r2", "r1"], "好记录必须照常可读"


def test_writing_after_a_torn_line_still_works(home):
    """坏行之后**继续追加**也要正常——不能因为尾部有半行就再也写不进去。"""
    with (home / "trials.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"torn": ')
    n = append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                     param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01", mode="full")
    assert n == 1, "trial_no 从可读记录数推——坏行不该把编号也算进去"
    assert count_trials("short_reversal", "v50_slope") == 1


def test_trial_numbers_are_unique_under_concurrent_appends(home):
    """**`trial_no` 在并发提交下也必须唯一。**

    原实现是"先读全量长度、再追加"，两步之间没有锁 → 两个并发提交读到同一个长度、
    拿到**同一个编号**。实测（修复前，40 个线程）：只得到 **22 个不同编号**，
    其中 `1` 被用了 **9 次** —— 而 docstring 声称的是"全局单调"，那是假的。
    于是 `trial_no` 不能再标识一条记录，按它排序/去重的消费方（`list_runs`、
    `/api/compare`）全都会错。

    锁是**进程级**的（本平台单进程 ✓）；多进程部署时这个锁等于没有，
    docstring 里写明了，届时要换成 `fcntl.flock`。
    """
    import threading

    got, lock = [], threading.Lock()

    def worker(i):
        n = append_trial(run_id=f"r{i}", engine="short_reversal", preset="v50_slope",
                         param_diff={"tp_pct": round(0.05 + i * 0.001, 4)},
                         start="2024-01-01", end="2025-01-01", mode="full")
        with lock:
            got.append(n)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(got)) == 40, f"只拿到 {len(set(got))} 个不同编号（修复前是 22）"
    nums = [r["trial_no"] for r in _read_all()]
    assert sorted(nums) == list(range(1, 41)), f"编号不连续/有重复：{sorted(nums)[:10]}…"


def test_the_ledger_timestamp_carries_an_explicit_timezone(home):
    """§0：时间戳必须是**带时区的单一基准**。

    原实现用 `datetime.now()` —— naive 的**本地**时间。本机与 UTC 差 8 小时，
    于是换一台时区不同的机器写的账本**事后无法解读**是哪一天，
    而 §0 明确要求"normalize timestamps to a single exchange timezone"。
    """
    append_trial(run_id="r1", engine="short_reversal", preset="v50_slope",
                 param_diff={"tp_pct": 0.09}, start="2024-01-01", end="2025-01-01", mode="full")
    at = _read_all()[0]["at"]
    assert at.endswith("+00:00") or at.endswith("Z"), \
        f"时间戳必须带显式时区（§0），现在是 {at!r}"
