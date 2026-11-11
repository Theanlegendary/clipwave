import os
import re
import time
import glob
import uuid
import shutil
import tempfile
import io
import threading
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from flask import Flask, render_template, request, jsonify, send_file, after_this_request
import yt_dlp
import qrcode
from articles_data import BLOG_ARTICLES, ARTICLES_BY_SLUG

try:
    from yt_dlp.networking.impersonate import ImpersonateTarget
    CHROME_TARGET = ImpersonateTarget.from_str('chrome')
except Exception:
    CHROME_TARGET = None

template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), 'templates'))
app = Flask(__name__, template_folder=template_dir)
app.config['TEMPLATES_AUTO_RELOAD'] = True

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return response

@app.route('/api/info', methods=['OPTIONS'])
@app.route('/api/download', methods=['OPTIONS'])
def options_cors():
    return '', 204

# Base directory for temporary downloads
TEMP_CACHE_DIR = os.path.join(tempfile.gettempdir(), 'social_video_dl_cache')
os.makedirs(TEMP_CACHE_DIR, exist_ok=True)

# Cookie handling for YouTube cloud bypass
# Serverless platforms (Vercel/AWS Lambda) have a read-only filesystem; cookies must live in writable /tmp
COOKIES_FILE = os.path.join(tempfile.gettempdir(), 'yt_active_cookies.txt')
src_cookies = os.path.join(os.path.dirname(__file__), 'cookies.txt')
if os.path.exists(src_cookies):
    try:
        shutil.copy2(src_cookies, COOKIES_FILE)
    except Exception:
        pass
if os.environ.get('YOUTUBE_COOKIES'):
    try:
        with open(COOKIES_FILE, 'w', encoding='utf-8') as f:
            f.write(os.environ['YOUTUBE_COOKIES'])
    except Exception:
        pass

def clean_social_url(raw_url: str) -> str:
    """Strip playlist and tracking parameters from URLs to prevent infinite playlist scanning."""
    raw_url = raw_url.strip()
    try:
        parsed = urlparse(raw_url)
        # If it's a YouTube watch link with a playlist/mix attached (&list=RD...), remove the list param
        if 'youtube.com' in parsed.netloc and parsed.path == '/watch':
            qs = parse_qs(parsed.query)
            if 'v' in qs:
                new_query = urlencode({'v': qs['v'][0]})
                return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
        elif 'youtu.be' in parsed.netloc:
            return f"https://www.youtube.com/watch?v={parsed.path.strip('/')}"
        # TikTok tracking parameters (remove ?_r=... or ?is_from_webapp=...)
        elif 'tiktok.com' in parsed.netloc:
            return urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))
    except Exception:
        pass
    return raw_url

def sanitize_filename(title: str) -> str:
    """Sanitize title for safe Windows / filesystem naming."""
    clean = re.sub(r'[\\/*?:"<>|]', "", title)
    return clean[:100].strip() or "video"

def cleanup_old_files():
    """Removes cached downloaded files older than 15 minutes in background."""
    now = time.time()
    for root, dirs, files in os.walk(TEMP_CACHE_DIR):
        for f in files:
            path = os.path.join(root, f)
            try:
                if os.path.getmtime(path) < now - 900:
                    os.remove(path)
            except Exception:
                pass
        for d in dirs:
            dir_path = os.path.join(root, d)
            try:
                if not os.listdir(dir_path) and os.path.getmtime(dir_path) < now - 900:
                    shutil.rmtree(dir_path, ignore_errors=True)
            except Exception:
                pass

def get_base_ydl_opts(url=None):
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'socket_timeout': 25,
        'js_runtimes': {'node': {}},
        'remote_components': ['ejs:github'],
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'android', 'ios'],
                'player_skip': ['configs'],
            }
        }
    }
    if os.path.exists(COOKIES_FILE):
        opts['cookiefile'] = COOKIES_FILE

    # TikTok enforces TLS fingerprint checks; use Chrome impersonate for TikTok
    if url and ('tiktok' in url or 'douyin' in url):
        if CHROME_TARGET is not None:
            opts['impersonate'] = CHROME_TARGET
    return opts

