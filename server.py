#!/usr/bin/env python3
import socketserver
import sys
from urllib.parse import urlparse, parse_qs

# Standard HTTP status reason phrases for response headers
STATUS_REASONS = {
    200: "OK",
    400: "Bad Request",
    404: "Not Found",
    405: "Method Not Allowed",
    500: "Internal Server Error"
}

class CalculatorHandler(socketserver.StreamRequestHandler):
    # Stretch Goal: Defendable idle timeout (15s) so persistent sockets don't hang indefinitely
    timeout = 15

    def handle(self):
        # Process requests in a loop over the persistent TCP socket connection.
        # Handles HTTP/1.1 pipelining naturally by processing buffered stream requests in order.
        while True:
            try:
                should_close = self.handle_one_request()
                if should_close:
                    break
            except (socketserver.socket.timeout, TimeoutError):
                # Idle connection timed out cleanly
                break
            except (ConnectionResetError, BrokenPipeError):
                # Socket disconnected by client
                break

    def read_chunked_body(self):
        # Stretch Goal: Parse HTTP chunked transfer encoding (RFC 2616 section 3.6.1)
        body = b""
        while True:
            line = self.rfile.readline(8192)
            if not line:
                break
            hex_size = line.split(b";")[0].strip()
            if not hex_size:
                continue
            try:
                chunk_len = int(hex_size, 16)
            except ValueError:
                break
            if chunk_len == 0:
                # Read trailing empty line after zero chunk
                self.rfile.readline(8192)
                break
            chunk_data = self.rfile.read(chunk_len)
            body += chunk_data
            # Read CRLF after chunk payload
            self.rfile.readline(8192)
        return body

    def handle_one_request(self):
        # Read primary request line from incoming socket stream
        request_line = self.rfile.readline(8192)
        if not request_line:
            # Socket EOF / client disconnect
            return True

        decoded_line = request_line.decode("latin-1").strip()
        if not decoded_line:
            return False

        # Parse method, path target, and HTTP version string
        parts = decoded_line.split()
        if len(parts) != 3:
            self.send_response(400, b"400 Bad Request\n", close=True)
            return True

        method, target, version = parts

        # Parse HTTP header lines until empty CRLF separator
        headers = {}
        while True:
            header_line = self.rfile.readline(8192).decode("latin-1")
            header_line_stripped = header_line.strip()
            if not header_line_stripped:
                break
            if ":" in header_line_stripped:
                key, value = header_line_stripped.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        # Enforce HTTP/1.1 compulsory Host header requirement (RFC 2616 s.14.23)
        if version == "HTTP/1.1" and "host" not in headers:
            self.send_response(400, b"Missing Host header\n", close=True)
            return True

        # Consume request body bytes based on Content-Length or chunked encoding
        # Ensures byte n+1 remains untouched for subsequent persistent requests
        transfer_encoding = headers.get("transfer-encoding", "").lower()
        if "chunked" in transfer_encoding:
            _ = self.read_chunked_body()
        elif "content-length" in headers:
            try:
                content_len = int(headers["content-length"])
                _ = self.rfile.read(content_len)
            except ValueError:
                self.send_response(400, b"Invalid Content-Length\n", close=True)
                return True

        # Stretch Goal: Honour Connection: close request header
        conn_header = headers.get("connection", "").lower()
        close_connection = ("close" in conn_header) or (version == "HTTP/1.0" and "keep-alive" not in conn_header)

        parsed_url = urlparse(target)
        query_params = parse_qs(parsed_url.query)
        path = parsed_url.path

        # Check for chunked response output parameter (?chunked=1)
        send_chunked = "chunked" in query_params and query_params["chunked"][0] == "1"

        supported_routes = ["/add", "/sub", "/mul", "/div"]

        # Validate HTTP method against allowed operations
        if method != "GET":
            if path in supported_routes:
                self.send_response(405, b"405 Method Not Allowed\n", close=close_connection)
            else:
                self.send_response(404, b"404 Not Found\n", close=close_connection)
            return close_connection

        if path not in supported_routes:
            self.send_response(404, b"404 Not Found\n", close=close_connection)
            return close_connection

        # Validate query parameters 'a' and 'b'
        if "a" not in query_params or "b" not in query_params:
            self.send_response(400, b"Missing query parameters\n", close=close_connection)
            return close_connection

        try:
            val_a = float(query_params["a"][0])
            val_b = float(query_params["b"][0])
        except ValueError:
            self.send_response(400, b"Invalid number format\n", close=close_connection)
            return close_connection

        # Execute arithmetic operation based on request path
        try:
            if path == "/add":
                res = val_a + val_b
            elif path == "/sub":
                res = val_a - val_b
            elif path == "/mul":
                res = val_a * val_b
            elif path == "/div":
                if val_b == 0:
                    self.send_response(400, b"Division by zero\n", close=close_connection)
                    return close_connection
                res = val_a / val_b
        except Exception:
            self.send_response(500, b"Server Error\n", close=close_connection)
            return close_connection

        # Format integer results cleanly without trailing decimals
        if res.is_integer():
            body_str = str(int(res))
        else:
            body_str = str(res)

        self.send_response(200, body_str.encode("utf-8"), close=close_connection, chunked=send_chunked)
        return close_connection

    def send_response(self, status_code, body_bytes, close=False, chunked=False):
        # Compose headers and body, sending in a single atomic socket write call
        reason = STATUS_REASONS.get(status_code, "Unknown")
        conn_header_val = "close" if close else "keep-alive"

        headers = [
            f"HTTP/1.1 {status_code} {reason}",
            "Content-Type: text/plain"
        ]

        if chunked:
            headers.append("Transfer-Encoding: chunked")
        else:
            headers.append(f"Content-Length: {len(body_bytes)}")

        headers.append(f"Connection: {conn_header_val}")
        if not close:
            headers.append("Keep-Alive: timeout=15, max=100")

        head_bytes = ("\r\n".join(headers) + "\r\n\r\n").encode("utf-8")
        out = head_bytes

        if chunked:
            if len(body_bytes) > 0:
                out += f"{len(body_bytes):X}\r\n".encode("utf-8") + body_bytes + b"\r\n"
            out += b"0\r\n\r\n"
        else:
            out += body_bytes

        self.wfile.write(out)
        self.wfile.flush()

class ReusableThreadingServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    print(f"Starting calculator HTTP server on port {port}...")
    server = ReusableThreadingServer(("0.0.0.0", port), CalculatorHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        server.server_close()
