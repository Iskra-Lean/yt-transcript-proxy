# yt-transcript-proxy

A lightweight Flask service that fetches YouTube video transcripts server-side, bypassing browser CORS restrictions. Deployed on Render and called by the YouTube Competitive Research dashboard.

## Endpoint

### GET /transcript?url={youtube_url}

Returns the transcript for any public YouTube video.

**Example:**
```
GET https://your-service.onrender.com/transcript?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

**Response:**
```json
{
  "video_id": "dQw4w9WgXcQ",
  "transcript": "Full transcript text here...",
  "full_length": 8234,
  "truncated": true
}
```

**Error response:**
```json
{
  "error": "Transcripts are disabled for this video"
}
```

### GET /health

Returns `{"status": "ok"}` — used to verify the service is running.

---

## Deploy to Render (step by step)

1. Push this folder to a GitHub repository
2. Go to render.com → New → Web Service
3. Connect your GitHub repo
4. Render auto-detects render.yaml and configures everything
5. Click Deploy
6. Copy your service URL (e.g. https://yt-transcript-proxy.onrender.com)
7. Paste it into the dashboard widget

---

## Local development

```bash
pip install -r requirements.txt
python main.py
# Service runs at http://localhost:5000
```

Test it:
```bash
curl "http://localhost:5000/transcript?url=https://www.youtube.com/watch?v=VIDEO_ID"
```
