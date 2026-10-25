# SosGrab

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
