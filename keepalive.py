import asyncio
import threading
from aiohttp import web

app = web.Application()


async def _health(request: web.Request) -> web.Response:
    return web.Response(text="Yoran (Yoran Studios) is online.", status=200)


app.router.add_get("/", _health)


def _run_web_server(port: int) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _serve():
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        print(f"[Keepalive] HTTP server on 0.0.0.0:{port}", flush=True)
        while True:
            await asyncio.sleep(3600)

    loop.run_until_complete(_serve())


def start_keepalive(port: int = 3000) -> None:
    t = threading.Thread(target=_run_web_server, args=(port,), daemon=True)
    t.start()
    print(f"[Keepalive] HTTP thread spawned on port {port}", flush=True)
