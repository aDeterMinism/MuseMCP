"""冒烟测试:stdio 连接 server.py,逐个调用工具。"""
import asyncio

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = "/home/z2g3/Documents/workSpace/创意 Muse/server.py"

params = StdioServerParameters(command=str(__import__("sys").executable), args=[SERVER])


async def main():
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("== tools:", [t.name for t in tools.tools])

            r = await s.call_tool("muse_seed", {"brief": "一岁一枯荣 的动画"})
            print("\n== muse_seed ==")
            print(r.content[0].text[:300])

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

            run_id = r.content[0].text  # placeholder; 用真实 id
            import re
            seed_text = (await s.call_tool("muse_seed", {"brief": "x"})).content[0].text
            rid = re.search(r"运行 ID: (\S+)", seed_text).group(1)
            r = await s.call_tool("muse_archive",
                                  {"run_id": rid,
                                   "report": "测试条目:keep——循环平稳结构方向幸存;kill——PPT 式寓言死因:隐喻过工整。"})
            print("\n== muse_archive ==")
            print(r.content[0].text)


asyncio.run(main())
