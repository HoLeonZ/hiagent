"""前端的静态契约：不引 CDN 之外的依赖、不做数值计算、只调存在的端点。"""
from __future__ import annotations

from pathlib import Path

#: ⚠️ **必须锚到本文件的位置，不能用 `Path("web/static")` 这种相对路径。**
#: 相对路径是相对 **pytest 的启动目录**的：从仓库根跑全绿，换个目录跑就全红——
#: 而失败消息会是"缺 index.html"，把"测试找错了地方"说成"文件不存在"。
#: 那种假警报会诱使人把契约测试改弱或删掉，正好与它的目的相反。
REPO_ROOT = Path(__file__).resolve().parents[1]
STATIC = REPO_ROOT / "web" / "static"


def test_static_files_exist():
    for name in ("index.html", "style.css", "app.js"):
        assert (STATIC / name).is_file(), f"缺 {name}"


def test_only_echarts_is_loaded_from_a_cdn():
    """无构建步骤：除 ECharts 外不得引入任何外部脚本/样式。"""
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    externals = [
        line for line in html.splitlines()
        if ("http://" in line or "https://" in line) and ("<script" in line or "<link" in line)
    ]
    assert len(externals) == 1, f"只应有一处外部资源(ECharts)，实为 {len(externals)}: {externals}"
    assert "echarts" in externals[0]


def test_the_frontend_does_not_derive_result_statistics():
    """该守的性质是：前端**不得从 API 数值派生统计量**（年化、比率、聚合）。

    结果是：指标一律来自后端，否则前后端会各自算出一套、给出不一致的数字。

    **不 ban `Math.round/abs/min/max`** —— 它们是 UI 机制，不是统计：
    当前 app.js 里只有三处（`:179` 把已等的毫秒取整成人看的秒、
    `:306` 把交易下标夹进数组范围），没有一处碰结果数字。
    一刀切 ban `Math.` 会把这些正常代码判红——**过宽的规则和过窄的规则一样坏**：
    它逼着人要么改正常的代码、要么把测试删掉。

    同理**不按裸子串匹配**：直接 ban 子串 `252` 会把十六进制颜色 `#ff5252`
    判成"硬编码年化常数"。裸子串是"年化计算"的**代理**，不是它本身。
    """
    import re

    js = (STATIC / "app.js").read_text(encoding="utf-8")
    BANNED = (
        r"Math\.(sqrt|pow|log|exp|cbrt)",   # 统计类 Math，**不含** round/abs/min/max
        r"\*\*\s*0\.5",                   # 另一条开方写法
        r"(?<![0-9a-fA-F#])252\b",          # √252 常数，但前面不是十六进制字符（排除 #ff5252）
    )
    for pattern in BANNED:
        assert not re.search(pattern, js), f"前端出现了统计计算: /{pattern}/"


def test_frontend_only_calls_endpoints_that_exist():
    """端点契约测试：app.js 里 fetch 的每个 API 路径都必须真的存在于路由表。

    没有这条，改一个路由名就会让前端静默 404——这正是本仓库反复出现的
    "看起来在工作、实际没连上"那类缺陷的前端版本。
    """
    import re

    from web.app import create_app

    routes = {r.path for r in create_app().routes}
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    called = set()
    for raw in re.findall(r"""fetch\(\s*[`'"]([^`'"]+)""", js):
        norm = re.sub(r"\$\{[^}]*\}", "{x}", raw.split("?")[0])
        called.add(norm)
    assert called, "没在 app.js 里找到任何 fetch 调用——契约测试失去判别力"
    # 路由表里是 {run_id} / {i}，前端是 ${...}，两边都归一成 {x}
    normalized_routes = {re.sub(r"\{[^}]*\}", "{x}", p) for p in routes}
    missing = {c for c in called if c not in normalized_routes}
    assert not missing, f"前端调用了不存在的端点: {sorted(missing)}"


def test_every_fetch_target_is_a_literal_or_template_string():
    """端点契约的**另一半**，没有它上一条就是"看似已检查"。

    上一条只能静态比对**字面量**路径。若哪天有人写成 `fetch(base + path)`，
    上一条的正则抓不到它——于是那个端点**静默地脱离了契约**，检查却仍然全绿。
    要求所有 fetch 的实参都是字面量/模板串，契约才**完整**：
    要么指向一个存在的路由，要么被上一条拦下，没有第三种可能。

    （实测 app.js 现有的 15 处 fetch 全部满足——规则不比现状宽。）
    """
    import re

    js = (STATIC / "app.js").read_text(encoding="utf-8")
    args = re.findall(r"fetch\(\s*([^\s,)]+)", js)
    assert len(args) >= 10, f"只找到 {len(args)} 处 fetch——抽取器失效了"
    for arg in args:
        assert arg[:1] in "`'\"", f"fetch 的实参不是字面量/模板串: fetch({arg}…)"