SEO_CONFIGS = {
    'default': {
        'title': 'Download all Video Free — Clipwave',
        'meta_desc': 'Download YouTube videos for free in 1080p Full HD, TikTok without watermark, and Instagram Reels. 100% free, fast, no ads, no sign-up, no app install required.',
        'h1_top': 'Download all',
        'h1_hl': 'Video Free',
        'subtitle': 'Paste any video link to download in HD MP4 or 192k MP3 audio. 100% free, no ads, no viruses, no side quests.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/',
    },
    'youtube': {
        'title': 'Download YouTube Videos for Free (1080p HD MP4 & MP3) — Clipwave',
        'meta_desc': 'Download YouTube videos for free in 1080p HD, 720p, and MP3 audio. Fast, safe, clean SaveFrom alternative with no popups or malware.',
        'h1_top': 'Download YouTube Videos.',
        'h1_hl': '100% Free in Full HD!',
        'subtitle': 'Paste any YouTube or Shorts link to save high quality MP4 video or crystal-clear MP3 audio instantly.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/youtube-downloader',
    },
    'tiktok': {
        'title': 'TikTok Downloader Without Watermark (HD MP4) — Clipwave',
        'meta_desc': 'Download TikTok videos without watermark in HD quality. Fast online TikTok saver for phones and desktop. No login needed.',
        'h1_top': 'Download TikTok Videos.',
        'h1_hl': 'No Watermark!',
        'subtitle': 'Save trending TikTok videos and sounds without any watermark or blur in seconds.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/tiktok-downloader',
    },
    'instagram': {
        'title': 'Instagram Reels & Video Downloader Free Online — Clipwave',
        'meta_desc': 'Download Instagram Reels, stories, and video posts in high-definition MP4. Easy one-click download for iPhone and Android.',
        'h1_top': 'Save Instagram Reels.',
        'h1_hl': 'Instant HD MP4!',
        'subtitle': 'Paste any public Instagram Reel or post link to download directly to your camera roll.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/instagram-downloader',
    },
    'twitter': {
        'title': 'Twitter / X Video Downloader (Fast Online MP4) — Clipwave',
        'meta_desc': 'Download Twitter (X) videos and GIFs in HD MP4. Paste the tweet link and save the video in seconds.',
        'h1_top': 'Download Twitter / X Videos.',
        'h1_hl': 'Save In 1 Click!',
        'subtitle': 'Save videos and GIFs from any public X / Twitter post in original resolution.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/twitter-downloader',
    },
    'facebook': {
        'title': 'Facebook Video Downloader (HD & SD MP4) — Clipwave',
        'meta_desc': 'Download Facebook public videos, reels, and watch clips in high quality MP4. Fast and safe online Facebook video saver.',
        'h1_top': 'Download Facebook Videos.',
        'h1_hl': 'Reels & Clips!',
        'subtitle': 'Save Facebook videos and reels to your computer or phone for offline watching.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/facebook-downloader',
    },
    'mp3': {
        'title': 'YouTube to MP3 Converter (High Quality 192kbps Audio) — Clipwave',
        'meta_desc': 'Convert YouTube and social videos to high quality MP3 audio files for free. Fast online audio extractor with no software.',
        'h1_top': 'Convert to MP3 Audio.',
        'h1_hl': 'Crystal Clear Sound!',
        'subtitle': 'Extract audio tracks from YouTube and social videos in 192kbps MP3 format in seconds.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/youtube-to-mp3',
    },
    'savefrom_alt': {
        'title': 'Best Safe SaveFrom.net Alternative (No Ads, No Viruses) — Clipwave',
        'meta_desc': 'Looking for a clean SaveFrom alternative without pop-up ads or malware? Clipwave lets you download YouTube, TikTok, and Instagram videos in HD MP4 safely with 0 ads.',
        'h1_top': 'SaveFrom Alternative.',
        'h1_hl': 'Clean & 100% Ad-Free!',
        'subtitle': 'Tired of 50 popups and virus alerts on SaveFrom? Download any video in full HD safely in seconds.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/savefrom-alternative',
    },
    'threads': {
        'title': 'Threads Video Downloader Without Watermark (HD MP4) — Clipwave',
        'meta_desc': 'Download Threads videos without watermark in Full HD MP4. Free online Meta Threads video downloader for iPhone, Android, and PC. 100% free, fast, no ads, no sign-up.',
        'h1_top': 'Download Threads Videos.',
        'h1_hl': 'Without Watermark!',
        'subtitle': 'Paste any Threads post link to save original 1080p MP4 video directly to your camera roll.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/threads-video-downloader',
    },
    'reddit': {
        'title': 'Reddit Video Downloader With Audio & Sound (HD MP4) — Clipwave',
        'meta_desc': 'Download Reddit videos with merged sound and audio in 1080p Full HD MP4. Fix silent Reddit downloads free online with zero ads.',
        'h1_top': 'Download Reddit Videos.',
        'h1_hl': 'With Full Audio!',
        'subtitle': 'Save Reddit videos with merged crystal-clear audio and video in Full HD MP4 in seconds.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/reddit-downloader',
    },
    'pinterest': {
        'title': 'Pinterest Video Downloader (HD MP4 & GIF) — Clipwave',
        'meta_desc': 'Download Pinterest videos, ideas, and GIFs in high definition MP4 for free. Save pins directly to camera roll with no watermark.',
        'h1_top': 'Download Pinterest Videos.',
        'h1_hl': 'Full HD & GIFs!',
        'subtitle': 'Paste any Pinterest pin link to download HD video or GIF without watermarks.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/pinterest-downloader',
    },
    'bilibili': {
        'title': 'Bilibili Video Downloader (HD MP4 Online) — Clipwave',
        'meta_desc': 'Download Bilibili videos in HD MP4 online for free. Fast Bilibili video saver without software.',
        'h1_top': 'Download Bilibili Videos.',
        'h1_hl': 'Fast Online MP4!',
        'subtitle': 'Save Bilibili anime clips and videos in high quality MP4 directly.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/bilibili-downloader',
    },
    'soundcloud': {
        'title': 'SoundCloud Downloader to MP3 (High Quality) — Clipwave',
        'meta_desc': 'Download SoundCloud tracks and songs to MP3 audio online for free. High quality 192k audio extractor.',
        'h1_top': 'Download SoundCloud to MP3.',
        'h1_hl': '192k Audio Track!',
        'subtitle': 'Extract audio from any SoundCloud track directly into high quality MP3 format.',
        'canonical': 'https://social-video-downloader-ruby.vercel.app/soundcloud-downloader',
    }
}

