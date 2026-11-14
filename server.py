#!/usr/bin/env python3
"""Muse MCP — 创作灵感服务器

角色分工(见 DESIGN.md):MCP 负责素材检索、信号工具与记忆;
发散与试炼由宿主会话完成。素材库就是本目录下的 library/ 文件夹。
"""
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parent
LIB = ROOT / "library"
INBOX = LIB / "inbox.md"
EARNED = LIB / "earned.md"
RUNS = ROOT / "runs"
WIKI_ZH = "https://zh.wikipedia.org/w/api.php"
UA = "MuseMCP/0.1 (personal creative tool)"

mcp = FastMCP(
    "muse",
    instructions=(
        "创作灵感 MCP。典型流程: muse_seed(命题) 拿到工作流指引 → muse_random 抽随机条目"
        "当信号 → muse_peek 展开感兴趣者 → muse_material_search 检索素材库 → "
        "主会话自己产出 n 张方向卡 → 起 n 个隔离智能体试炼 → muse_archive 归档。"
        "任何时刻可用 muse_park 随手寄存素材。"
    ),
)


# ---------- helpers ----------

def _wiki_api(params: dict) -> dict:
    params = {"format": "json", **params}
    url = WIKI_ZH + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read(1_000_000).decode("utf-8"))  # 响应体上限 1MB
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} {e.reason}") from e
    except Exception as e:
        raise RuntimeError(f"网络或解析失败:{e}") from e


def _ensure_dirs():
    LIB.mkdir(exist_ok=True)
    INBOX.touch(exist_ok=True)
    EARNED.touch(exist_ok=True)
    RUNS.mkdir(exist_ok=True)


def _append(path: Path, text: str):
    _ensure_dirs()
    with path.open("a", encoding="utf-8") as f:
        f.write(text.rstrip() + "\n\n")


# ---------- tools ----------

@mcp.tool()
def muse_seed(brief: str) -> str:
    """记录一个创作命题,开启一次运行。返回运行 ID 和试炼工作流指引。

    brief: 创作命题,如"一岁一枯荣 的动画"
    """
    brief = brief.strip()
    if not brief:
        return "(命题为空;给一句话命题)"
    if len(brief) > 2000:
        brief = brief[:2000] + "…(已截断)"
    _ensure_dirs()
    base = time.strftime("%Y%m%d-%H%M%S")
    suffix = 0
    while True:
        run_id = base if suffix == 0 else f"{base}-{suffix}"
        run_dir = RUNS / run_id
        try:
            run_dir.mkdir()  # mkdir 原子,失败即说明同秒已有运行(P1 修复)
            break
        except FileExistsError:
            suffix += 1
    (run_dir / "brief.md").write_text(
        f"# 命题\n\n{brief}\n", encoding="utf-8")
    guide = f"""运行 ID: {run_id}
命题已存入 runs/{run_id}/brief.md

试炼工作流指引(由你——主会话——执行,MCP 不参与发散与试炼):

1. 【信号】用 muse_random(n) 抽随机条目,扫标题,感兴趣的用 muse_peek 展开;
   也可注入其他当次信号(热搜、近期事件)。
2. 【发散】产出 n 张方向卡(5-8 张,覆盖至少 3 种信号类型),每张含:
   - idea: 一句话创意方向
   - signal: 风格 / 事件 / 结构 / 受众 / 私人素材(哪一类)
   - angle: 具体到本命题的切入
   - kill_hint: 它最可能死于什么
   卡片存入 runs/{run_id}/cards.md。
3. 【试炼】每个方向卡交给一个相互隔离的子智能体(各自独立工作区、
   禁止访问 muse MCP、互相看不到),每人产出报告:
   - verdict: keep / pivot / kill
   - concept: 若活着——logline、关键画面、与命题的契合点
   - kill: 是什么(或差点)杀死它——这条本身是素材
   - pivot: 若转向——转向成了什么
   报告汇总存入 runs/{run_id}/reports/。
4. 【归档】把幸存方案与有价值的否决理由交给 muse_archive。
"""
    return guide


@mcp.tool()
def muse_random(n: int = 5) -> str:
    """随机传送门:从维基百科抽 n 篇随机条目(仅标题)。

    用法:多抽、扫标题、只对有感觉的用 muse_peek 展开。
    信号往往在标题的名字、数字、地名里,不在正文里。
    """
    n = max(1, min(n, 20))
    try:
        data = _wiki_api({"action": "query", "list": "random",
                          "rnnamespace": 0, "rnlimit": n})
        titles = [p["title"] for p in data.get("query", {}).get("random", [])]
    except Exception as e:
        return f"(维基百科暂时不可用:{e};稍后重试或换信号源)"
    if not titles:
        return "(维基百科返回异常(无随机结果);稍后再试)"
    return "随机条目(只扫标题,有感觉再 peek):\n" + "\n".join(
        f"- {t}" for t in titles)


