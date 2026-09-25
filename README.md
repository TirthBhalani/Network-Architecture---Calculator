# HTTP/1.1 Persistent Calculator Server

## Project Overview

We were tasked with building an HTTP/1.1 calculator server from scratch using raw sockets (no web frameworks allowed) : "Build a calculator that stays on the line".

The core challenge of this project was persistent connection handling. Unlike standard HTTP/1.0 servers that close the TCP connection after serving a single response (using EOF as the boundary), HTTP/1.1 keeps the socket open by default across multiple sequential requests. Because the connection stays alive, I had to ensure that the server explicitly parses headers, handles `Content-Length` bounds, and handles protocol edge cases cleanly without corrupting subsequent requests on the same stream.

---

## Features & Core Operations

I implemented the following arithmetic routes and HTTP behavior:

1. **`GET /add?a=2&b=3`** -> Returns HTTP status `200` with response body `5`.
2. **`GET /sub?a=10&b=4`** -> Returns HTTP status `200` with response body `6`.
3. **`GET /mul?a=6&b=7`** -> Returns HTTP status `200` with response body `42`.
4. **`GET /div?a=9&b=3`** -> Returns HTTP status `200` with response body `3`.

---

## Stretch Goals Implemented (All 4 Optional Goals Covered)

I implemented all four optional stretch goals :

1. **Honour `Connection: close`**:
   - I checked if the client sent `Connection: close` in the HTTP headers (or used HTTP/1.0 without keep-alive). When present, the server adds `Connection: close` to the response header and closes the TCP connection after writing the response.
2. **Idle Timeout You Can Defend**:
   - I configured a 15-second socket timeout (`timeout = 15`) on the socket server handler. If an open persistent socket stays idle for more than 15 seconds without receiving a new request, the server cleanly terminates the socket connection.
3. **Chunked Transfer Encoding**:
   - I added support for `Transfer-Encoding: chunked`. The server can parse incoming chunked bodies according to RFC 2616 section 3.6.1 (hex chunk sizes followed by CRLF and trailer `0`). It can also send chunked responses when `?chunked=1` is specified in the query parameters.
4. **HTTP/1.1 Pipelining (Take all six at once and answer in order)**:
   - I designed the request processing loop to handle concatenated HTTP requests received in a single TCP socket buffer write (`socket.sendall`). The server reads each request, computes the result, and writes responses back in the exact order requests were received without dropping the connection.

---

## Error Handling & Edge Cases

I covered all edge cases:

- **Division by zero (`GET /div?a=1&b=0`)**: Returns HTTP status `400 Bad Request`.
- **Invalid operand parameters (`GET /add?a=x&b=3`)**: String-to-float conversions are validated; non-numeric values return HTTP `400 Bad Request`.
- **Missing query parameters (`GET /add?a=2`)**: Validates that both `a` and `b` parameters exist.
- **Unsupported operation / unknown route (`GET /pow?a=2&b=8`)**: Returns HTTP `404 Not Found`.
- **Method not allowed (`POST /add`)**: Non-GET methods on supported endpoints return HTTP `405 Method Not Allowed`.
- **Missing `Host` header (`GET /add (no Host)`)**: According to RFC 2616, HTTP/1.1 requests without a `Host` header return HTTP `400 Bad Request`.

---

## Project Structure

- `server.py`: The HTTP/1.1 socket server implementation with persistent sockets and stretch goals.
- `test_server.py`: Automated test script verifying persistent sockets, HTTP pipelining, chunked encoding, and `Connection: close`.

---

## Running the Server and Tests

### 1. Start the Server
Run the server on default port 8080:
```bash
python server.py 8080
```

### 2. Run the Test Suite
In another terminal, run the automated test suite:
```bash
python test_server.py
```

All test cases verify that 1 TCP handshake handles all requests, pipelining, and stretch features over a persistent socket connection.
