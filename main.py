from flask import Flask, request, jsonify
from flask_cors import CORS
import re, os, subprocess, json, tempfile

app = Flask(__name__)
CORS(app, origins="*")


def extract_video_id(url_or_id):
    patterns = [r'(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})']
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id.strip()):
        return url_or_id.strip()
    return None


def fetch_via_ytdlp(video_id):
    """Use yt-dlp to fetch auto-generated or manual subtitles."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            "yt-dlp",
            "--write-auto-subs",
            "--write-subs",
            "--sub-lang", "en",
            "--sub-format", "json3",
            "--skip-download",
            "--no-playlist",
            "-o", f"{tmpdir}/%(id)s.%(ext)s",
            url
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

        # Find the subtitle file
        for fname in os.listdir(tmpdir):
            if fname.endswith('.json3'):
                with open(os.path.join(tmpdir, fname)) as f:
                    data = json.load(f)
                # Parse json3 format
                texts = []
                for event in data.get('events', []):
                    segs = event.get('segs', [])
                    line = ''.join(s.get('utf8', '') for s in segs).strip()
                    if line and line != '\n':
                        texts.append(line)
                return ' '.join(texts)

        # Try vtt fallback
        cmd2 = [
            "yt-dlp",
            "--write-auto-subs",
            "--write-subs",
            "--sub-lang", "en",
            "--sub-format", "vtt",
            "--skip-download",
            "--no-playlist",
            "-o", f"{tmpdir}/%(id)s.%(ext)s",
            url
        ]
        subprocess.run(cmd2, capture_output=True, text=True, timeout=30)
        for fname in os.listdir(tmpdir):
            if fname.endswith('.vtt'):
                with open(os.path.join(tmpdir, fname)) as f:
                    raw = f.read()
                # Strip VTT headers/timestamps
                lines = []
                for line in raw.splitlines():
                    if line.startswith('WEBVTT') or '-->' in line or line.strip() == '':
                        continue
                    # Remove HTML tags
                    clean = re.sub(r'<[^>]+>', '', line).strip()
                    if clean:
                        lines.append(clean)
                return ' '.join(lines)

    return None


def fetch_via_api(video_id):
    """Fallback: youtube-transcript-api."""
    from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
    except NoTranscriptFound:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
    return ' '.join(s['text'].replace('\n', ' ') for s in transcript_list)


@app.route('/transcript', methods=['GET'])
def get_transcript():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'Missing ?url= parameter'}), 400

    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'error': 'Could not extract video ID'}), 400

    full_text = None
    method_used = None
    error_detail = None

    # Try yt-dlp first
    try:
        full_text = fetch_via_ytdlp(video_id)
        if full_text:
            method_used = 'yt-dlp'
    except Exception as e:
        error_detail = f'yt-dlp failed: {str(e)}'

    # Fallback to youtube-transcript-api
    if not full_text:
        try:
            full_text = fetch_via_api(video_id)
            if full_text:
                method_used = 'transcript-api'
        except Exception as e:
            error_detail = (error_detail or '') + f' | api failed: {str(e)}'

    if not full_text:
        return jsonify({'error': f'No transcript available. {error_detail or ""}'}), 404

    return jsonify({
        'video_id': video_id,
        'transcript': full_text[:5000],
        'full_length': len(full_text),
        'truncated': len(full_text) > 5000,
        'method': method_used
    })


@app.route('/health', methods=['GET'])
def health():
    # Check if yt-dlp is available
    try:
        r = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        ytdlp_version = r.stdout.strip()
    except:
        ytdlp_version = 'not found'
    return jsonify({'status': 'ok', 'service': 'yt-transcript-proxy', 'yt-dlp': ytdlp_version})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
