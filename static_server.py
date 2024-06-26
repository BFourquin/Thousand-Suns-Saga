#!/usr/bin/env python3
# encoding: utf-8

"""Use instead of `python3 -m http.server` when you need CORS"""

import os
from http.server import HTTPServer, SimpleHTTPRequestHandler


class CORSRequestHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET')
        # self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        return super(CORSRequestHandler, self).end_headers()


# Static folder
os.chdir('admin_web/static/')

httpd = HTTPServer(('0.0.0.0', 33100), CORSRequestHandler)
httpd.serve_forever()
