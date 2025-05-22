#!/usr/bin/env python
import asyncio
import uuid
from aiohttp import web
from aiohttp.typedefs import Handler
import argparse
import logging

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(process)s] [%(levelname)s] %(message)s")
logg = logging.getLogger(__name__)

sockets = {}

class ProxyRequestHandler:
    async def do_GET(self, request):
        """GET: Read data from TargetAddress and return to client through http response"""
        id = request.match_info.get('id')
        if id == "health":
            return web.Response(status=200)
        if id in sockets:
            reader, _ = sockets[id]
            try:
                data = await reader.read(4096) 
                if data:
                    return web.Response(body=data, content_type='application/octet-stream')
                return web.Response(status=204)
            except Exception as e:
                logg.error(f"GET error: {e}")
                return web.json_response({"error": str(e)}, status=500)
        logg.info('%s not found' % id)
        return web.json_response({"error": "Resource not found"}, status=404)

    async def do_POST(self, request):
        data = await request.json()
        if "host" in data and "port" in data:
            id = str(uuid.uuid4())
            target_host = data["host"]
            target_port = int(data["port"])
            logg.info('Connecting to target address: %s %s' % (target_host, target_port))
            try:
                reader, writer = await asyncio.open_connection(target_host, target_port)
                sockets[id] = (reader, writer)
                return web.Response(text=id)
            except Exception as e:
                logg.error(f"POST error: {e}")
                return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"error": "Resource not found"}, status=404)

    async def do_PUT(self, request):
        id = request.match_info.get('id')
        if id in sockets:
            _, writer = sockets[id]
            try:
                data = await request.content.read()
                writer.write(data)
                await writer.drain()
                return web.Response(status=200)
            except Exception as e:
                logg.error(f"PUT error: {e}")
                return web.json_response({"error": str(e)}, status=500)
        return web.json_response({"error": "Resource not found"}, status=404)

    async def do_DELETE(self, request):
        id = request.match_info.get('id')
        if id in sockets:
            _, writer = sockets[id]
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                logg.error(f"DELETE error: {e}")
            del sockets[id]
            return web.json_response({"message": "Session deleted", "session": id})
        return web.json_response({"error": "Session not found"}, status=404)

handler = ProxyRequestHandler()

@web.middleware
async def middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        response = exc
    if not response.prepared:
        response.headers["SERVER"] = "cloudflare"
    return response

app = web.Application(middlewares=[middleware])
app.router.add_get('/{id}', handler.do_GET)
app.router.add_post('/', handler.do_POST)
app.router.add_put('/{id}', handler.do_PUT)
app.router.add_delete('/{id}', handler.do_DELETE)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start Proxy Server")
    parser.add_argument("-p", default=8080, dest='port', help='Specify port number server will listen to', type=int)
    args = parser.parse_args()
    logg.info("Starting server on port %s" % args.port)
    web.run_app(app, host='0.0.0.0', port=args.port)
