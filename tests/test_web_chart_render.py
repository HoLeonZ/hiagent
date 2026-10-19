"""图表渲染的契约：SL/TP 必须是画出来的横线；K 线用原始价、指标用 payload。

两份检查，各防一类缺陷：

* **静态**（前三条，出自计划 Task 8 Step 1）：防"忘了画"——函数没实现、SL/TP 只写成
  文案、指标在 JS 里另算一遍。
* **行为级**（后两条）：把 `app.js` 真跑一遍、把 `setOption` 的实参抓下来。
  静态检查**看不出价域与数据序**：`[raw_open, raw_high, raw_low, raw_close]`（错的 OHLC 序）
  与正确写法在字面上都是"取了四个 raw_ 字段"，而画出来**仍然像一张正常的 K 线图**。
  只有真执行一次才能把"看起来在把关"变成真的在把关。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

#: ⚠️ **必须锚到本文件的位置**，不能用 `Path("web/static/app.js")` 这种相对路径：
#: 相对路径是相对 **pytest 的启动目录**的，换个目录跑就变成"找不到 app.js"——
#: 假警报会诱使人把契约测试改弱或删掉（同 `tests/test_web_frontend_contract.py`）。
REPO_ROOT = Path(__file__).resolve().parents[1]
JS = REPO_ROOT / "web" / "static" / "app.js"

#: 画图里**允许**的 UI 算术（与 Task 7 的契约测试同一条原则）。
#: **不 ban 裸 `Math.`** —— 一刀切会把 `Math.max`（坐标轴范围）、`Math.round`（tooltip）
#: 这些正常代码判红，逼人要么改正常代码、要么把测试删掉。过宽的规则和过窄的规则一样坏。
BANNED_STATISTICS = (
    r"Math\.(sqrt|pow|log|exp|cbrt)",   # 只 ban 统计类 Math
    r"(?<![0-9a-fA-F#])252\b",          # √252；前面不是十六进制字符（排除 #ff5252）
)


def _chart_body() -> str:
    """取出 `renderChart` 的函数体（**花括号配平**，不是按下一个 `function` 切）。

    **抽取器必须自证有效**：函数若被改名，这里立刻给出可读的错误，
    而不是让后面三条断言各自莫名其妙地红。

    **也必须给上界**。计划里写的是 `split("\\nfunction ", 1)`，那个上界**是漏的**：
    `renderChart` 之后是 `async function loadConfigs`，它不以 `function ` 开头，
    所以切不断；真正切断它的是再下一个 `function renderConfigs`——于是 `loadConfigs`
    整个被吞进 body。后果是 `"markLine" in body` 之类的断言可能匹配到**别的函数**里的
    字面量，测试变成假绿。花括号配平才是这里的上界。
    """
    js = JS.read_text(encoding="utf-8")
    assert "function renderChart" in js, "app.js 里找不到 `function renderChart`——契约测试失去判别力"
    start = js.index("function renderChart")
    depth = 0
    end = -1
    for i in range(js.index("{", start), len(js)):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    assert end > 0, "renderChart 的花括号不配平——抽取器失效（或函数被截断）"
    body = js[start:end]
    assert len(body) > 200, f"renderChart 的函数体只抽到 {len(body)} 字符——抽取器可能失效"
    # 上界自证：没吞掉后面的函数（吞掉了说明抽取逻辑退回成"切到下一个 function"）
    assert "function loadConfigs" not in body, "抽取器越过了 renderChart 的右花括号"
    return body


def test_render_chart_is_implemented():
    body = _chart_body()
    assert "echarts.init" in body, "renderChart 尚未实现"
    # ⚠️ 断言必须**匹配属性写法**，`"candlestick" in body` 这种裸子串是**假绿**的：
    # 注释里的"candlestick"、变量名、series 名都能满足它。
    # 实测（M2 变异，把 `type: "candlestick"` 改成 `type: "line"`）：用裸子串时
    # 这条**纹丝不动**，只有行为级测试变红；改成下面这个模式后才真的红。
    assert re.search(r'type:\s*["\']candlestick["\']', body), "K 线必须是 candlestick 类型"


def test_sl_and_tp_are_drawn_as_lines_not_just_text():
    """§4 的 SL/TP 是相对百分比，图上必须**画出价位**。

    同一条纪律：`"markLine" in body` 会被**变量名 `markLines`** 满足。
    实测（M1b 变异：保留 `const markLines` 但把 `markLine: markLines` 从 K 线 series 上摘掉）：
    裸子串版本仍然全绿，图却已经没有那两条线了。故这里要求 `markLine:` 属性前有"线"的后缀约束。
    """
    body = _chart_body()
    assert re.search(r"markLine\s*:", body), "SL/TP 必须用 markLine 画成横线"
    assert "sl_price" in body and "tp_price" in body


def test_indicators_come_from_the_payload_not_from_js_math():
    """指标必须**来自 payload**，前端不得自行计算。

    只 ban 统计类（见 `BANNED_STATISTICS`），不 ban `Math.max` 这类 UI 算术。
    """
    body = _chart_body()
    for series in ("ma5", "ma20", "ma60", "macd_dif"):
        assert series in body, f"未绘制 {series}"
    for pattern in BANNED_STATISTICS:
        assert not re.search(pattern, body), f"图表里出现自行计算的统计量: /{pattern}/"


# ─────────────────────────── 行为级契约（真跑一遍 app.js） ───────────────────────────

#: 用假 DOM/假 echarts 把 app.js 载进 node 并调用 `renderChart`。
#: `fetch` 给一个**永不 resolve** 的 promise：app.js 结尾会自跑 `loadCatalog()` 等三个异步函数，
#: 若让 fetch 抛错，未处理的 rejection 会让 node **以非零码退出**——
#: 于是"渲染正确"被报成"测试崩溃"，正是最容易被误读成假象的失败方式。
_DRIVER = r"""
const fs = require("fs");
const vm = require("vm");
const [jsPath, payloadPath] = process.argv.slice(2);