def test_every_dom_id_the_script_looks_up_exists_in_the_html():
    """跨边界引用：`app.js` 里 `$("x")` 的每个 id 都必须在 `index.html` 里有 `id="x"`。

    这**一定会**在运行时炸、而不是在构建时：没有构建步骤、没有类型检查，
    `$("nope")` 返回 `null`，下一行 `.innerHTML = …` 就在浏览器里抛 TypeError，
    **页面静默不渲染**，而全部 Python 测试仍然全绿。

    这是本仓库那类"看起来在工作、实际没连上"缺陷的前端版本——
    和"后端路由与前端 fetch 对不上"是同一个跨边界引用问题，故并列成两条。
    """
    import re

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    html_ids = set(re.findall(r'id="([^"]+)"', html))
    js_ids = set(re.findall(r'\$\("([^"]+)"\)', js))
    js_ids |= set(re.findall(r"""getElementById\(\s*['"]([^'"]+)['"]""", js))

    # **判别力自检**：抽取器必须真的抽到东西。
    # 若哪天 app.js 换成别的取值写法，正则匹配 0 个 id，`js_ids - html_ids` 是空集，
    # 这条测试会在"什么都没检查"的情况下变绿——那正是它要防的那种缺陷。
    assert len(html_ids) >= 15, f"index.html 里只抽到 {len(html_ids)} 个 id——抽取器失效了"
    assert len(js_ids) >= 15, f"app.js 里只抽到 {len(js_ids)} 个 id——抽取器失效了"

    missing = js_ids - html_ids
    assert not missing, f"app.js 引用了 index.html 里不存在的 id: {sorted(missing)}"


def test_the_metric_table_takes_its_labels_from_the_server():
    """指标的中文标签**只能来自 `/api/catalog` 的 `metric_meta`**（设计文档 §6.1）。

    前端若自备一份标签表，两份必然漂移——而漂移的表现是"某一格格式不对/显示成英文"，
    **不会有人注意到**。这条把"又抄了一份"变成构建期就能看见的红。
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "metricMeta" in js, "app.js 必须从 /api/catalog 取 metric_meta"

    from web.metrics_view import METRIC_LABELS

    leaked = [v for v in METRIC_LABELS.values() if f'"{v}"' in js or f"'{v}'" in js]
    assert not leaked, f"app.js 里硬编码了指标标签（应改用 metric_meta）: {leaked}"


def test_the_frontend_does_not_hide_a_missing_metric():
    """§0/§6.1：缺失的指标要**如实显示**，不能整个格子丢掉。

    原实现是 `.filter(([, v]) => typeof v === "number")` —— 它把 `None` 静默滤掉，
    于是**"这个引擎不产出年化"与"平台忘了算"在界面上长得一样**。
    §0 的规则是如实表示缺失（渲染成 `—` 并保留格子）。
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'typeof v === "number"' not in js.replace(" ", ""), \
        "疑似又在用 typeof 过滤指标——那会把 None 静默丢掉"
    assert '"—"' in js or "'—'" in js, "缺失值必须渲染成明确的占位符，而不是空着"


def test_the_frontend_does_not_reformat_metrics_with_a_fixed_precision():
    """单位是数据的一部分：按服务端声明的 `kind` 渲染，不用 `toFixed(4)` 一把梭。

    原写法会把 `trades_count` 渲染成 `74.0000`、`final_capital` 渲染成 `1500000.0000`。
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "fmtValue" in js, "指标必须走按 kind 分支的格式化函数"
    assert "toFixed(4)" not in js, "不得对指标用固定四位小数，应按 kind 渲染"


def test_the_trade_table_formats_by_unit_instead_of_dumping_raw_floats():
    """交易表**按单位格式化**，不能把原始浮点直接倒出来。

    原实现是 `${row[c] ?? ""}`，界面上因此出现 `-499.42349999992143`、
    `-0.001499000749437843` 这种东西（起服务跑一次就能看到）。
    单位是数据的一部分——表列名来自后端的 14 列 schema，但 schema 只说列名、
    不说单位，所以这一层必须显式声明（`TRADE_KINDS`），不能靠"看着像数字就原样放"。
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "TRADE_KINDS" in js, "交易表必须按列声明单位"
    assert "fmtValue" in js, "交易表必须走按单位分支的格式化函数"
    # 查的是**渲染表达式**，不是随便出现这个词——注释里提到旧写法不该被误伤。
    import re

    assert not re.search(r"<td>\$\{row\[c\]", js), "疑似又直接把原始值塞进单元格了"


