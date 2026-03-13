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


def normalize_channel(channel):
    """Turn @handle, channel name, or URL into a YouTube URL."""
    channel = channel.strip()
    if channel.startswith('http'):
        return channel
    if channel.startswith('@'):
        return f'https://www.youtube.com/{channel}'
    # Treat as handle
    return f'https://www.youtube.com/@{channel}'


def fetch_top_videos(channel, limit=5):
    """
    Use yt-dlp to fetch the most-viewed videos from a channel.
    Returns list of {title, url, video_id, view_count, upload_date, duration}.
    Strategy: pull from /videos sorted by most popular (yt-dlp --playlist-end N --no-download).
    """
    channel_url = normalize_channel(channel)
    # Append /videos to get the videos tab, sorted by popularity via yt-dlp's view_count
    videos_url = channel_url.rstrip('/') + '/videos'

    cmd = [
        'yt-dlp',
        '--flat-playlist',
        '--playlist-end', str(limit * 4),   # fetch more, sort by views, return top N
        '--print', '%(id)s\t%(title)s\t%(view_count)s\t%(upload_date)s\t%(duration)s',
        '--no-warnings',
        videos_url
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

    videos = []
    for line in result.stdout.strip().splitlines():
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        vid_id = parts[0].strip()
        title = parts[1].strip() if len(parts) > 1 else ''
        view_count = parts[2].strip() if len(parts) > 2 else 'N/A'
        upload_date = parts[3].strip() if len(parts) > 3 else ''
        duration = parts[4].strip() if len(parts) > 4 else ''

        if not vid_id or not title or vid_id == 'NA':
            continue

        # Format view count
        try:
            vc = int(view_count)
            if vc >= 1_000_000:
                vc_fmt = f'~{vc/1_000_000:.1f}M'
            elif vc >= 1_000:
                vc_fmt = f'~{vc/1_000:.0f}K'
            else:
                vc_fmt = str(vc)
        except:
            vc_fmt = view_count

        # Format duration
        dur_fmt = ''
        try:
            secs = int(duration)
            dur_fmt = f'{secs//60}:{secs%60:02d}'
        except:
            dur_fmt = duration

        # Format date
        date_fmt = ''
        try:
            d = str(upload_date)
            date_fmt = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
        except:
            date_fmt = upload_date

        videos.append({
            'video_id': vid_id,
            'title': title,
            'url': f'https://www.youtube.com/watch?v={vid_id}',
            'view_count_raw': int(view_count) if view_count.isdigit() else 0,
            'view_count': vc_fmt,
            'upload_date': date_fmt,
            'duration': dur_fmt
        })

    # Sort by view count descending, return top N
    videos.sort(key=lambda x: x['view_count_raw'], reverse=True)
    return videos[:limit]


def fetch_channel_info(channel):
    """Get channel name and subscriber count."""
    channel_url = normalize_channel(channel)
    cmd = [
        'yt-dlp',
        '--flat-playlist',
        '--playlist-end', '1',
        '--print', '%(channel)s\t%(channel_follower_count)s',
        '--no-warnings',
        channel_url + '/videos'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    for line in result.stdout.strip().splitlines():
        parts = line.split('\t')
        if len(parts) >= 2:
            name = parts[0].strip()
            subs_raw = parts[1].strip()
            try:
                subs = int(subs_raw)
                if subs >= 1_000_000:
                    subs_fmt = f'{subs/1_000_000:.1f}M'
                elif subs >= 1_000:
                    subs_fmt = f'{subs/1_000:.0f}K'
                else:
                    subs_fmt = str(subs)
            except:
                subs_fmt = subs_raw
            return {'name': name, 'subscribers': subs_fmt}
    return {'name': channel, 'subscribers': 'N/A'}


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
        subprocess.run(cmd, capture_output=True, text=True, timeout=45)

        for fname in os.listdir(tmpdir):
            if fname.endswith('.json3'):
                with open(os.path.join(tmpdir, fname)) as f:
                    data = json.load(f)
                texts = []
                for event in data.get('events', []):
                    segs = event.get('segs', [])
                    line = ''.join(s.get('utf8', '') for s in segs).strip()
                    if line and line != '\n':
                        texts.append(line)
                return ' '.join(texts)

        # VTT fallback
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
        subprocess.run(cmd2, capture_output=True, text=True, timeout=45)
        for fname in os.listdir(tmpdir):
            if fname.endswith('.vtt'):
                with open(os.path.join(tmpdir, fname)) as f:
                    raw = f.read()
                lines = []
                for line in raw.splitlines():
                    if line.startswith('WEBVTT') or '-->' in line or line.strip() == '':
                        continue
                    clean = re.sub(r'<[^>]+>', '', line).strip()
                    if clean:
                        lines.append(clean)
                return ' '.join(lines)

    return None


def fetch_via_api(video_id):
    """Fallback: youtube-transcript-api."""
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound
    try:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
    except NoTranscriptFound:
        transcript_list = YouTubeTranscriptApi.get_transcript(video_id)
    return ' '.join(s['text'].replace('\n', ' ') for s in transcript_list)


# ─── Routes ────────────────────────────────────────────────────────────────────

@app.route('/top-videos', methods=['GET'])
def top_videos():
    """
    GET /top-videos?channel=@365DataScience&limit=5
    Returns real top videos sorted by view count.
    """
    channel = request.args.get('channel', '').strip()
    if not channel:
        return jsonify({'error': 'Missing ?channel= parameter'}), 400

    try:
        limit = int(request.args.get('limit', 5))
        limit = max(1, min(limit, 20))
    except:
        limit = 5

    try:
        info = fetch_channel_info(channel)
        videos = fetch_top_videos(channel, limit)

        if not videos:
            return jsonify({'error': f'No videos found for channel: {channel}'}), 404

        return jsonify({
            'channel': channel,
            'channel_name': info['name'],
            'subscribers': info['subscribers'],
            'videos': videos,
            'count': len(videos)
        })

    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Request timed out fetching channel data'}), 504
    except Exception as e:
        return jsonify({'error': f'Failed: {str(e)}'}), 500


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

    try:
        full_text = fetch_via_ytdlp(video_id)
        if full_text:
            method_used = 'yt-dlp'
    except Exception as e:
        error_detail = f'yt-dlp failed: {str(e)}'

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
    try:
        r = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
        ytdlp_version = r.stdout.strip()
    except:
        ytdlp_version = 'not found'
    return jsonify({
        'status': 'ok',
        'service': 'yt-transcript-proxy',
        'yt-dlp': ytdlp_version,
        'endpoints': ['/health', '/top-videos?channel=@handle&limit=5', '/transcript?url=...']
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