const els = new Map();
function fakeEl() {
  return { addEventListener() {}, appendChild() {}, querySelectorAll: () => [],
           querySelector: () => null, classList: { toggle() {}, add() {}, remove() {} },
           dataset: {}, style: {}, innerHTML: "", textContent: "", value: "", hidden: false };
}
const document = {
  getElementById(id) { if (!els.has(id)) els.set(id, fakeEl()); return els.get(id); },
  querySelectorAll: () => [], querySelector: () => null,
  createElement: () => fakeEl(), addEventListener() {},
};
const captured = [];
const echarts = { init() { return { setOption(o) { captured.push(o); }, resize() {} }; } };
const ctx = {
  document, echarts, console, alert() {}, prompt: () => null,
  fetch: () => new Promise(() => {}), addEventListener() {},
  setTimeout, clearTimeout, setInterval, clearInterval,
};
ctx.window = ctx;
ctx.globalThis = ctx;

vm.createContext(ctx);
vm.runInContext(fs.readFileSync(jsPath, "utf8"), ctx, { filename: jsPath });
if (typeof ctx.renderChart !== "function") {
  console.error("app.js 里没有可调用的 renderChart——抽取器失效");
  process.exit(2);
}

const payload = JSON.parse(fs.readFileSync(payloadPath, "utf8"));

// **每次调用各自 try/catch。** 若让异常逃出去，node 会以非零码退出，
// 于是测试报的是 fixture 层的"node 执行失败"——那读起来像**harness 坏了**，
// 而真相是**被测代码抛了**。把抛出原因原样带回，让断言红得清楚。
function render(name) {
  const opts = [];
  try {
    ctx.renderChart(payload[name]);
  } catch (e) {
    return { threw: e.constructor.name + ": " + e.message, options: opts };
  }
  while (captured.length) opts.push(captured.shift());
  return { threw: null, options: opts };
}

