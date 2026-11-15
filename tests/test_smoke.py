"""冒烟测试:stdio 连接 server.py,逐个调用工具。"""
import asyncio
import re
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = "/home/z2g3/Documents/workSpace/创意 Muse/server.py"

params = StdioServerParameters(command=sys.executable, args=[SERVER])


async def main():
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("== tools:", [t.name for t in tools.tools])
            assert "muse_deal" in [t.name for t in tools.tools]

            r = await s.call_tool("muse_seed", {"brief": "一岁一枯荣 的动画"})
            seed_text = r.content[0].text
            print("\n== muse_seed ==")
            print(seed_text[:400])
            run_id = re.search(r"运行 ID: (\S+)", seed_text).group(1)

            # 发牌:返回值只含路径与模板,不得泄露牌面(标题/简介)
            r = await s.call_tool("muse_deal", {"run_id": run_id, "n": 3})
            deal_text = r.content[0].text
            print("\n== muse_deal ==")
            print(deal_text)
            assert "branch-1" in deal_text and "branch-3" in deal_text
            for path in [f"runs/{run_id}/branch-{k}" for k in (1, 2, 3)]:
                ref = open(f"{SERVER.rsplit('/', 1)[0]}/{path}/reference.md",
                           encoding="utf-8").read()
                assert "## 你的信号" in ref and "verdict" in ref, path

            # 幂等:重调不重发(返回内容一致)
            r2 = await s.call_tool("muse_deal", {"run_id": run_id, "n": 3})
            assert r2.content[0].text == deal_text
            print("\n== muse_deal 幂等 OK ==")

            r = await s.call_tool("muse_random", {"n": 3})
            print("\n== muse_random ==")
            print(r.content[0].text)

            r = await s.call_tool("muse_peek", {"title": "牛郎织女"})
            print("\n== muse_peek(牛郎织女) ==")
            print(r.content[0].text[:150], "...")

            r = await s.call_tool("muse_park",
                                  {"text": "测试寄存:一块被1911年探险队命名的南极岩石",
                                   "source": "冒烟测试"})
            print("\n== muse_park ==")
            print(r.content[0].text)

            r = await s.call_tool("muse_material_search", {"query": "岩石"})
            print("\n== muse_material_search(岩石) ==")
            print(r.content[0].text[:300])

            r = await s.call_tool("muse_archive",
                                  {"run_id": run_id,
                                   "report": "测试条目:keep——循环平稳结构方向幸存;"
                                             "kill——PPT 式寓言死因:隐喻过工整。"})
            print("\n== muse_archive ==")
            print(r.content[0].text)

            print("\n全部通过")


asyncio.run(main())
