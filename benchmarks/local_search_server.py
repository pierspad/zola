#!/usr/bin/env python3
"""Local browser-only delivery check with explicit test gzip/Brotli negotiation."""
import argparse
import gzip
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
try:
    import brotli
except ImportError:
    brotli = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(args.root.resolve()), **kw)

        def log_message(self, format, *values):
            pass

        def send_head(self):
            path = Path(self.translate_path(self.path))
            if path.is_dir():
                path /= 'index.html'
            status = 200 if path.is_file() else 404
            raw = path.read_bytes() if status == 200 else b'Not found'
            mime = self.guess_type(str(path))
            encoding = None
            body = raw
            accepted = self.headers.get('Accept-Encoding', '')
            if status == 200 and (mime.startswith('text/') or mime in ('application/json','application/javascript','image/svg+xml')):
                if brotli and 'br' in accepted:
                    body, encoding = brotli.compress(raw, quality=5), 'br'
                elif 'gzip' in accepted:
                    body, encoding = gzip.compress(raw, mtime=0), 'gzip'
            self.send_response(status)
            self.send_header('Content-Type',mime)
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('Vary','Accept-Encoding')
            if encoding:
                self.send_header('Content-Encoding',encoding)
            self.end_headers()
            with args.log.open('a') as log:
                log.write(json.dumps({'timestamp':time.time(),'method':self.command,'path':urlsplit(self.path).path,
                                      'status':status,'encoding':encoding,'raw_body_bytes':len(raw),
                                      'encoded_body_bytes':len(body),'accept_encoding':accepted}) + '\n')
            return io.BytesIO(body)

    print(f'Local test compression server on http://127.0.0.1:{args.port}',flush=True)
    ThreadingHTTPServer(('127.0.0.1',args.port),Handler).serve_forever()


if __name__ == '__main__':
    main()