def test_the_trade_table_keeps_stop_and_target_visually_distinct():
    """止损/止盈必须用**比入场价更高的精度**。

    本预设 `sl_pct = 0.0005`：8.01 的止损是 **8.014**。若两位小数显示，
    它会渲染成 `8.01` —— **与入场价一模一样**，读表的人会以为止损就画在入场价上。
    这不是洁癖：那是这个预设的**正常形态**，不是极端情形。
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert 'sl_price: "price3"' in js, "止损要用 3 位小数"
    assert 'tp_price: "price3"' in js, "止盈要用 3 位小数"


def test_fmtValue_behaves_correctly_when_actually_executed():
    """**真正执行 `fmtValue`**，而不是检查它的名字在不在文件里。

    为什么需要这一条：契约测试原先全是**字符串存在性**检查。我按它们把
    `TRADE_KINDS` / `fmtValue` 加进去之后，那些检查**全绿**，
    而页面上每一列日期、代码、退出原因都显示成了 `—` —— 因为
    `Number("2026-03-09")` 是 `NaN`，被"非数就 —"那条分支提前拦掉了。
    **只有真的看一眼浏览器才发现。** 所以这里真的把 app.js 加载进一个
    最小的 DOM 桩、调 `fmtValue`、断言输出。

    （判定条件里也有教训：一条只查"函数名在不在"的契约测试，
    在函数写错时是**不可能**红的。）
    """
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("没有 node，无法执行 JS")

    harness = """
const fs = require("fs");
const el = { addEventListener(){}, style:{}, classList:{add(){},remove(){}},
  querySelector: () => el, querySelectorAll: () => [], appendChild(){}, remove(){},
  setAttribute(){}, click(){}, innerHTML:"", textContent:"", disabled:false,
  hidden:false, value:"", children:[], dataset:{} };
global.document = { getElementById: () => el, querySelector: () => el,
  querySelectorAll: () => [], createElement: () => el, addEventListener(){} };
global.window = { addEventListener(){} };
// 让应用的初始化挂起：我们只关心 fmtValue，不想让它真去拉 catalog
global.fetch = () => new Promise(() => {});
eval(fs.readFileSync(process.argv[1], "utf8"));
const cases = [
  ["2026-03-09", undefined, "2026-03-09"],
  ["600156.SH",  undefined, "600156.SH"],
  ["SL",         undefined, "SL"],
  [-1498.3953558749215, "money",  "-1,498.40"],
  [-0.001499000749437843, "pct",   "-0.15%"],
  [8.014005, "price3", "8.014"],
  [8.014,    "price",  "8.01"],
  [124700,   "int",    "124700"],
  [null,     "pct",    "\\u2014"],
  // ↓ ratio / days：**这两个分支曾是缺口**。原实现有两个格式化函数
  //   （`fmtMetric` 给指标、`fmtCell` 给交易），而 `fmtCell` **没有** ratio/days ——
  //   把 `fmtCell` 用到指标上（对比面板）后，`夏普比率` 掉进兜底分支，
  //   输出 `3.3891465183413962`（实测截图发现）。合并为一个函数后补上这两条。
  [3.3891465183413962, "ratio", "3.39"],
  [2.35714, "days", "2.4 天"],
  // 负零：-0.0015 在两位小数下是 "-0.00"，读起来像 bug；规范成 "0.00"
  [-0.0015,  "money",  "0.00"],
  [-1234.5,  "money",  "-1,234.50"],   // 真负数必须保留符号
];
console.log(JSON.stringify(cases.map(([v, k, want]) => [v, k, fmtValue(v, k), want])));
"""
    r = subprocess.run([node, "-e", harness, str(STATIC / "app.js")],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, f"加载 app.js 失败：{r.stderr[-400:]}"
    results = json.loads(r.stdout.strip().splitlines()[-1])
    bad = [
        f"fmtValue({v!r}, {k!r}) = {got!r}，应为 {want!r}"
        for v, k, got, want in results if got != want
    ]
    assert not bad, "交易表单元格格式化错了：\n  " + "\n  ".join(bad)


def test_the_trade_table_headers_come_from_the_server_not_from_english_keys():
    """**交易明细的表头必须用服务端下发的中文标签。**

    实测（2026-10-21 看真实页面截图）：指标表已经是中文，而交易明细的表头
    却是 `entry_date`/`exit_date`/`thscode` 这些英文键 —— **同一个页面上两套语言**。
    聚宽的交易明细是中文列头。

    标签与平仓原因的中文值都由 `/api/catalog` 的 `trade_meta` 下发，
    前端**不得自备一份**（两份必然漂移，而漂移的表现是"某一列表头变英文了"，
    不会有人注意到）。
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "tradeMeta" in js, "app.js 必须从 /api/catalog 取 trade_meta"
    assert "labels[c] || c" in js, "表头应当用服务端标签，取不到时才退回键名"

    from web.metrics_view import EXIT_REASON_LABELS, TRADE_LABELS

    # 14 列规范 + 平台补的两列，**每一列都要有中文名**
    from core.trade_schema import TRADE_COLS

    for c in list(TRADE_COLS) + ["sl_price", "tp_price"]:
        assert c in TRADE_LABELS, f"交易列 {c} 没有中文表头"
        assert TRADE_LABELS[c], f"交易列 {c} 的中文表头是空的"
    # 平仓原因的英文码要有中文值
    for code in ("SL", "TP", "time", "eod"):
        assert code in EXIT_REASON_LABELS, f"平仓原因 {code} 没有中文值"


