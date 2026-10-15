import os
import sys
import json
import urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import webbrowser
import socket
import threading
import subprocess
import tempfile
import uuid
import zipfile

SYSTEM_DIR = os.path.dirname(os.path.abspath(__file__))
if os.path.exists(os.path.join(os.path.dirname(SYSTEM_DIR), "中英合并释义_JSON")):
    DATA_DIR = os.path.join(os.path.dirname(SYSTEM_DIR), "中英合并释义_JSON")
elif os.path.exists(os.path.join(SYSTEM_DIR, "中英合并释义_JSON")):
    DATA_DIR = os.path.join(SYSTEM_DIR, "中英合并释义_JSON")
else:
    DATA_DIR = os.path.join(os.path.dirname(SYSTEM_DIR), "中英合并释义_JSON")

def find_browser_path():
    candidates = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        os.path.expanduser(r"~\AppData\Local\Microsoft\Edge\Application\msedge.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expanduser(r"~\AppData\Local\Google\Chrome\Application\chrome.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    return None

class VocabularyPrintServer(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=SYSTEM_DIR, **kwargs)

    def log_message(self, format, *args):
        # Clean console log
        sys.stdout.write(f"[{self.log_date_time_string()}] {format % args}\n")
        sys.stdout.flush()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Connection", "close")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        if path == "/api/catalog":
            cat_path = os.path.join(SYSTEM_DIR, "catalog.json")
            if os.path.exists(cat_path):
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Connection", "close")
                self.end_headers()
                with open(cat_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "Catalog not found")
            return

        elif path == "/api/book":
            rel_path = query.get("path", [""])[0]
            if not rel_path:
                self.send_error(400, "Missing path param")
                return
            
            safe_rel = urllib.parse.unquote(rel_path).replace("/", os.sep).replace("\\", os.sep).lstrip(os.sep)
            file_path = os.path.abspath(os.path.join(DATA_DIR, safe_rel))
            data_dir_abs = os.path.abspath(DATA_DIR)
            
            # 严格防止路径遍历攻击 (Path Traversal Protection)
            if not file_path.startswith(data_dir_abs):
                self.send_error(403, "Access denied")
                return

            if os.path.exists(file_path) and file_path.endswith(".json"):
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Connection", "close")
                self.end_headers()
                with open(file_path, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "Book file not found")
            return

        elif path == "/" or path == "":
            self.send_response(302)
            self.send_header("Location", "/index.html")
            self.send_header("Connection", "close")
            self.end_headers()
            return

        super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/export-pdf":
            temp_html_path = None
            temp_pdf_path = None
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length)
                payload = json.loads(post_data.decode("utf-8"))
                
                html_content = payload.get("html", "")
                raw_filename = payload.get("filename", "vocabulary_book.pdf")
                if not raw_filename.endswith(".pdf"):
                    raw_filename += ".pdf"

                browser_path = find_browser_path()
                if not browser_path:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "未找到 Edge 或 Chrome 浏览器程序"}).encode("utf-8"))
                    return

                temp_dir = tempfile.gettempdir()
                uid = uuid.uuid4().hex[:8]
                temp_html_path = os.path.abspath(os.path.join(temp_dir, f"vocab_export_{uid}.html"))
                temp_pdf_path = os.path.abspath(os.path.join(temp_dir, f"vocab_export_{uid}.pdf"))

                with open(temp_html_path, "w", encoding="utf-8") as f:
                    f.write(html_content)

                file_url = "file:///" + temp_html_path.replace("\\", "/")
                cmd = [
                    browser_path,
                    "--headless",
                    "--disable-gpu",
                    "--disable-software-rasterizer",
                    "--hide-scrollbars",
                    "--no-pdf-header-footer",
                    f"--print-to-pdf={temp_pdf_path}",
                    file_url
                ]

                run_res = subprocess.run(cmd, capture_output=True, timeout=120)

                if os.path.exists(temp_pdf_path) and os.path.getsize(temp_pdf_path) > 0:
                    with open(temp_pdf_path, "rb") as f:
                        pdf_bytes = f.read()

                    quoted_filename = urllib.parse.quote(raw_filename.encode("utf-8"))
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted_filename}")
                    self.send_header("Content-Length", str(len(pdf_bytes)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(pdf_bytes)
                else:
                    err_msg = run_res.stderr.decode("utf-8", errors="ignore") if run_res.stderr else "生成 PDF 失败"
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": err_msg}).encode("utf-8"))

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            finally:
                if temp_html_path and os.path.exists(temp_html_path):
                    try:
                        os.remove(temp_html_path)
                    except Exception:
                        pass
                if temp_pdf_path and os.path.exists(temp_pdf_path):
                    try:
                        os.remove(temp_pdf_path)
                    except Exception:
                        pass
            return

        elif parsed.path == "/api/export-volumes-zip":
            temp_files_to_clean = []
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                post_data = self.rfile.read(content_length)
                payload = json.loads(post_data.decode("utf-8"))

                volumes = payload.get("volumes", [])
                zip_filename = payload.get("zipFilename", "vocabulary_volumes.zip")
                export_format = payload.get("format", "pdf")

                if not zip_filename.endswith(".zip"):
                    zip_filename += ".zip"

                if not volumes:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "未提供有效分卷数据"}).encode("utf-8"))
                    return

                browser_path = find_browser_path() if export_format == "pdf" else None
                if export_format == "pdf" and not browser_path:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "未找到 Edge 或 Chrome 浏览器程序"}).encode("utf-8"))
                    return

                temp_dir = tempfile.gettempdir()
                uid = uuid.uuid4().hex[:8]
                temp_zip_path = os.path.abspath(os.path.join(temp_dir, f"vocab_volumes_{uid}.zip"))
                temp_files_to_clean.append(temp_zip_path)

                with zipfile.ZipFile(temp_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
                    for idx, vol in enumerate(volumes):
                        vol_filename = vol.get("filename", f"volume_{idx+1}")
                        html_content = vol.get("html", "")

                        if export_format == "html":
                            if not vol_filename.endswith(".html"):
                                vol_filename += ".html"
                            zf.writestr(vol_filename, html_content.encode("utf-8"))
                        else:
                            # PDF export
                            if not vol_filename.endswith(".pdf"):
                                vol_filename += ".pdf"
                            vol_uid = f"{uid}_{idx+1}"
                            v_html_path = os.path.abspath(os.path.join(temp_dir, f"v_html_{vol_uid}.html"))
                            v_pdf_path = os.path.abspath(os.path.join(temp_dir, f"v_pdf_{vol_uid}.pdf"))
                            temp_files_to_clean.extend([v_html_path, v_pdf_path])

                            with open(v_html_path, "w", encoding="utf-8") as vf:
                                vf.write(html_content)

                            file_url = "file:///" + v_html_path.replace("\\", "/")
                            cmd = [
                                browser_path,
                                "--headless",
                                "--disable-gpu",
                                "--disable-software-rasterizer",
                                "--hide-scrollbars",
                                "--no-pdf-header-footer",
                                f"--print-to-pdf={v_pdf_path}",
                                file_url
                            ]
                            subprocess.run(cmd, capture_output=True, timeout=120)

                            if os.path.exists(v_pdf_path) and os.path.getsize(v_pdf_path) > 0:
                                zf.write(v_pdf_path, arcname=vol_filename)
                            else:
                                fallback_html_name = vol_filename.replace(".pdf", ".html")
                                zf.writestr(fallback_html_name, html_content.encode("utf-8"))

                if os.path.exists(temp_zip_path) and os.path.getsize(temp_zip_path) > 0:
                    with open(temp_zip_path, "rb") as zf_read:
                        zip_bytes = zf_read.read()

                    quoted_zip_name = urllib.parse.quote(zip_filename.encode("utf-8"))
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quoted_zip_name}")
                    self.send_header("Content-Length", str(len(zip_bytes)))
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(zip_bytes)
                else:
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "生成分卷压缩包失败"}).encode("utf-8"))

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
            finally:
                for tf in temp_files_to_clean:
                    if tf and os.path.exists(tf):
                        try:
                            os.remove(tf)
                        except Exception:
                            pass
            return

        self.send_error(404, "Endpoint not found")

def get_free_port(start_port=8899):
    for port in range(start_port, start_port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                return port
    return start_port

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ThreadingHTTPServer.allow_reuse_address = True
    port = get_free_port(8899)
    server_address = ('127.0.0.1', port)
    httpd = ThreadingHTTPServer(server_address, VocabularyPrintServer)
    url = f"http://127.0.0.1:{port}/index.html"
    
    print("=" * 60, flush=True)
    print("  [OK] 单词打印记忆本系统已成功启动！", flush=True)
    print(f"  服务网址: {url}", flush=True)
    print("  （浏览器已自动打开，若未打开请手动复制上方网址打开）", flush=True)
    print("  请勿关闭此黑色窗口，按 Ctrl + C 可退出服务", flush=True)
    print("=" * 60, flush=True)

    def open_browser():
        webbrowser.open(url)

    threading.Timer(0.5, open_browser).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n系统已退出。", flush=True)
    finally:
        httpd.server_close()

if __name__ == '__main__':
    main()
