import asyncio
import aiohttp
import sys
import logging

PROXY_URL = 'http://localhost:8080' 
BUFFER = 4096

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
logg = logging.getLogger(__name__)

async def create_session(session, host, port):
    async with session.post(f'{PROXY_URL}/', json={'host': host, 'port': port}) as resp:
        if resp.status == 200:
            session_id = (await resp.text()).strip()
            logg.info(f"Session created: {session_id}")
            return session_id
        else:
            logg.error(f"Failed to create session: {await resp.text()}")
            return None

async def send_data(session, session_id, data):
    async with session.put(f'{PROXY_URL}/{session_id}', data=data) as resp:
        return resp.status == 200

async def recv_data(session, session_id):
    async with session.get(f'{PROXY_URL}/{session_id}') as resp:
        if resp.status == 200:
            return await resp.read()
        return b''

async def close_session(session, session_id):
    try:
        await session.delete(f'{PROXY_URL}/{session_id}')
    except Exception:
        pass

async def handle_http_proxy_client(local_reader, local_writer, session):
    try:
        data = await local_reader.readuntil(b'\r\n\r\n')
    except Exception:
        local_writer.close()
        await local_writer.wait_closed()
        return
    header = data.decode(errors='ignore')
    lines = header.split('\r\n')
    is_connect = lines and lines[0].startswith('CONNECT')

    if is_connect:
        try:
            _, target, _ = lines[0].split()
            target_host, target_port = target.split(':')
            target_port = int(target_port)
        except Exception:
            logg.error('Invalid CONNECT request')
            local_writer.close()
            await local_writer.wait_closed()
            return
    else:
        target_host, target_port = None, 80
        for line in lines:
            if line.lower().startswith('host:'):
                host_line = line.split(':', 1)[1].strip()
                if ':' in host_line:
                    target_host, target_port = host_line.split(':')
                    target_port = int(target_port)
                else:
                    target_host = host_line
        if not target_host:
            logg.error('No Host header found in HTTP request')
            local_writer.close()
            await local_writer.wait_closed()
            return

    session_id = await create_session(session, target_host, target_port)
    if not session_id:
        local_writer.close()
        await local_writer.wait_closed()
        return

    if is_connect:
        local_writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        await local_writer.drain()
    else:
        ok = await send_data(session, session_id, data)
        if not ok:
            await close_session(session, session_id)
            local_writer.close()
            await local_writer.wait_closed()
            return

    async def recv_loop():
        try:
            while True:
                chunk = await recv_data(session, session_id)
                if chunk:
                    local_writer.write(chunk)
                    await local_writer.drain()
                else:
                    await asyncio.sleep(0.05)
        except Exception:
            pass
    recv_task = asyncio.create_task(recv_loop())
    try:
        while True:
            chunk = await local_reader.read(BUFFER)
            if not chunk:
                break
            ok = await send_data(session, session_id, chunk)
            if not ok:
                break
    except Exception:
        pass
    finally:
        await close_session(session, session_id)
        logg.info("Closing session %s", session_id)
        recv_task.cancel()
        local_writer.close()
        await local_writer.wait_closed()

async def main():
    if len(sys.argv) < 2:
        logg.error("Usage: python client.py <local_port>")
        sys.exit(1)
    local_port = int(sys.argv[1])
    logg.info(f"[+] HTTP proxy listening on 127.0.0.1:{local_port}, forwarding via proxy server.")
    async with aiohttp.ClientSession() as session:
        server = await asyncio.start_server(
            lambda r, w: handle_http_proxy_client(r, w, session),
            '0.0.0.0', local_port)
        async with server:
            await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