@app.route('/')
def home():
    return render_template('index.html', seo=SEO_CONFIGS['default'])

@app.route('/savefrom-alternative')
def savefrom_alt_page():
    return render_template('index.html', seo=SEO_CONFIGS['savefrom_alt'])

@app.route('/youtube-downloader')
@app.route('/youtube-video-downloader')
def youtube_page():
    return render_template('index.html', seo=SEO_CONFIGS['youtube'])

@app.route('/tiktok-downloader')
@app.route('/tiktok-downloader-without-watermark')
def tiktok_page():
    return render_template('index.html', seo=SEO_CONFIGS['tiktok'])

@app.route('/instagram-downloader')
@app.route('/instagram-reels-downloader')
def instagram_page():
    return render_template('index.html', seo=SEO_CONFIGS['instagram'])

@app.route('/twitter-downloader')
@app.route('/x-video-downloader')
def twitter_page():
    return render_template('index.html', seo=SEO_CONFIGS['twitter'])

@app.route('/facebook-downloader')
@app.route('/facebook-video-downloader')
def facebook_page():
    return render_template('index.html', seo=SEO_CONFIGS['facebook'])

@app.route('/youtube-to-mp3')
def mp3_page():
    return render_template('index.html', seo=SEO_CONFIGS['mp3'])

