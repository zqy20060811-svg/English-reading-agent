"""开发用静态文件服务器：在 http.server 基础上追加 no-cache 响应头。

python -m http.server 不发送缓存控制头，浏览器会对 HTML 做启发式缓存，
前端页面更新后容易读到旧版本（表现为改动"不生效"）。本服务器对所有
响应追加 Cache-Control: no-cache，强制浏览器每次向服务器校验新鲜度。

用法：python -m app.scripts.serve_frontend [端口]（默认 8080）
"""
import http.server
import sys
from pathlib import Path

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
# 始终以 frontend/ 为站点根目录，与原启动方式保持一致
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    """每个响应都禁止缓存的静态文件处理器。"""

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


if __name__ == "__main__":
    import functools

    handler = functools.partial(NoCacheHandler, directory=str(FRONTEND_DIR))
    with http.server.ThreadingHTTPServer(("0.0.0.0", PORT), handler) as httpd:
        print(f"前端静态服务（no-cache）：http://localhost:{PORT}/  站点目录：{FRONTEND_DIR}")
        httpd.serve_forever()