def test_the_history_list_shows_each_runs_return():
    """**历史列表里每条直接显示收益** —— 对标聚宽的「我的回测」。

    没有它，用户得把每次运行都点开才知道哪个好；而"改了参数之后得能看出
    哪个更好"正是这个平台存在的理由。

    判据落在**服务端给的数据**上（`/api/runs` 每条带 `metrics`），
    前端只把它格式化出来。
    """
    from fastapi.testclient import TestClient

    from web.app import create_app

    client = TestClient(create_app())
    runs = client.get("/api/runs?limit=5").json()["runs"]
    if not runs:
        pytest.skip("本地状态目录里没有运行记录（§6：缺失应 skip 而非 error）")
    for r in runs:
        assert "metrics" in r, "每条运行都要带 metrics 字段（没有结果时为 None）"
        if r.get("has_result"):
            assert r["metrics"] is not None, f"{r['run_id']} 声称有结果却没有指标"
            assert r["metrics"]["total_return"] is not None
        else:
            assert r["metrics"] is None, "没有结果的运行不该带指标"

    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "h.metrics" in js, "历史行应当把该次运行的收益显示出来"
    assert "fmtValue(h.metrics.total_return" in js, \
        "收益要按服务端声明的单位格式化，不能原样倒出"


def test_history_is_rerendered_once_the_metric_metadata_arrives():
    """**历史行的收益不能退化成原始浮点。**

    `loadHistory()` 与 `loadCatalog()` 是**并发**发起的（页面末尾连写三行，都不 await），
    历史可能先渲染 —— 那时 `HP.metricMeta` 还没到，`fmtValue` 拿不到 `kind`，
    于是收益渲染成 `1.1502863790988918`（实测截图确认，会被读成 1.15%）。

    修法必须与"谁先完成"无关：元数据到位后**重渲染一次**。
    靠"保证 loadCatalog 先跑完"太脆 —— 那一行挪个位置就悄悄坏了，
    而坏的表现只是"数字格式变了"，不会有测试注意到。
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "renderHistory()" in js
    # 在 loadCatalog 里（metricMeta 赋值之后）必须有一次重渲染
    i = js.index("HP.metricMeta = body.metric_meta")
    j = js.index("renderCatalog(", i)          # loadCatalog 的结尾
    assert "renderHistory()" in js[i:j], \
        "loadCatalog 拿到 metric_meta 之后必须重渲染历史，否则并发下收益会是原始浮点"


def test_the_visible_text_carries_no_markdown_asterisks():
    """**页面上的文案里不许有 `**`。** `textContent`/HTML 都不解析 markdown。

    这条规则在仓库里已经写过，然后被违反**三次**（历史标题、超额收益口径说明、
    年度收益的说明都是 `**在窗口内**` 这种写法原样显示成星号）——
    因为"浏览器里长得不对"只有**看**才知道，静态契约测试当时查的是别的东西。

    判据：`index.html` 的文本节点（**剔除 HTML 注释**，注释里写给维护者的
    markdown 星号无妨）不含 `**`。服务端下发的文案由
    `test_the_metrics_table_and_the_curve_agree` 里那组断言守着。
    """
    import re

    html = (STATIC / "index.html").read_text(encoding="utf-8")
    visible = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert "**" not in visible, (
        "index.html 的可见文本里有 `**`：（会被原样显示成星号，不是粗体）\n"
        + "\n".join(line for line in visible.splitlines() if "**" in line)
    )


def test_the_metric_table_marks_the_cells_that_are_not_window_scoped():
    """**引擎面板口径的那几格必须打标记。**

    页头写着请求窗口，而 `engine_scoped` 里的几项（期末资金/总收益率/年化/夏普/
    最大回撤）是引擎按它自己的面板自报的。不打标记，用户会把它们读成窗口数字。
    后端早就把清单和文案都下发好了，界面却**一个消费者都没有** ——
    "看起来在把关、实际抓不到"的另一种形态：数据在、没人读。

    判据：指标格渲染读 `engine_scoped`，说明位渲染 `engine_scope_note`（文案来自服务端）。
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "engine_scoped" in js, "指标表没有读引擎口径标记"
    assert "engine_scope_note" in js, "口径说明没有从服务端取（前端自备一份必然漂移）"
    assert 'metrics-caveat' in js, "没有地方显示那句说明"


