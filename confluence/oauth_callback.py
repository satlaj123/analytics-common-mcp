from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        if 'code' in query:
            code = query['code'][0]
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<h1>Authorization successful!</h1><p>You can close this window.</p>')
            print(f"AUTH_CODE={code}", flush=True)
            self.server.got_code = True
        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b'Waiting...')

    def log_message(self, format, *args):
        pass


server = HTTPServer(('localhost', 8080), CallbackHandler)
server.got_code = False
print("Waiting for OAuth callback on http://localhost:8080...", flush=True)
while not server.got_code:
    server.handle_request()
print("Done!", flush=True)
