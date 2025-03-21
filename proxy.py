import json
import socketserver
import socket
import base64
import logging

import requests

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(process)s] [%(levelname)s] %(message)s")
logg = logging.getLogger(__name__)

BUFFER = 1024 * 8  # 8KB size buffer
TUNNEL_URL = "http://192.168.0.110:8080"

class TunnelConnection:

    def __init__(self):
        self.session = requests.Session()
        self.session.verify = False
        self.id = None

    def get_channel_url(self):
        return f"{TUNNEL_URL}/{self.id if self.id else ''}"

    def create(self, host, port):
        logg.info("Creating connection to remote tunnel")
        headers = {"Content-Type": "application/json", "Accept": "text/plain"}
        try:
            data = {"host": host, "port": port}
            logg.info("Creating connection with settings: %s", data)
            response = self.session.post(url=self.get_channel_url(), data=json.dumps(data), headers=headers)
            if response.status_code == 200:
                self.id = response.content.decode('utf-8')
                logg.info('Successfully created connection: %s', self.id)
                return True
            logg.warning('Failed to establish connection: status %s because %s', response.status_code, response.reason)
            return False 
        except Exception as ex:
            logg.error("Error Creating Connection: %s", ex)
            return False

    def forward(self, data:bytes) -> bytes:
        if data:
            headers = {"Content-Type": "text/plain"}
            response = self.session.put(url=self.get_channel_url(), data=base64.b64encode(data).decode(), headers=headers)
            if response.status_code == 200:
                return base64.b64decode(response.content)
            else:
                logg.error("Failed to forward data to remote tunnel: %s", response.reason)
        return None

    def close(self):
        logg.info("Closing connection to target at remote tunnel")
        self.session.delete(self.get_channel_url())
        self.session.close()
 
class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass

class ProxyRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        client_ip, client_port = self.client_address
        logg.info(f"Connection received from {client_ip}:{client_port}")
        try:
            data = self.get_client_request()
            if not data:
                logg.warning(f"No data received from {client_ip}:{client_port}")
                return

            raw_request = data.decode('utf-8', errors='replace')
            logg.info(f"Raw request from {client_ip}:{client_port}: {raw_request.splitlines()[0]}")
            method, path, http_version = raw_request.split("\r\n")[0].split(" ")
            host_header = next((line for line in raw_request.split("\r\n") if line.lower().startswith("host:")), None)
            host, port = self.parse_host(host_header, method)

            if not host:
                logg.warning(f"Host header missing or invalid in request from {client_ip}:{client_port}")
                self.request.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                return

            remote_connection = TunnelConnection()
            if (not remote_connection.create(host, port)):
                logg.error(f"Create remote connection failed")
                return
            
            if method == "CONNECT":
                logg.info(f"Handling HTTPS tunneling for {host}:{port} from {client_ip}:{client_port}")
                self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            else:
                logg.info(f"Handling HTTP request for {host}:{port} from {client_ip}:{client_port}")
                remote_data = remote_connection.forward(data)
                self.request.sendall(remote_data)

            while(True):
                data = self.get_client_request()
                if not data:
                    logg.info("Connection closed during data relay")
                    return
                data_received = remote_connection.forward(data)
                self.request.sendall(data_received)

        except Exception as e:
            logg.error(f"Error handling request from {client_ip}:{client_port}: {e}")
        finally:
            remote_connection.close()

    def get_client_request(self) -> bytes:
        request = b''
        self.request.settimeout(2.0)  # Set a timeout of 5 seconds
        try:
            while True:
                data = self.request.recv(BUFFER)
                if not data:
                    logg.info("Connection closed during data relay")
                    break
                request += data
                if len(data) < BUFFER:
                    # If the received data is less than the buffer size, assume the request is complete
                    break
        except socket.timeout:
            logg.warning("Socket timed out while receiving data")
        except Exception as e:
            logg.error(f"Error while receiving data: {e}")

        return request

    def parse_host(self, host_header, method):
        if host_header:
            host = host_header.split(":", 1)[1].strip()
            if ":" in host:
                host, port = host.split(":")
                return host, int(port)
            return host, 443 if method == "CONNECT" else 80
        return None, None
    

if __name__ == "__main__":
    host, port = '0.0.0.0', 8080
    with ThreadedTCPServer((host, port), ProxyRequestHandler) as server:
        logg.info(f"Server started on {host}:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            logg.info("Server shutting down...")