@mcp.tool()
def muse_peek(title: str) -> str:
    """展开一篇维基条目的正文简介。

    title: 条目标题(通常是 muse_random 抽到的)
    """
    try:
        data = _wiki_api({"action": "query", "prop": "extracts",
                          "explaintext": 1, "exintro": 1, "redirects": 1,
                          "titles": title})
        pages = data.get("query", {}).get("pages", {})
    except Exception as e:
        return f"(维基百科暂时不可用:{e})"
    for p in pages.values():
        if "extract" in p and p["extract"].strip():
            return p["extract"].strip()
    return f"(条目《{title}》没有可用的正文简介)"


@mcp.tool()
def muse_material_search(query: str) -> str:
    """检索素材库(library/ 下所有 .md 文件)。

    query: 关键词,按行匹配。返回命中行及其所在条目。
    空库返回空是正常行为:发散时扩大信号覆盖即可,不必卡住。
    """
    _ensure_dirs()
    query = query.strip()
    if not query:
        return "(空查询;给一个关键词)"
    if len(query) > 100:
        query = query[:100]
    hits = []
    for md in sorted(LIB.glob("*.md")):
        if md.stat().st_size > 1_000_000:
            continue  # 超大文件跳过,防返回内容爆炸
        lines = md.read_text(encoding="utf-8").splitlines()
        skip_until = -1
        for i, line in enumerate(lines):
            if i <= skip_until:
                continue
            if query.lower() in line.lower():
                entry = lines[max(0, i - 4): i + 2]
                hits.append(f"[{md.name}]\n" + "\n".join(entry))
                skip_until = i + 1  # 相邻命中合并为一条,不重复返回
    if not hits:
        return f"(素材库无《{query}》命中。空库不是阻塞——扩大信号覆盖继续发散。)"
    return "\n\n---\n\n".join(hits[:10])


@mcp.tool()
def muse_park(text: str, source: str = "") -> str:
    """无业务入库:把素材随手寄存进 library/inbox.md(标记待蒸馏),
    不依赖任何一次创作运行。

    text: 要寄存的内容(一段画面、一个词条、一个火花)
    source: 可选来源说明,如"维基随机条目:赤根智子"
    """
    text = text.strip()
    if not text:
        return "(空内容;给一段素材)"
    if len(text) > 20000:
        text = text[:20000] + "…(已截断)"
    source = (source or "").strip()[:200]
    ts = time.strftime("%Y-%m-%d %H:%M")
    head = f"## 寄存 {ts}" + (f"  (来源: {source})" if source else "")
    _append(INBOX, f"{head}\n\n{text}")
    return f"已寄存到 library/inbox.md 待蒸馏区。当前 inbox 共 {len(INBOX.read_text(encoding='utf-8'))} 字。"


@mcp.tool()
def muse_archive(run_id: str, report: str) -> str:
    """归档一次运行的成果:把幸存方案与有价值的否决理由蒸馏进
    library/earned.md(source: earned)。

    run_id: muse_seed 返回的运行 ID
    report: 蒸馏后的归档文本,建议每条含 idea + 死因/活因
    """
    if not re.fullmatch(r"\d{8}-\d{6}(-\d+)?", run_id):
        return f"(运行 ID 不合法:{run_id};请用 muse_seed 返回的 ID)"
    report = report.strip()
    if not report:
        return "(空报告;先跑完试炼再归档)"
    if len(report) > 50000:
        report = report[:50000] + "…(已截断)"
    run_dir = RUNS / run_id
    if not run_dir.is_dir():
        return f"(运行 {run_id} 不存在;先用 muse_seed)"
    if EARNED.exists() and f"## {run_id} " in EARNED.read_text(encoding="utf-8"):
        return f"(运行 {run_id} 已归档过;如需补充请手动编辑 library/earned.md)"
    ts = time.strftime("%Y-%m-%d %H:%M")
    _append(EARNED, f"## {run_id}  {ts}  (earned)\n\n{report}")
    return f"已归档 {run_id} 到 library/earned.md。"


if __name__ == "__main__":
    mcp.run()
