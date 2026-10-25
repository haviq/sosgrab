"""SosGrab — social media video link extractor.

Extract-and-redirect architecture: the server never proxies media bytes
(serverless response limits make that impossible); it resolves direct
CDN URLs with yt-dlp and hands them to the client.
"""
import os, re, ipaddress, socket
from typing import Optional
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
from pathlib import Path
import threading, time

BASE_DIR = Path(__file__).parent
STATIC = BASE_DIR / "static"

APP_VERSION = "1.0.0"

app = FastAPI(title="SosGrab", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---- best-effort per-IP rate limit (resets per serverless instance) ----
_hits: dict = {}
_lock = threading.Lock()
LIMIT = int(os.environ.get("RATE_LIMIT", "15"))
WINDOW = 300.0


def _allow(ip: str) -> bool:
    now = time.time()
    with _lock:
        arr = [t for t in _hits.get(ip, []) if now - t < WINDOW]
        if len(arr) >= LIMIT:
            _hits[ip] = arr
            return False
        arr.append(now)
        _hits[ip] = arr
        return True


BLOCKED_HOSTS = re.compile(
    r"^(localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|169\.254\.|\[?::1\]?$)",
    re.I,
)


def validate_url(raw: str) -> str:
    url = (raw or "").strip()
    if not re.match(r"^https?://[\w.-]+", url, re.I):
        raise HTTPException(400, "Provide a valid http(s) URL.")
    host = re.match(r"^https?://([^/:?#]+)", url, re.I).group(1).lower()
    if BLOCKED_HOSTS.match(host):
        raise HTTPException(400, "That host is not allowed.")
    try:
        infos = socket.getaddrinfo(host, None)
        for info in infos:
            if ipaddress.ip_address(info[4][0]).is_private:
                raise HTTPException(400, "That host is not allowed.")
    except socket.gaierror:
        raise HTTPException(400, "Could not resolve that host.")
    return url


class ResolveReq(BaseModel):
    url: str


PLATFORMS = [
    (r"tiktok\.com", "TikTok"),
    (r"instagram\.com", "Instagram"),
    (r"(youtube\.com|youtu\.be)", "YouTube"),
    (r"(twitter\.com|x\.com)", "X (Twitter)"),
    (r"facebook\.com|fb\.watch", "Facebook"),
    (r"twitch\.tv", "Twitch"),
    (r"soundcloud\.com", "SoundCloud"),
]


def platform_of(url: str) -> str:
    for pat, name in PLATFORMS:
        if re.search(pat, url, re.I):
            return name
    return "Web"


@app.post("/api/resolve")
def api_resolve(req: ResolveReq, request: Request):
    ip = request.client.host if request.client else "x"
    if not _allow(ip):
        raise HTTPException(429, "Too many requests — wait a few minutes.")
    url = validate_url(req.url)

    import yt_dlp
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "nocheckcertificate": False,
        "socket_timeout": 20,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        msg = str(e)
        if "Sign in to confirm" in msg or "bot" in msg.lower():
            raise HTTPException(502, "The platform is asking this server to verify it is not a bot for this video. Try another link or host it on a residential IP.")
        if "Private" in msg or "login" in msg.lower():
            raise HTTPException(403, "That content is private or requires a login.")
        if "Unsupported" in msg:
            raise HTTPException(400, "That URL is not supported.")
        raise HTTPException(502, "Extraction failed: " + msg[:180])

    entries = info.get("entries") if info.get("entries") is not None else [info]
    entry = entries[0]
    formats = []
    seen = set()
    for f in entry.get("formats") or []:
        if not f.get("url"):
            continue
        v, a = f.get("vcodec", "none"), f.get("acodec", "none")
        if v == "none" and a == "none":
            continue
        label = f"{f.get('height') or f.get('abr') or '?'}p" if v != "none" else f"audio {f.get('abr') or ''}kbps"
        key = (label, f.get("ext"))
        if key in seen:
            continue
        seen.add(key)
        formats.append({
            "label": label.strip(),
            "ext": f.get("ext"),
            "url": f["url"],
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "video": v != "none",
        })
    # best progressive first, then by height desc, then audio
    formats.sort(key=lambda f: (
        0 if (f["video"] and f.get("ext") == "mp4") else 1,
        -(int(re.sub(r"\D", "", f["label"]) or 0)),
    ))
    formats = formats[:6]

    return {
        "platform": platform_of(url),
        "title": entry.get("title") or "media",
        "thumbnail": entry.get("thumbnail"),
        "duration": entry.get("duration"),
        "uploader": entry.get("uploader"),
        "formats": formats,
        "note": "Download straight from the platform CDN — nothing passes through this server.",
    }


@app.get("/api/health")
def health():
    return {"ok": True, "version": APP_VERSION}


@app.middleware("http")
async def _headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    return resp


@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"),
                        headers={"Cache-Control": "no-cache, must-revalidate"})


@app.get("/api/healthz")
def healthz():
    return Response(b"ok", media_type="text/plain")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    return JSONResponse({"detail": "Internal error"}, status_code=500)


# static assets (logo/favicon if added later)
from fastapi.staticfiles import StaticFiles
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
