from flask import Flask, request, jsonify
from flask_cors import CORS
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound, VideoUnavailable
import re
import os

app = Flask(__name__)
CORS(app, origins="*")


def extract_video_id(url_or_id):
    """Extract YouTube video ID from any URL format or bare ID."""
    patterns = [
        r'(?:v=|/v/|youtu\.be/|/embed/|/shorts/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url_or_id)
        if match:
            return match.group(1)
    # If it's already an 11-char ID
    if re.match(r'^[a-zA-Z0-9_-]{11}$', url_or_id.strip()):
        return url_or_id.strip()
    return None


@app.route('/transcript', methods=['GET'])
def get_transcript():
    url = request.args.get('url', '').strip()
    if not url:
        return jsonify({'error': 'Missing ?url= parameter'}), 400

    video_id = extract_video_id(url)
    if not video_id:
        return jsonify({'error': 'Could not extract video ID from URL'}), 400

    try:
        # Try English first, then any available language
        try:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
        except NoTranscriptFound:
            transcript_list = YouTubeTranscriptApi.get_transcript(video_id)

        # Join all text segments into one clean string
        full_text = ' '.join(
            segment['text'].replace('\n', ' ')
            for segment in transcript_list
        )

        # Return first 5000 chars (covers ~3-4 minutes — enough for hook analysis)
        return jsonify({
            'video_id': video_id,
            'transcript': full_text[:5000],
            'full_length': len(full_text),
            'truncated': len(full_text) > 5000
        })

    except TranscriptsDisabled:
        return jsonify({'error': 'Transcripts are disabled for this video'}), 404
    except VideoUnavailable:
        return jsonify({'error': 'Video is unavailable or private'}), 404
    except NoTranscriptFound:
        return jsonify({'error': 'No transcript found for this video'}), 404
    except Exception as e:
        return jsonify({'error': f'Failed to fetch transcript: {str(e)}'}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'yt-transcript-proxy'})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
