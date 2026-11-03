# 3D 캠퍼스 테스트 서버
# 브라우저가 옛날 파일을 저장해 두고 쓰지 않도록(캐시 끄기) 항상 최신 파일을 보낸다.
# 실행: python serve.py  →  http://localhost:8123/?lite=1
import http.server
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8123


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


print(f"Serving HTTP on port {PORT} (http://localhost:{PORT}/?lite=1)", flush=True)
http.server.ThreadingHTTPServer(("", PORT), NoCacheHandler).serve_forever()