@app.route('/threads-video-downloader')
@app.route('/threads-downloader')
def threads_page():
    return render_template('index.html', seo=SEO_CONFIGS['threads'])

@app.route('/reddit-video-downloader')
@app.route('/reddit-downloader')
def reddit_page():
    return render_template('index.html', seo=SEO_CONFIGS['reddit'])

@app.route('/pinterest-video-downloader')
@app.route('/pinterest-downloader')
def pinterest_page():
    return render_template('index.html', seo=SEO_CONFIGS['pinterest'])

@app.route('/bilibili-video-downloader')
@app.route('/bilibili-downloader')
def bilibili_page():
    return render_template('index.html', seo=SEO_CONFIGS['bilibili'])

@app.route('/soundcloud-downloader')
def soundcloud_page():
    return render_template('index.html', seo=SEO_CONFIGS['soundcloud'])

# Blog & Guides Routes
@app.route('/blog')
def blog_index():
    return render_template('blog_index.html', articles=BLOG_ARTICLES)

@app.route('/blog/<slug>')
def blog_post(slug):
    article = ARTICLES_BY_SLUG.get(slug)
    if not article:
        return render_template('blog_index.html', articles=BLOG_ARTICLES), 404
    related = [a for a in BLOG_ARTICLES if a['slug'] != slug][:3]
    return render_template('blog_post.html', article=article, related_articles=related)

# Google Search Console HTML File Verification Route
@app.route('/google<string:token>.html')
def google_verification(token):
    return f"google-site-verification: google{token}.html", 200, {'Content-Type': 'text/plain'}

@app.route('/api/qr')
def generate_qr():
    """Generate high-contrast QR code locally on demand without third-party network dependencies."""
    data = request.args.get('data', '').strip()
    if not data:
        return 'Missing data parameter', 400
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1B1B3A", back_color="#FFFFFF")
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return send_file(buf, mimetype='image/png')

@app.route('/sw.js')
def service_worker():
    return send_file(os.path.join(os.path.dirname(__file__), 'static', 'sw.js'), mimetype='application/javascript')

@app.route('/manifest.json')
def manifest():
    return jsonify({
        "name": "Clipwave — Video Downloader",
        "short_name": "Clipwave",
        "start_url": "/",
        "id": "/",
        "display": "standalone",
        "background_color": "#FFF8EE",
        "theme_color": "#BDE7FF",
        "orientation": "any",
        "description": "Download YouTube, TikTok, and Instagram videos in HD MP4 with no ads.",
        "icons": [
            {
                "src": "/static/icons/icon-192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any"
            },
            {
                "src": "/static/icons/icon-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any"
            },
            {
                "src": "/static/icons/icon-maskable-512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable"
            }
        ]
    })

@app.route('/robots.txt')
def robots():
    return """User-agent: *
Allow: /
Sitemap: https://social-video-downloader-ruby.vercel.app/sitemap.xml
""", 200, {'Content-Type': 'text/plain'}

