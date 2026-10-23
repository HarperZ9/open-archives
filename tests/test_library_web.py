# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Zain Dana Harper
"""Library guards, receipts and the any-URL fetcher, against a local HTTP server."""
import hashlib
import http.server
import json
import os
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

from openarchives import licence as lic
from openarchives import webfetch
from openarchives.library import GatherPlan, Library, LibraryError, pick_root
from openarchives.model import Item, MediaFile
from openarchives.net import Http, SizeCapExceeded

PAYLOAD = bytes(range(256)) * 400          # 102,400 bytes
PAGE = b"""<html><head><title>Mill photographs</title>
<meta property="og:image" content="/img/mill.jpg"></head>
<body><a rel="license" href="https://creativecommons.org/licenses/by/4.0/">CC BY</a>
<img src="/private/secret.jpg"></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.server.agents.append(self.headers.get("User-Agent"))
        routes = {"/robots.txt": (b"User-agent: *\nDisallow: /private/\n", "text/plain"),
                  "/file.bin": (PAYLOAD, "application/octet-stream"),
                  "/page.html": (PAGE, "text/html"),
                  "/img/mill.jpg": (PAYLOAD[:5000], "image/jpeg"),
                  "/private/secret.jpg": (b"nope", "image/jpeg")}
        body, ctype = routes.get(self.path, (None, None))
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ServerCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.agents = []
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = Library(Path(self.tmp.name) / "lib")
        self.http = Http(interval_scale=0.0)

    def tearDown(self):
        self.tmp.cleanup()


class LibraryTests(ServerCase):
    @mock.patch.dict(os.environ, {"OPEN_ARCHIVES_FORBIDDEN_DRIVES": "D"})
    def test_refuses_forbidden_drive(self):
        with self.assertRaises(LibraryError):
            pick_root(r"D:\archive-library")
        with self.assertRaises(LibraryError):
            Library(Path(r"D:\anything"))

    def test_download_hash_receipt_and_user_agent(self):
        it = Item(source="web", id="file", title="Test file", media_type="dataset",
                  landing_url=self.base, files=[MediaFile(url=self.base + "/file.bin")],
                  rights_raw="CC0").finalise()
        plan = GatherPlan(cap_bytes=10 << 20, per_file_bytes=10 << 20)
        receipt = json.loads(self.lib.gather(self.http, [it], plan, "t", {"q": 1}).read_text())
        f = receipt["items"][0]["files"][0]
        self.assertEqual(f["sha256"], hashlib.sha256(PAYLOAD).hexdigest())
        self.assertEqual(f["bytes"], len(PAYLOAD))
        self.assertEqual(receipt["basis_breakdown"], {lic.FREE: 1})
        self.assertIn("open-archives", self.server.agents[-1])
        self.assertEqual(len(self.lib.indexed()), 1)

    def test_run_cap_stops_download_and_leaves_no_partial(self):
        dest = Path(self.tmp.name) / "x.bin"
        with self.assertRaises(SizeCapExceeded):
            self.http.download(self.base + "/file.bin", dest, 1000)
        self.assertFalse(dest.exists())
        self.assertFalse(dest.with_suffix(".bin.part").exists())

    def test_declared_size_over_cap_is_skipped(self):
        it = Item(source="web", id="big", title="Big", media_type="dataset", landing_url=self.base,
                  files=[MediaFile(url=self.base + "/file.bin", size=50 << 20)]).finalise()
        receipt = json.loads(self.lib.gather(self.http, [it], GatherPlan(cap_bytes=1 << 20),
                                             "cap", None).read_text())
        self.assertIn("run cap", receipt["items"][0]["status"])
        self.assertEqual(receipt["bytes_downloaded"], 0)


class WebFetchTests(ServerCase):
    def test_robots_disallow_refuses(self):
        with self.assertRaises(webfetch.RobotsRefused):
            webfetch.fetch(self.http, self.lib, self.base + "/private/secret.jpg")

    def test_page_media_hints_and_reference_only_default(self):
        receipt = json.loads(webfetch.fetch(self.http, self.lib, self.base + "/page.html",
                                            media_limit=5).read_text())
        fetched = {r["item"]["files"][0]["url"].rsplit("/", 1)[-1]: r for r in receipt["items"]}
        self.assertIn("mill.jpg", fetched)
        self.assertNotIn("secret.jpg", fetched)          # robots-disallowed media skipped
        page = fetched["page.html"]["item"]
        self.assertIn("https://creativecommons.org/licenses/by/4.0/", page["extra"]["licence_hints"])
        self.assertEqual(page["basis"], lic.REFERENCE_ONLY)   # hints never clear material
        self.assertIn("not reviewed", page["extra"]["terms_review"])

    def test_author_claim_sets_basis(self):
        receipt = json.loads(webfetch.fetch(
            self.http, self.lib, self.base + "/img/mill.jpg", licence_claim="CC BY 4.0",
            terms_note="terms page allows reuse with credit").read_text())
        self.assertEqual(receipt["items"][0]["item"]["basis"], lic.CREDIT)

    def test_fair_use_needs_reason(self):
        with self.assertRaises(ValueError):
            webfetch.fetch(self.http, self.lib, self.base + "/img/mill.jpg", basis_claim=lic.FAIR_USE)


if __name__ == "__main__":
    unittest.main()
