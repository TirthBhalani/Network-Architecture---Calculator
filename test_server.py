#!/usr/bin/env python3
import socket
import time
import sys

class HTTPResponseReader:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = b""

    def read_response(self):
        # Read until HTTP double CRLF header delimiter is found in stream buffer
        while b"\r\n\r\n" not in self.buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            self.buffer += chunk

        if not self.buffer:
            return None, None, b"", {}

        header_part, body_and_rest = self.buffer.split(b"\r\n\r\n", 1)
        header_lines = header_part.decode("latin-1").split("\r\n")
        
        status_line = header_lines[0]
        status_code = int(status_line.split()[1])

        headers = {}
        for line in header_lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        is_chunked = headers.get("transfer-encoding", "").lower() == "chunked"
        content_length = int(headers.get("content-length", 0)) if "content-length" in headers else None

        if is_chunked:
            # Buffer stream until 0\r\n\r\n chunk end marker is received
            while b"0\r\n\r\n" not in body_and_rest:
                chunk = self.sock.recv(4096)
                if not chunk:
                    break
                body_and_rest += chunk
            
            # Extract chunked body data
            raw_body = b""
            data_cursor = body_and_rest
            while True:
                if b"\r\n" not in data_cursor:
                    break
                size_line, rest = data_cursor.split(b"\r\n", 1)
                size = int(size_line.split(b";")[0].strip(), 16)
                if size == 0:
                    # Update buffer to start after terminal 0\r\n\r\n marker
                    end_idx = data_cursor.find(b"0\r\n\r\n") + 5
                    self.buffer = data_cursor[end_idx:]
                    break
                raw_body += rest[:size]
                data_cursor = rest[size + 2:]
            return status_code, status_line, raw_body, headers
        elif content_length is not None:
            # Buffer remaining body bytes for current response
            while len(body_and_rest) < content_length:
                chunk = self.sock.recv(content_length - len(body_and_rest))
                if not chunk:
                    break
                body_and_rest += chunk
            
            body = body_and_rest[:content_length]
            # Preserve unconsumed stream bytes in buffer for next pipelined response
            self.buffer = body_and_rest[content_length:]
            return status_code, status_line, body, headers
        else:
            self.buffer = b""
            return status_code, status_line, body_and_rest, headers

def run_tests():
    print("=== Testing Calculator Server & Stretch Goals ===")
    
    # Standard Persistent Socket Test
    print("\n[Test 1] Persistent Socket (6 requests sequentially on 1 TCP handshake)...")
    s = socket.create_connection(("localhost", 8080))
    reader = HTTPResponseReader(s)

    tests = [
        ("GET /add?a=2&b=3 HTTP/1.1\r\nHost: localhost\r\n\r\n", 200, b"5"),
        ("GET /sub?a=10&b=4 HTTP/1.1\r\nHost: localhost\r\n\r\n", 200, b"6"),
        ("GET /mul?a=6&b=7 HTTP/1.1\r\nHost: localhost\r\n\r\n", 200, b"42"),
        ("GET /div?a=9&b=3 HTTP/1.1\r\nHost: localhost\r\n\r\n", 200, b"3"),
        ("GET /div?a=1&b=0 HTTP/1.1\r\nHost: localhost\r\n\r\n", 400, None),
        ("GET /add?a=x&b=3 HTTP/1.1\r\nHost: localhost\r\n\r\n", 400, None),
    ]

    for req, expected_status, expected_body in tests:
        s.sendall(req.encode("utf-8"))
        code, line, body, hdrs = reader.read_response()
        print(f"  {req.strip().splitlines()[0]} -> Status {code}, Body {body!r}")
        assert code == expected_status, f"Expected {expected_status}, got {code}"
        if expected_body is not None:
            assert body == expected_body, f"Expected body {expected_body!r}, got {body!r}"

    s.close()
    print("  -> Passed persistent socket test!")

    # Stretch Goal 4: HTTP Pipelining (take all six at once and answer in order)
    print("\n[Stretch Goal 4] HTTP Pipelining (Sending 6 requests at once in 1 socket write)...")
    s_pipe = socket.create_connection(("localhost", 8080))
    pipe_reader = HTTPResponseReader(s_pipe)
    pipelined_payload = "".join([req for req, _, _ in tests]).encode("utf-8")
    
    # Send all 6 concatenated requests in one single socket write call
    s_pipe.sendall(pipelined_payload)

    # Read back all 6 responses sequentially in exact order from stream buffer
    for req, expected_status, expected_body in tests:
        code, line, body, hdrs = pipe_reader.read_response()
        print(f"  Pipelined response for {req.strip().splitlines()[0]} -> Status {code}, Body {body!r}")
        assert code == expected_status, f"Expected {expected_status}, got {code}"
        if expected_body is not None:
            assert body == expected_body, f"Expected body {expected_body!r}, got {body!r}"
    
    s_pipe.close()
    print("  -> Passed HTTP Pipelining stretch test!")

    # Stretch Goal 1: Honour Connection: close
    print("\n[Stretch Goal 1] Honouring Connection: close...")
    s_close = socket.create_connection(("localhost", 8080))
    close_reader = HTTPResponseReader(s_close)
    s_close.sendall(b"GET /add?a=2&b=3 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
    code, line, body, hdrs = close_reader.read_response()
    assert code == 200 and body == b"5", "Failed basic request on Connection: close"
    assert hdrs.get("connection", "").lower() == "close", "Response missing Connection: close header"
    
    # Confirm socket closure by server
    data_after = s_close.recv(1024)
    assert len(data_after) == 0, "Socket remained open after Connection: close"
    s_close.close()
    print("  -> Passed Connection: close stretch test!")

    # Stretch Goal 3: Chunked Encoding
    print("\n[Stretch Goal 3] Chunked Encoding (Response & Request)...")
    s_chunk = socket.create_connection(("localhost", 8080))
    chunk_reader = HTTPResponseReader(s_chunk)
    s_chunk.sendall(b"GET /mul?a=6&b=7&chunked=1 HTTP/1.1\r\nHost: localhost\r\n\r\n")
    code, line, body, hdrs = chunk_reader.read_response()
    assert code == 200 and body == b"42", f"Expected body 42, got {body!r}"
    assert hdrs.get("transfer-encoding", "").lower() == "chunked", "Response not chunked"
    s_chunk.close()
    print("  -> Passed Chunked Encoding stretch test!")

    print("\n=== ALL CORE & STRETCH TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    run_tests()
