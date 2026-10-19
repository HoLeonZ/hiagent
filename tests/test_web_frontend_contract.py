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
    assert "fmtMetric" in js, "指标必须走按 kind 分支的格式化函数"
    assert "toFixed(4)" not in js, "不得对指标用固定四位小数，应按 kind 渲染"
