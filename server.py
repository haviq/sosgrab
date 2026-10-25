"""SosGrab — social media video link extractor.

Extract-and-redirect architecture: the server never proxies media bytes
(serverless response limits make that impossible); it resolves direct
CDN URLs with yt-dlp and hands them to the client.
"""
import os, re, ipaddress, socket, tempfile
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
    cookies: str = ""


PLATFORMS = [
    (r"tiktok\.com", "TikTok"),
    (r"instagram\.com", "Instagram"),
    (r"(youtube\.com|youtu\.be)", "YouTube"),
    (r"(twitter\.com|x\.com)", "X (Twitter)"),
    (r"facebook\.com|fb\.watch", "Facebook"),
    (r"twitch\.tv", "Twitch"),
    (r"soundcloud\.com", "SoundCloud"),
]


CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

# Zero-effort mode: a saved session cookie per platform, set as env vars
# (FB_COOKIE / IG_COOKIE / TT_COOKIE). Applied automatically when the
# request carries no per-request cookie. Rotate by updating the env var.
SAVED_COOKIES = {
    "facebook": os.environ.get("FB_COOKIE", ""),
    "instagram": os.environ.get("IG_COOKIE", ""),
    "tiktok": os.environ.get("TT_COOKIE", ""),
}


def _netscape_jar(header: str, host: str) -> Optional[str]:
    """Convert a raw 'k=v; k2=v2' Cookie header into a Netscape-format
    cookie file — the only cookie transport yt-dlp reliably honors."""
    pairs = []
    for part in header.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if k and re.match(r"^[\w\[\].-]+$", k):
            pairs.append((k, v))
    if not pairs:
        return None
    dom = "." + re.sub(r"^www\.", "", host)
    lines = ["# Netscape HTTP Cookie File"]
    for k, v in pairs:
        lines.append(f"{dom}\tTRUE\t/\tTRUE\t2147483647\t{k}\t{v}")
    fd = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False,
                                     dir="/tmp" if os.path.isdir("/tmp") else None)
    fd.write("\n".join(lines) + "\n")
    fd.close()
    return fd.name


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

    # bring-your-own-cookie: private reels/posts need the user's own session.
    # The cookie is used for this one extraction and never stored or logged.
    cookies = (req.cookies or "").strip()
    if cookies and ("\n" in cookies or len(cookies) > 8000):
        raise HTTPException(400, "Invalid cookie header.")
    if cookies and not re.match(r'^[\x21-\x7e\x80-\xff; =]+$', cookies):
        raise HTTPException(400, "Invalid cookie header.")

    import yt_dlp
    host = re.match(r"^https?://([^/:?#]+)", url, re.I).group(1).lower()
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "nocheckcertificate": False,
        "socket_timeout": 20,
        "user_agent": CHROME_UA,
    }
    jar = None
    if cookies:
        jar = _netscape_jar(cookies, host)
        if jar:
            opts["cookiefile"] = jar
        else:
            opts["http_headers"] = {"Cookie": cookies}
    else:
        # zero-effort fallback: platform cookie saved on the server
        plat = platform_of(url).lower().split(" ")[0]
        saved = SAVED_COOKIES.get(plat, "")
        if saved:
            jar = _netscape_jar(saved, host)
            if jar:
                opts["cookiefile"] = jar
    try:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
        finally:
            if jar:
                try: os.unlink(jar)
                except Exception: pass
    except Exception as e:
        msg = str(e)
        if "Cannot parse data" in msg:
            raise HTTPException(403, "Facebook refused the request even with your cookie. Re-login to Facebook, copy a FRESH cookie (F12 → Network → first request → Cookie header) and try again. The session may have expired or been logged out remotely.")
        if "Sign in to confirm" in msg or "bot" in msg.lower():
            raise HTTPException(502, "The platform is asking this server to verify it is not a bot for this video. Try another link or host it on a residential IP.")
        if "Private" in msg or "login" in msg.lower() or "rate limit" in msg.lower() or "429" in msg:
            hint = " If this is your private content, paste your session cookie in Advanced." if not cookies else " Your cookie may have expired — refresh it and try again."
            raise HTTPException(403, "That content is private or requires a login." + hint)
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
        v, a = f.get("vcodec"), f.get("acodec")
        video = v not in (None, "none")
        audio = a not in (None, "none")
        if v == "" and a == "":
            # FB progressive sources report no codecs at all: they carry both
            video = audio = True
        if not video and not audio:
            continue
        if video and audio:
            label = "MP4 with sound"
            if f.get("height"):
                label = f"MP4 {f['height']}p with sound"
        elif video:
            label = f"{f.get('height') or '?'}p (NO SOUND)"
        else:
            label = f"Audio {f.get('abr') or ''}kbps".replace("  ", " ")
        key = (label, f.get("ext"))
        if key in seen:
            continue
        seen.add(key)
        formats.append({
            "label": label,
            "ext": f.get("ext"),
            "url": f["url"],
            "filesize": f.get("filesize") or f.get("filesize_approx"),
            "video": video,
            "has_sound": audio,
        })
    # combined (video+audio in one file) always first, biggest first;
    # then silent video-only; audio-only last
    def height_of(f):
        return int(re.sub(r"\D", "", f["label"].split("(")[0]) or 0)
    formats.sort(key=lambda f: (
        0 if (f["video"] and f["has_sound"]) else (1 if f["video"] else 2),
        -height_of(f),
        -(f["filesize"] or 0),
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
