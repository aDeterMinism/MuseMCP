#!/usr/bin/env python3
"""Muse MCP — 创作灵感服务器

角色分工(见 DESIGN.md):MCP 负责素材检索、信号工具与记忆;
发散与试炼由宿主会话完成。素材库就是本目录下的 library/ 文件夹。
"""
import json
import random
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

# 切入视角轮转池:保证一次运行的 n 个分支覆盖多种视角(DESIGN.md 的"≥3 种信号类型")
DEAL_TYPES = ["结构", "叙事原型", "风格", "事件", "受众", "感官材质", "媒介手法"]

# 主会话拉起子智能体的固定模板(prompt 只换 {k} 与 {path} 两个变量)
SPAWN_TEMPLATE = """你是分支 {k}。工作区:{path}。
第一步:Read {path}/reference.md,里面有命题、你的信号和工作规则。
禁止访问 muse MCP 的任何工具;禁止读取工作区以外的任何项目文件。
产出:Write {path}/report.md,格式见 reference.md 末尾。"""

# 试炼报告模板(写进每个分支的 reference.md 末尾)
REPORT_TEMPLATE = """verdict: keep / pivot / kill
concept: 若活着——logline、关键画面、与命题的契合点
kill:   是什么(或差点)杀死它——这条本身是素材
pivot:  若转向——转向成了什么"""

