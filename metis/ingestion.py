"""Bounded paper fetcher with DNS pinning on every redirect (including IPv6).
Socket connection uses a vetted numeric address while TLS validates original hostname.
No ambient proxy credentials, cookies or cloud metadata access.
"""

import hashlib
import http.client
import io
import multiprocessing
import resource
import ipaddress
import re
import socket
import ssl
import urllib.parse
from pypdf import PdfReader

MAX_BYTES = 12 * 1024 * 1024


class UnsafeURL(ValueError):
    pass


def resolve_public(url):
    u = urllib.parse.urlsplit(url)
    if (
        u.scheme not in ("http", "https")
        or not u.hostname
        or u.username
        or u.password
        or u.port not in (None, 80, 443)
    ):
        raise UnsafeURL("Only public HTTP(S) URLs on ports 80/443 are allowed")
    if len(url) > 4096:
        raise UnsafeURL("URL too long")
    try:
        addresses = socket.getaddrinfo(
            u.hostname,
            u.port or (443 if u.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise UnsafeURL("Hostname resolution failed") from exc
    ips = list(dict.fromkeys(a[4][0] for a in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise UnsafeURL(
            "Private, loopback, link-local and reserved destinations are blocked"
        )
    return u, ips[0]


class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, port):
        super().__init__(
            host, port=port, timeout=20, context=ssl.create_default_context()
        )
        self.ip = ip

    def connect(self):
        sock = socket.create_connection((self.ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def fetch(url, redirects=4):
    for _ in range(redirects + 1):
        u, ip = resolve_public(url)
        port = u.port or (443 if u.scheme == "https" else 80)
        conn = (
            PinnedHTTPS(u.hostname, ip, port)
            if u.scheme == "https"
            else http.client.HTTPConnection(ip, port, timeout=20)
        )
        path = urllib.parse.urlunsplit(("", "", u.path or "/", u.query, ""))
        try:
            conn.request(
                "GET",
                path,
                headers={
                    "Host": u.netloc,
                    "User-Agent": "Metis/1.0 (paper ingestion)",
                    "Accept": "application/pdf,text/plain,text/html",
                    "Accept-Encoding": "identity",
                },
            )
            r = conn.getresponse()
            if r.status in (301, 302, 303, 307, 308):
                dest = r.getheader("Location")
                if not dest:
                    raise UnsafeURL("Redirect missing destination")
                url = urllib.parse.urljoin(url, dest)
                continue
            if r.status != 200:
                raise ValueError("Paper server returned HTTP " + str(r.status))
            if int(r.getheader("Content-Length", "0")) > MAX_BYTES:
                raise ValueError("Paper exceeds 12 MiB")
            raw = r.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Paper exceeds 12 MiB")
            return raw, r.getheader("Content-Type", ""), url
        finally:
            conn.close()
    raise UnsafeURL("Too many redirects")


def arxiv_url(identifier):
    identifier = identifier.strip().removeprefix("arXiv:")
    if not re.fullmatch(
        r"(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?", identifier
    ):
        raise ValueError("Invalid arXiv ID")
    return "https://arxiv.org/pdf/" + identifier


def _pdf_child(raw, channel):
    try:
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        reader = PdfReader(io.BytesIO(raw), strict=False)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are unsupported")
        if len(reader.pages) > 150:
            raise ValueError("PDF limited to 150 pages")
        text = ""
        for page in reader.pages:
            text += (page.extract_text() or "")[:40000] + "\n"
            if len(text) > 300000:
                raise ValueError("Extracted paper exceeds 300000 characters")
        channel.send((True, text))
    except BaseException as exc:
        channel.send(
            (False, "PDF parsing failed: " + type(exc).__name__ + ": " + str(exc)[:200])
        )
    finally:
        channel.close()


def pdf_text(raw):
    ctx = multiprocessing.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_pdf_child, args=(raw, child), daemon=True)
    process.start()
    child.close()
    try:
        if not parent.poll(12):
            raise ValueError("PDF parsing exceeded 12 second limit")
        try:
            ok, text = parent.recv()
        except EOFError:
            raise ValueError("PDF parser exhausted resource limits")
        if not ok:
            raise ValueError(text)
        return text
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)


def extract_text(raw, ctype=""):
    if raw.startswith(b"%PDF-"):
        text = pdf_text(raw)
    else:
        text = raw.decode("utf-8", errors="replace")
        if "html" in ctype:
            from html.parser import HTMLParser

            class Text(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.parts = []
                    self.skip = 0

                def handle_starttag(self, t, a):
                    if t in ("script", "style"):
                        self.skip += 1

                def handle_endtag(self, t):
                    if t in ("script", "style"):
                        self.skip = max(0, self.skip - 1)

                def handle_data(self, d):
                    if not self.skip:
                        self.parts.append(d)

            p = Text()
            p.feed(text)
            text = " ".join(p.parts)
    text = text.strip()
    if len(text) < 30:
        raise ValueError("No usable text; scanned PDFs require external OCR")
    if len(text) > 300000:
        raise ValueError("Extracted paper exceeds 300000 characters")
    return text


def content_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()
