#!/usr/bin/env python3
"""Mini static server pro Railway deployment.

Identické chování jako `python3 -m http.server` (servíruje `public/`),
ale s explicit HTTP hlavičkami pro iframe embed v Macaly + bezpečnostní
hygiena.

Klíčové headery:
- Content-Security-Policy: frame-ancestors * (povolí embed všude)
- X-Frame-Options odstraněno (deprecated, frame-ancestors je nahrazuje)
- Cache-Control pro static assety (long cache, etag default)
- Permissions-Policy bez interactive features (geolocation, mic, atd.)

Usage:
    PORT=8080 python3 server.py
"""
from __future__ import annotations

import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PUBLIC_DIR = Path(__file__).resolve().parent / "public"


class TalentMapHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC_DIR), **kwargs)

    def end_headers(self) -> None:
        # Iframe embed — frame-ancestors je modern equivalent X-Frame-Options
        self.send_header(
            "Content-Security-Policy",
            "frame-ancestors *; "
            "default-src 'self'; "
            "img-src 'self' data: https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self' data: https://fonts.gstatic.com; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "base-uri 'self'",
        )
        # Modern security hardening
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=(), payment=()",
        )
        # Cache: JSON datasety 1h (refresh měsíčně, ale i tak hash-based etag)
        path = self.path.split("?")[0]
        if path.endswith(".json"):
            self.send_header("Cache-Control", "public, max-age=3600")
        elif path.endswith((".html", "/")):
            self.send_header("Cache-Control", "public, max-age=300")
        else:
            self.send_header("Cache-Control", "public, max-age=86400")
        super().end_headers()

    def log_message(self, format, *args):
        # Railway logs handle requestlog už sám; držet jen 4xx/5xx, ne 2xx noise.
        try:
            status = int(args[1])
            if status < 400:
                return
        except (IndexError, ValueError):
            pass
        super().log_message(format, *args)


def main() -> None:
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), TalentMapHandler)
    print(f"Czech AI Talent Map · serving public/ on :{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutdown", flush=True)


if __name__ == "__main__":
    main()