@app.route('/sitemap.xml')
def sitemap():
    base_url = 'https://social-video-downloader-ruby.vercel.app'
    urls = [
        (f'{base_url}/', '1.0', 'daily'),
        (f'{base_url}/threads-video-downloader', '0.9', 'daily'),
        (f'{base_url}/tiktok-downloader', '0.9', 'daily'),
        (f'{base_url}/youtube-downloader', '0.9', 'daily'),
        (f'{base_url}/instagram-downloader', '0.9', 'daily'),
        (f'{base_url}/twitter-downloader', '0.8', 'daily'),
        (f'{base_url}/facebook-downloader', '0.8', 'daily'),
        (f'{base_url}/reddit-downloader', '0.8', 'daily'),
        (f'{base_url}/pinterest-downloader', '0.8', 'daily'),
        (f'{base_url}/bilibili-downloader', '0.8', 'daily'),
        (f'{base_url}/soundcloud-downloader', '0.8', 'daily'),
        (f'{base_url}/youtube-to-mp3', '0.9', 'daily'),
        (f'{base_url}/savefrom-alternative', '0.9', 'daily'),
        (f'{base_url}/blog', '0.8', 'daily'),
    ]
    # Dynamically add all blog articles
    for article in BLOG_ARTICLES:
        urls.append((f"{base_url}/blog/{article['slug']}", '0.9', 'weekly'))

    xml_entries = "\n".join([f"""  <url>
    <loc>{url}</loc>
    <lastmod>2026-11-11</lastmod>
    <changefreq>{freq}</changefreq>
    <priority>{prio}</priority>
  </url>""" for url, prio, freq in urls])

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{xml_entries}
</urlset>
""", 200, {'Content-Type': 'application/xml'}

@app.route('/api/info', methods=['POST'])
def fetch_info():
    """Extract metadata without downloading."""
    data = request.get_json(silent=True) or {}
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'error': 'Please provide a valid video link.'}), 400

    target_url = clean_social_url(url)
    ydl_opts = {
        **get_base_ydl_opts(target_url),
        'skip_download': True,
        'extract_flat': False,
    }

    try:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=False)
        except Exception as first_err:
            if 'youtube' in target_url or 'youtu.be' in target_url:
                fallback_opts = dict(ydl_opts)
                fallback_opts['extractor_args'] = {
                    'youtube': {
                        'player_client': ['android', 'ios'],
                        'player_skip': ['configs'],
                    }
                }
                with yt_dlp.YoutubeDL(fallback_opts) as ydl_fallback:
                    info = ydl_fallback.extract_info(target_url, download=False)
            else:
                raise first_err
            
        if 'entries' in info and info['entries']:
            info = info['entries'][0]

        duration_secs = info.get('duration')
        duration_str = None
        if duration_secs:
            mins, secs = divmod(int(duration_secs), 60)
            hours, mins = divmod(mins, 60)
            if hours > 0:
                duration_str = f"{hours}:{mins:02d}:{secs:02d}"
            else:
                duration_str = f"{mins}:{secs:02d}"

        # Detect platform
        extractor = str(info.get('extractor_key', 'Generic')).lower()
        platform_name = "Social Video"
        if 'youtube' in extractor:
            platform_name = "YouTube"
        elif 'tiktok' in extractor:
            platform_name = "TikTok"
        elif 'instagram' in extractor:
            platform_name = "Instagram"
        elif 'twitter' in extractor or 'x' in extractor:
            platform_name = "Twitter / X"
        elif 'facebook' in extractor:
            platform_name = "Facebook"
        elif 'reddit' in extractor:
            platform_name = "Reddit"
        elif 'pinterest' in extractor:
            platform_name = "Pinterest"

        return jsonify({
            'title': info.get('title') or "Untitled Video",
            'thumbnail': info.get('thumbnail') or "",
            'duration': duration_str or "Video",
            'author': info.get('uploader') or info.get('channel') or "Unknown Creator",
            'platform': platform_name,
            'clean_url': target_url,
        })

    except Exception as e:
        error_msg = str(e)
        if "Private video" in error_msg:
            return jsonify({'error': 'This video is private or requires login.'}), 400
        elif "not a valid URL" in error_msg:
            return jsonify({'error': 'The provided link is not a valid or supported URL.'}), 400
        elif "Sign in to confirm you’re not a bot" in error_msg or "confirm you're not a bot" in error_msg or "Sign in to confirm" in error_msg:
            return jsonify({'error': 'YouTube requires verification for datacenter IPs. TikTok & Instagram work directly, or launch Clipwave locally via start.bat on your PC/Mac!'}), 400
        return jsonify({'error': f'Unable to process link: {error_msg[:140]}...'}), 500

@app.route('/api/download', methods=['GET'])
def download():
    """Process and stream the requested format directly to the user's browser."""
    threading.Thread(target=cleanup_old_files, daemon=True).start()

    raw_url = request.args.get('url', '').strip()
    quality = request.args.get('quality', 'best')

    if not raw_url:
        return "URL parameter is missing", 400

    target_url = clean_social_url(raw_url)
    task_dir = os.path.join(TEMP_CACHE_DIR, str(uuid.uuid4()))
    os.makedirs(task_dir, exist_ok=True)
    out_template = os.path.join(task_dir, '%(id)s.%(ext)s')

    common_opts = {
        **get_base_ydl_opts(target_url),
    }

    if quality in ('audio_320', '320k', '320'):
        ydl_opts = {
            **common_opts,
            'format': 'bestaudio/best',
            'outtmpl': out_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '320',
            }],
        }
        target_ext = '.mp3'
        mime_type = 'audio/mpeg'
    elif quality == 'audio' or quality == 'mp3':
        ydl_opts = {
            **common_opts,
            'format': 'bestaudio/best',
            'outtmpl': out_template,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
        }
        target_ext = '.mp3'
        mime_type = 'audio/mpeg'
    elif quality == 'm4a':
        ydl_opts = {
            **common_opts,
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': out_template,
        }
        target_ext = '.m4a'
        mime_type = 'audio/mp4'
    elif quality == '720p' or quality == '720':
        ydl_opts = {
            **common_opts,
            'format': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]/best',
            'outtmpl': out_template,
            'merge_output_format': 'mp4',
        }
        target_ext = '.mp4'
        mime_type = 'video/mp4'
    elif quality == '480p' or quality == '480':
        ydl_opts = {
            **common_opts,
            'format': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best[height<=480]/best',
            'outtmpl': out_template,
            'merge_output_format': 'mp4',
        }
        target_ext = '.mp4'
        mime_type = 'video/mp4'
    elif quality == '360p' or quality == '360':
        ydl_opts = {
            **common_opts,
            'format': 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best[height<=360]/best',
            'outtmpl': out_template,
            'merge_output_format': 'mp4',
        }
        target_ext = '.mp4'
        mime_type = 'video/mp4'
    else: # best quality / 1080p
        ydl_opts = {
            **common_opts,
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
            'outtmpl': out_template,
            'merge_output_format': 'mp4',
        }
        target_ext = '.mp4'
        mime_type = 'video/mp4'

    try:
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(target_url, download=True)
        except Exception as first_dl_err:
            if 'youtube' in target_url or 'youtu.be' in target_url:
                fallback_ydl_opts = dict(ydl_opts)
                fallback_ydl_opts['extractor_args'] = {
                    'youtube': {
                        'player_client': ['android', 'ios'],
                        'player_skip': ['configs'],
                    }
                }
                with yt_dlp.YoutubeDL(fallback_ydl_opts) as ydl_fallback:
                    info = ydl_fallback.extract_info(target_url, download=True)
            else:
                raise first_dl_err

        if 'entries' in info and info['entries']:
            info = info['entries'][0]
        raw_title = info.get('title', 'downloaded_video')
        safe_title = sanitize_filename(raw_title)

        matching_files = glob.glob(os.path.join(task_dir, '*'))
        if not matching_files:
            return "File could not be produced", 500

        downloaded_file = matching_files[0]
        actual_ext = os.path.splitext(downloaded_file)[1] or target_ext
        safe_download_name = f"{safe_title}{actual_ext}"

        @after_this_request
        def remove_file(response):
            threading.Timer(60.0, lambda: shutil.rmtree(task_dir, ignore_errors=True)).start()
            return response

        return send_file(
            downloaded_file,
            as_attachment=True,
            download_name=safe_download_name,
            mimetype=mime_type
        )

    except Exception as e:
        shutil.rmtree(task_dir, ignore_errors=True)
        return f"Error downloading media: {str(e)}", 500

if __name__ == '__main__':
    print("==================================================")
    print("  OmniDrop Video Downloader Server Active!")
    print("  URL: http://127.0.0.1:5000")
    print("==================================================")
    app.run(host='0.0.0.0', port=5000, debug=False)