process.stdout.write(JSON.stringify({
  with_data: render("with_data"),
  empty: render("empty"),
  no_levels: render("no_levels"),
  chart_html: els.get("chart") ? els.get("chart").innerHTML : "",
}));
"""

BAR_A = {"date": "2026-03-02", "raw_open": 10.0, "raw_close": 11.0, "raw_low": 9.0, "raw_high": 12.0,
         "adj_open": 7.0, "adj_close": 7.7, "adj_low": 6.3, "adj_high": 8.4, "volume": 1000.0,
         "ma5": 10.5, "ma10": 10.4, "ma20": 10.2, "ma60": None,
         "macd_dif": -0.11, "macd_dea": -0.09, "macd_bar": -0.02}
BAR_B = {"date": "2026-03-03", "raw_open": 11.0, "raw_close": 9.5, "raw_low": 9.4, "raw_high": 11.2,
         "adj_open": 7.7, "adj_close": 6.65, "adj_low": 6.58, "adj_high": 7.84, "volume": 2000.0,
         "ma5": 10.9, "ma10": 10.6, "ma20": 10.3, "ma60": 9.9,
         "macd_dif": -0.13, "macd_dea": -0.10, "macd_bar": -0.03}

#: 空头一笔：止损在入场价**上方**、止盈在**下方**（`web.chart.sl_tp_prices` 的口径）。
PAYLOAD: dict[str, Any] = {
    "bars": [BAR_A, BAR_B],
    "entry": {"date": "2026-03-02", "price": 10.0},
    "exit": {"date": "2026-03-03", "price": 9.2, "reason": "take_profit"},
    "sl_price": 10.5, "tp_price": 9.2, "direction": "short",
}
EMPTY_PAYLOAD: dict[str, Any] = {"bars": [], "entry": None, "exit": None,
                                 "sl_price": None, "tp_price": None, "direction": "short"}
#: 有日线、但**没有可画的 SL/TP 价位** —— 后端在"引擎按 ATR 出场"或"预设没给这两个参数"时
#: 就是这么返回的。图表仍要画出来，只是**一条横线都不许有**。
NO_LEVELS_PAYLOAD: dict[str, Any] = {
    "bars": [BAR_A, BAR_B],
    "entry": {"date": "2026-03-02", "price": 10.0},
    "exit": {"date": "2026-03-03", "price": 9.2, "reason": "take_profit"},
    "sl_price": None, "tp_price": None, "direction": "long",
}

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="需要 node 执行前端契约")


@lru_cache(maxsize=1)
def _run_render_chart(tmp: str) -> dict[str, Any]:
    """在 node 里真跑一次 `renderChart`，返回假 echarts 抓到的 `setOption` 实参。"""
    tmp_path = Path(tmp)
    driver = tmp_path / "driver.js"
    payload = tmp_path / "payload.json"
    driver.write_text(textwrap.dedent(_DRIVER), encoding="utf-8")
    payload.write_text(json.dumps({"with_data": PAYLOAD, "empty": EMPTY_PAYLOAD,
                                   "no_levels": NO_LEVELS_PAYLOAD}), encoding="utf-8")
    got = subprocess.run(["node", str(driver), str(JS), str(payload)],
                         capture_output=True, text=True, timeout=120)
    assert got.returncode == 0, f"node 执行 app.js 失败（rc={got.returncode}）:\n{got.stderr}"
    return json.loads(got.stdout)


@pytest.fixture
def rendered(tmp_path_factory) -> dict[str, Any]:
    return _run_render_chart(str(tmp_path_factory.mktemp("chartjs")))


@needs_node
def test_candles_are_raw_prices_in_open_close_low_high_order(rendered):
    """K 线必须是 **raw_** 价、且数据序是 `[open, close, low, high]`。

    这条**只有真跑一遍才有判别力**：把顺序写成 OHLC，静态看仍然是"取了四个 raw_ 字段"，
    画出来也仍然像一张正常的 K 线图——只是阴阳与上下影线是反的。
    """
    assert rendered["with_data"]["threw"] is None, f"renderChart 抛了：{rendered['with_data']['threw']}"
    options = rendered["with_data"]["options"]
    assert len(options) == 1, "renderChart 应当只 setOption 一次"
    candle = options[0]["series"][0]
    assert candle["type"] == "candlestick"
    assert candle["data"] == [[10.0, 11.0, 9.0, 12.0], [11.0, 9.5, 9.4, 11.2]], \
        "candlestick 数据序必须是 [open, close, low, high]"
    # 判别力自检：错误的 OHLC 序**必须**与上面不同——否则这条断言什么都没排除
    wrong = [[b["raw_open"], b["raw_high"], b["raw_low"], b["raw_close"]] for b in PAYLOAD["bars"]]
    assert candle["data"] != wrong, "价序或价域写反了（拿 OHLC / 复权价画蜡烛）"


@needs_node
def test_indicators_and_sl_tp_come_verbatim_from_the_payload(rendered):
    """图上每一条线/点位都必须**逐位等于 payload 里的数**（前端不派生）。

    MA/MACD 在复权域上算、SL/TP 由 `entry_price × (1 ± pct)` 推——两者都在后端。
    前端若自己重算，这里会立刻不等；`null` 也必须原样传给 ECharts（断线，不是断成 0）。
    """
    assert rendered["with_data"]["threw"] is None, f"renderChart 抛了：{rendered['with_data']['threw']}"
    option = rendered["with_data"]["options"][0]
    by_name = {s["name"]: s for s in option["series"]}

    for name in ("ma5", "ma20", "ma60"):
        assert by_name[name]["data"] == [b[name] for b in PAYLOAD["bars"]], \
            f"{name} 不是 payload 里的那一列（前端自己算了？）"
    assert by_name["ma60"]["data"][0] is None, "暖机不足的 null 必须原样传给 ECharts（断线），不能填成 0"
    assert [by_name["macd_dif"]["data"][0], by_name["macd_dea"]["data"][0],
            by_name["macd_bar"]["data"][0]] == [-0.11, -0.09, -0.02]

    # 入场/出场只画在 payload 给的那一点上（不是"用指标反推"出来的点）
    assert by_name["入场"]["data"] == [["2026-03-02", 10.0]]
    assert by_name["出场"]["data"] == [["2026-03-03", 9.2]]

    lines = by_name["K"]["markLine"]["data"]
    assert [ln["yAxis"] for ln in lines] == [10.5, 9.2], "SL/TP 横线必须画在 payload 给的价位上"
    assert all(ln["lineStyle"]["type"] == "dashed" for ln in lines)


@needs_node
def test_a_payload_without_bars_does_not_throw(rendered):
    """`bars: []` 是后端**设计好的**返回（窗口内查不到日线）：不许抛、也不许留旧图。

    计划里的实现直接取 `d.entry.date`，在 `entry: None` 上抛 TypeError——
    页面其余部分一切正常，只有图表区静默停在上一笔，看起来像"点了没反应"。
    """
    assert rendered["empty"]["threw"] is None, f"空 payload 让 renderChart 抛了：{rendered['empty']['threw']}"
    assert rendered["empty"]["options"] == [], "空 payload 不应 setOption（会把上一笔的图留着）"
    assert "日线" in rendered["chart_html"], "空 payload 应在图表区给出可读的说明，而不是留白"


@needs_node
def test_no_sl_tp_lines_when_the_backend_says_there_are_none(rendered):
    """后端说没有价位时，图上**一条横线都不许有**。

    什么时候会没有：引擎按**信号日 ATR 自适应**出场（`chase_up` 的 22/22 个预设都是），
    或预设压根没给 `sl_pct`/`tp_pct`。原实现无条件按 `entry × (1 ± sl_pct)` 画，
    于是 chase_up 的图上会出现**一条引擎从未使用过的止盈线**（差 12 个百分点）——
    **那比不画更坏**：它让用户以为策略是按那条线退出的。

    判据落在**渲染出来的 option** 上：`K` series 必须没有 `markLine`（或它的 data 为空），
    图本身仍然画出来。
    """
    assert rendered["no_levels"]["threw"] is None, \
        f"没有 SL/TP 价位时 renderChart 抛了（多半是在 null 上取小数点）：{rendered['no_levels']['threw']}"
    assert len(rendered["no_levels"]["options"]) == 1, "没有 SL/TP 也一样要出图"
    candle = rendered["no_levels"]["options"][0]["series"][0]
    assert candle["type"] == "candlestick", "蜡烛仍要画"
    assert candle["data"], "日线在，K 线就该有数据"
    ml = candle.get("markLine")
    assert not ml or not ml.get("data"), f"后端说没有价位，图上却有横线：{ml}"