mcp = FastMCP(
    "muse",
    instructions=(
        "创作灵感 MCP。典型流程: muse_seed(命题) 开运行 → muse_deal 确定性发牌、"
        "建 n 个分支工作区(参考内容直接落盘,主会话不见牌面) → "
        "主会话按发牌返回的模板机械地起 n 个隔离智能体试炼 → 汇总报告 → muse_archive 归档。"
        "任何时刻可用 muse_park 随手寄存素材;muse_random / muse_peek 可作临时信号。"
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


def _wiki_extract(title: str) -> str:
    """取条目简介,失败静默返回空串(发牌不能因单条网络错误中断)。"""
    try:
        data = _wiki_api({"action": "query", "prop": "extracts",
                          "explaintext": 1, "exintro": 1, "redirects": 1,
                          "titles": title})
        for p in data.get("query", {}).get("pages", {}).values():
            if p.get("extract", "").strip():
                return p["extract"].strip()
    except Exception:
        pass
    return ""


def _read_brief(run_dir: Path) -> str:
    """从 brief.md 取命题正文(去掉标题行)。"""
    try:
        lines = (run_dir / "brief.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return "(命题缺失)"
    body = [l for l in lines if l.strip() and not l.startswith("# ")]
    return "\n".join(body).strip() or "(命题缺失)"


def _reference_md(k: int, brief: str, title: str, extract: str, kind: str) -> str:
    sig = f"维基随机条目:《{title}》"
    if extract:
        sig += f"\n\n{extract}"
    else:
        sig += "\n\n(该条目没有正文简介;没关系——信号在标题的名字、数字、地名里,直接从标题出发。)"
    return f"""# 分支 {k} 参考材料

## 命题

{brief}

## 你的信号

{sig}

## 切入视角(建议;可偏离,但偏离要有理由)

{kind}——从这个视角把信号发展成一个具体方向。
经验:信号往往在名字、数字、地名的低层,不在条目正文里。别被简介带跑。

## 工作规则

1. 一切读写限制在本目录;禁止访问 muse MCP 的任何工具;禁止读取其他分支目录。
2. 先发展:把信号和命题推成一个具体方案(logline、关键画面)。
3. 再审判:诚实地攻击它,写清楚是什么(或差点)杀死它。
4. 报告写为本目录下的 report.md:

```
{REPORT_TEMPLATE}
```
"""


def _deal_reply(run_id: str, n: int) -> str:
    run_dir = RUNS / run_id  # 绝对路径:主会话 cwd 与服务器 ROOT 不同,相对路径会被按 cwd 解释
    paths = "\n".join(f"- {run_dir / f'branch-{k}'}" for k in range(1, n + 1))
    return f"""已发牌:运行 {run_id},共 {n} 个分支(重调幂等,不会重发)。

工作区(绝对路径,与主会话 cwd 无关;牌面已落盘到各自 reference.md。不要读它们——你先看了再转述,就把你的锚定带给了子代理):

{paths}

拉起模板(每个分支一次 Agent 调用,同一条消息里并行发出;prompt 只换 {{k}} 与 {{path}}):

```
{SPAWN_TEMPLATE}
```

n 份 report.md 齐了之后:读 {run_dir}/branch-*/report.md 排名汇总,再 muse_archive。"""


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
命题已存入 {run_dir / 'brief.md'}

试炼工作流指引(由你——主会话——执行;MCP 负责发牌与记忆,试炼由隔离子智能体做):

1. 【发牌】调用 muse_deal("{run_id}", n),n 取 5-8。MCP 会确定性抽信号、
   建 n 个分支工作区并把参考内容写进各自 reference.md。返回值只有路径,
   牌面你不要看——你先读了再转述,就把你的锚定带给了子代理。
2. 【试炼】按 muse_deal 返回的拉起模板,每个分支起一个隔离子智能体,
   同一条消息里并行发出;prompt 只含分支号与工作区路径,
   不含你对信号的任何解读。各分支自己产出 report.md。
3. 【编辑】读完 {run_dir}/branch-*/report.md,排名并给出最终汇报。
4. 【归档】把幸存方案与有价值的否决理由交给 muse_archive。
"""
    return guide


@mcp.tool()
def muse_deal(run_id: str, n: int = 5) -> str:
    """确定性发牌:为一次运行建 n 个分支工作区,给每分支分配一个
    维基随机信号,参考内容直接写进该分支的 reference.md。

    用 run_id 作种子,分支 k 拿到什么完全由 (run_id, k) 决定;
    返回值只含目录路径与拉起模板,不含牌面(主会话不接触信号内容)。
    幂等:同一运行重复调用返回已发出的牌,不重发。

    run_id: muse_seed 返回的运行 ID
    n: 分支数(5-8)
    """
    if not re.fullmatch(r"\d{8}-\d{6}(-\d+)?", run_id):
        return f"(运行 ID 不合法:{run_id};请用 muse_seed 返回的 ID)"
    n = max(1, min(n, 8))
    run_dir = RUNS / run_id
    if not run_dir.is_dir():
        return f"(运行 {run_id} 不存在;先用 muse_seed)"

    deal_file = run_dir / "deal.json"
    if deal_file.exists():  # 幂等:已发过牌,只回路径
        try:
            deal = json.loads(deal_file.read_text(encoding="utf-8"))
            return _deal_reply(run_id, len(deal["branches"]))
        except Exception:
            pass  # deal.json 损坏则重发覆盖

    # 1) 抽候选:多抽一倍,种子化洗牌后取前 n 个(分配过程零模型参与)
    try:
        data = _wiki_api({"action": "query", "list": "random",
                          "rnnamespace": 0, "rnlimit": min(max(n * 2, 10), 20)})
        pool = [p["title"] for p in data.get("query", {}).get("random", [])]
    except Exception as e:
        return f"(维基百科暂时不可用:{e};稍后重试发牌)"
    pool = list(dict.fromkeys(pool))  # 去重,保序
    if not pool:
        return "(维基百科返回异常(无随机结果);稍后重试发牌)"
    rng = random.Random(run_id)  # 种子 = run_id,分配可复现、可审计
    rng.shuffle(pool)
    picks = pool[:n]

    # 2) 覆盖保证:视角从轮转池里种子化排序分配
    kinds = DEAL_TYPES[:]
    rng.shuffle(kinds)

    # 3) 建工作区、落盘参考内容(逐分支容错:单条简介抓不到不影响发牌)
    brief = _read_brief(run_dir)
    branches = []
    for k, title in enumerate(picks, start=1):
        d = run_dir / f"branch-{k}"
        d.mkdir(exist_ok=True)
        (d / "reference.md").write_text(
            _reference_md(k, brief, title, _wiki_extract(title), kinds[(k - 1) % len(kinds)]),
            encoding="utf-8")
        branches.append({"k": k, "dir": f"branch-{k}", "title": title,
                         "kind": kinds[(k - 1) % len(kinds)]})

    # 4) 审计留痕:牌面只进 deal.json(在磁盘上,不在主会话上下文里)
    deal_file.write_text(json.dumps(
        {"run_id": run_id, "seed": run_id, "n": n, "branches": branches},
        ensure_ascii=False, indent=2), encoding="utf-8")
    return _deal_reply(run_id, n)


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
