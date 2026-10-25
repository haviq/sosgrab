# Hans Downloader

Paste a TikTok / Instagram / YouTube / X / Facebook link → get direct download
links. Extract-and-redirect: the server resolves CDN URLs with yt-dlp and the
client downloads straight from the platform — nothing is stored or proxied.

## Run locally
pip install -r requirements.txt
uvicorn server:app --reload --port 8790

## Deploy
vercel --prod

## Note
For personal use; respect each platform's terms and content copyright.

## Browser extension: Hans Downloader Cookie Helper (one-click cookies)

Private reels need your login session. Instead of copying headers by hand,
load the bundled extension once and it becomes a single click:

1. Chrome/Edge: `chrome://extensions` → enable **Developer mode** → **Load unpacked** → pick the `extension/` folder (or use `sosgrab-cookie-helper.zip`).
2. Open facebook.com / instagram.com / tiktok.com, click the Hans Downloader icon → **Copy + open Hans Downloader**.
3. Paste into the **Advanced** box and Grab.

The extension only reads cookies for the four supported domains, shows
required-key checks (c_user/xs, sessionid), and never sends cookies anywhere —
the clipboard is the transport.