def test_the_poller_treats_every_terminal_status_as_terminal():
    """**轮询必须在这里停下来。** 每漏一个终态，那个 `setInterval` 就永远不会清掉。

    服务在运行中途重启过时，`/api/runs/{id}` 走磁盘回退还给 `unknown`
    （内存里没有这次作业、磁盘上也没有结局文件）——它**不会再变**。
    漏掉它，界面就永远停在旧状态上每秒打一次请求，**既不报错也不结束**：
    用户看到的是一个永远转不完的回测。

    判据取"终态集合要包含服务端磁盘回退会返回的每一个状态"：
    服务端那侧是 `done` / `failed` / `cancelled` / `unknown`。
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    fn = js[js.index("function pollRun()"):]
    fn = fn[:fn.index("async function cancelRun()")]
    lines = fn.splitlines()
    # 收集"由状态触发、且**随后真的** clearInterval"的那些分支的条件行。
    # 不看紧邻一行是刻意的：分支体允许换行/加注释，判据应当是"这个分支会停轮询"，
    # 而不是"这三个词出现在同一行"。
    guards = [
        line for i, line in enumerate(lines)
        if "j.status" in line
        and any("clearInterval(HP.poll)" in nxt for nxt in lines[i:i + 4])
    ]
    assert guards, "pollRun 里没有任何由**状态**终止轮询的分支"
    joined = " ".join(guards)
    for terminal in ("done", "failed", "cancelled", "unknown"):
        assert f'"{terminal}"' in joined, \
            f"终态 {terminal!r} 不在任何终止分支里 —— 它会让轮询永远不停：" \
            f"{[g.strip() for g in guards]}"


def test_the_compare_panel_flags_runs_that_are_not_comparable():
    """**窗口或模式不同的运行不可直接比较，而界面上必须说出来。**

    原实现把选中的运行并排列出，**既不显示各自覆盖的时段、也不警示** ——
    用户勾两次不同区间（或一次 preview + 一次 full）就会看到一张
    **静默地拿苹果比橘子**的表，而那些数看起来一样可信。

    设计文档的标准比聚宽更严：preview 的数字"不得作为业绩依据、不可与 full 比较"。
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "comparable" in js, "对比面板必须判断所选运行是否可比"
    assert "不可直接比较" in js, "不可比时必须在界面上明确说出来"
    # 每一列都要显示**它自己**的窗口 —— 否则用户看不出它们覆盖不同时段
    assert "x.start}~${x.end}" in js or "${x.start}~${x.end}" in js, \
        "列头要显示该次运行自己的窗口"
    # 文案里**不许写 markdown 星号** —— 这个页面用 textContent 渲染，星号会原样显示出来。
    # （本文件里已有同一条规矩，我在这个警告上又违反过一次。）
    import re

    for m in re.finditer(r'class="warn">([^`]{0,200}?)<', js):
        assert "**" not in m.group(1), f"警告文案里有 markdown 星号：{m.group(1)}"


def test_the_config_list_shows_the_preset_drift_badge():
    """**预设漂移必须在界面上如实显示**（不静默、也不阻断）。

    配置存的是"相对预设的一组改动"。**预设本身也会变** —— 那时"同一个配置"
    跑出来的参数已经不同了，而用户以为在复现。设计文档明文要求界面显示这一点。

    端到端实测过（2026-10-22）：存一个配置 → 把落盘指纹改掉 → 界面出现
    `⚠ 预设已变动` 并带一条说明。这条把那个渲染钉住。
    """
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "preset_drifted" in js, "前端必须处理 preset_drifted"
    assert "预设已变动" in js, "漂移时必须在界面上显示出来"
    # 不阻断：仍然可以载入/复制/删除 —— 漂移只是提示，不是错误
    i = js.index("preset_drifted")
    seg = js[i:i + 600]
    assert "drift" in seg, "漂移应当是一个独立的视觉标记"
