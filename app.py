# app.py
from flask import Flask, jsonify, send_file, request, Response, abort, make_response
from flask_cors import CORS
import os
import json
import subprocess
import threading
from pathlib import Path
from werkzeug.utils import secure_filename
import mimetypes
import re
import platform
from functools import wraps

app = Flask(__name__)
# เปิด CORS กว้างไว้ (เสิร์ฟโดเมนเดียวกันผ่าน Apache ก็ไม่เป็นไร)
CORS(app, resources={r"/*": {"origins": "*"}})

# ==============================
# CONFIG
# ==============================
# ปรับ path ให้ตรงระบบจริง
app.config['VIDEO_FOLDER'] = r'D:\NewSoftware\videostreaming\video'
app.config['PROCESSED_FOLDER'] = r'D:\NewSoftware\videostreaming\video_process'
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024 * 1024  # 20GB

# >>> Basic Auth เฉพาะหน้า index <<<
app.config['INDEX_USERNAME'] = 'videoadmin'      # เปลี่ยนได้
app.config['INDEX_PASSWORD'] = 'StrongPass!'     # เปลี่ยนได้

# สร้างโฟลเดอร์ถ้ายังไม่มี
Path(app.config['VIDEO_FOLDER']).mkdir(parents=True, exist_ok=True)
Path(app.config['PROCESSED_FOLDER']).mkdir(parents=True, exist_ok=True)

# สตรีมไฟล์ใหญ่
CHUNK_SIZE = 1024 * 1024  # 1MB
HLS_SEGMENT_SECONDS = 6

# MIME สำคัญ
mimetypes.add_type('application/vnd.apple.mpegURL', '.m3u8')
mimetypes.add_type('video/MP2T', '.ts')
mimetypes.add_type('video/mp4', '.m4s')

VIDEO_EXTS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v'}

# ==============================
# UTILITIES
# ==============================
def _cache_headers(resp, seconds=3600):
    resp.headers['Cache-Control'] = f'public, max-age={seconds}'
    return resp

def _file_iter(path: Path, start: int, end: int, chunk_size=CHUNK_SIZE):
    with open(path, 'rb') as f:
        f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = f.read(min(chunk_size, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk

def _safe_id_from_relpath(relpath: str) -> str:
    # ใช้ relpath เป็น key สำหรับโฟลเดอร์ processed โดยแปลงอักขระพิเศษ
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', relpath)

def send_video_with_range(video_path: Path):
    """ส่งไฟล์วิดีโอ/ไฟล์ใหญ่พร้อมรองรับ HTTP Range"""
    video_path = Path(video_path)
    if not video_path.exists():
        abort(404)

    file_size = video_path.stat().st_size
    range_header = request.headers.get('Range')
    content_type = mimetypes.guess_type(str(video_path))[0] or 'application/octet-stream'

    if not range_header:
        # ส่งทั้งไฟล์ (200)
        resp = make_response(_file_iter(video_path, 0, file_size - 1, chunk_size=CHUNK_SIZE))
        resp.status_code = 200
        resp.headers['Content-Length'] = str(file_size)
        resp.headers['Content-Type'] = content_type
        resp.headers['Accept-Ranges'] = 'bytes'
        return _cache_headers(resp, 3600)

    # Parse: bytes=start-end
    m = re.match(r'bytes=(\d+)-(\d*)', range_header)
    if not m:
        resp = make_response('', 416)
        resp.headers['Content-Range'] = f'bytes */{file_size}'
        return resp

    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1

    if start >= file_size or end >= file_size or start > end:
        resp = make_response('', 416)
        resp.headers['Content-Range'] = f'bytes */{file_size}'
        return resp

    length = end - start + 1
    resp = Response(
        _file_iter(video_path, start, end, chunk_size=CHUNK_SIZE),
        status=206,
        headers={
            'Content-Range': f'bytes {start}-{end}/{file_size}',
            'Accept-Ranges': 'bytes',
            'Content-Length': str(length),
            'Content-Type': content_type
        }
    )
    return _cache_headers(resp, 3600)

# --------- Basic Auth (เฉพาะหน้า index) ----------
def _auth_failed():
    resp = make_response('Authentication required', 401)
    resp.headers['WWW-Authenticate'] = 'Basic realm="Video Index"'
    return resp

def require_index_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.type != 'basic':
            return _auth_failed()
        if auth.username != app.config['INDEX_USERNAME'] or auth.password != app.config['INDEX_PASSWORD']:
            return _auth_failed()
        return f(*args, **kwargs)
    return wrapper
# ---------------------------------------------------

# ==============================
# VIDEO PROCESSOR
# ==============================
class VideoProcessor:
    def __init__(self, video_folder, processed_folder):
        self.video_folder = Path(video_folder)
        self.processed_folder = Path(processed_folder)
        self.ffmpeg_path = 'ffmpeg'  # ต้องอยู่ใน PATH
        self.processing_status = {}  # { key: 'processing'|'completed'|'error'|'not_started' }
        self._lock = threading.Lock()

    def get_video_info(self, video_path: Path):
        """ดึงข้อมูลวิดีโอด้วย ffprobe"""
        try:
            cmd = [
                'ffprobe', '-v', 'quiet', '-print_format', 'json',
                '-show_format', '-show_streams', str(video_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                info = json.loads(result.stdout)
                video_stream = next((s for s in info.get('streams', []) if s.get('codec_type') == 'video'), None)
                fmt = info.get('format', {})
                return {
                    'duration': float(fmt.get('duration', 0) or 0),
                    'size': int(fmt.get('size', 0) or 0),
                    'width': int(video_stream.get('width', 0) if video_stream else 0),
                    'height': int(video_stream.get('height', 0) if video_stream else 0),
                    'bitrate': int(fmt.get('bit_rate', 0) or 0),
                }
        except Exception as e:
            print(f"Error getting video info: {e}")
        return None

    def _find_input_file(self, video_id: str):
        # โหมดเดิม: ชื่อไฟล์ไม่รวมสกุลใน root
        for ext in VIDEO_EXTS:
            f = self.video_folder / f"{video_id}{ext}"
            if f.exists():
                return f
        return None

    def create_web_optimized_version_from_file(self, input_file: Path, video_key: str, make_hls=True):
        """ประมวลผลจากไฟล์ที่ระบุ (รองรับ relpath)"""
        input_file = Path(input_file)
        if not input_file.exists():
            raise FileNotFoundError(str(input_file))

        out_dir = self.processed_folder / video_key
        (out_dir / 'mp4').mkdir(parents=True, exist_ok=True)
        if make_hls:
            (out_dir / 'hls').mkdir(parents=True, exist_ok=True)

        qualities = [
            {'name': '480p',  'resolution': '854x480',   'video_bitrate': '1000k', 'audio_bitrate': '96k'},
            {'name': '720p',  'resolution': '1280x720',  'video_bitrate': '2500k', 'audio_bitrate': '128k'},
            {'name': '1080p', 'resolution': '1920x1080', 'video_bitrate': '4000k', 'audio_bitrate': '192k'},
        ]

        with self._lock:
            self.processing_status[video_key] = 'processing'

        try:
            # 1) MP4 ต่อความละเอียด
            for q in qualities:
                mp4_out = out_dir / 'mp4' / f"{q['name']}.mp4"
                cmd = [
                    self.ffmpeg_path, '-y',
                    '-i', str(input_file),
                    '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
                    '-b:v', q['video_bitrate'],
                    '-maxrate', q['video_bitrate'],
                    '-bufsize', str(int(q['video_bitrate'].replace('k', '')) * 2) + 'k',
                    '-s', q['resolution'],
                    '-c:a', 'aac', '-b:a', q['audio_bitrate'],
                    '-movflags', '+faststart',
                    str(mp4_out)
                ]
                print(f"[MP4] {video_key} - {q['name']}")
                p = subprocess.run(cmd, capture_output=True, text=True)
                if p.returncode != 0:
                    print(f"FFmpeg MP4 error {q['name']}: {p.stderr}")

            # 2) HLS (optional)
            if make_hls:
                master_path = out_dir / 'hls' / 'master.m3u8'
                variants = []
                for q in qualities:
                    v_dir = out_dir / 'hls' / q['name']
                    v_dir.mkdir(parents=True, exist_ok=True)
                    hlscmd = [
                        self.ffmpeg_path, '-y',
                        '-i', str(input_file),
                        '-c:v', 'libx264', '-preset', 'medium', '-crf', '23',
                        '-b:v', q['video_bitrate'],
                        '-maxrate', q['video_bitrate'],
                        '-bufsize', str(int(q['video_bitrate'].replace('k', '')) * 2) + 'k',
                        '-s', q['resolution'],
                        '-c:a', 'aac', '-b:a', q['audio_bitrate'],
                        '-hls_time', str(HLS_SEGMENT_SECONDS),
                        '-hls_playlist_type', 'vod',
                        '-hls_flags', 'independent_segments',
                        '-hls_segment_filename', str(v_dir / "seg_%05d.ts"),
                        str(v_dir / 'index.m3u8')
                    ]
                    print(f"[HLS] {video_key} - {q['name']}")
                    p2 = subprocess.run(hlscmd, capture_output=True, text=True)
                    if p2.returncode != 0:
                        print(f"FFmpeg HLS error {q['name']}: {p2.stderr}")
                        continue
                    bw = int(q['video_bitrate'].replace('k', '')) * 1000 + 128000
                    variants.append({
                        'name': q['name'],
                        'bandwidth': bw,
                        'playlist': f"{q['name']}/index.m3u8",
                        'resolution': q['resolution']
                    })

                if variants:
                    with open(master_path, 'w', encoding='utf-8') as m:
                        m.write("#EXTM3U\n#EXT-X-VERSION:3\n")
                        for v in variants:
                            m.write(f"#EXT-X-STREAM-INF:BANDWIDTH={v['bandwidth']},RESOLUTION={v['resolution']}\n")
                            m.write(f"{v['playlist']}\n")

            with self._lock:
                self.processing_status[video_key] = 'completed'
            print(f"[OK] processed: {video_key}")
            return True

        except Exception as e:
            print(f"[ERR] processing {video_key}: {e}")
            with self._lock:
                self.processing_status[video_key] = 'error'
            return False

    def create_web_optimized_version(self, video_id: str):
        """โหมดเก่า: หาไฟล์จาก root ด้วยชื่อ video_id (ไม่รองรับโฟลเดอร์ย่อย)"""
        input_file = self._find_input_file(video_id)
        if not input_file:
            raise FileNotFoundError(f"ไม่พบไฟล์ {video_id}")
        key = _safe_id_from_relpath(video_id)
        return self.create_web_optimized_version_from_file(input_file, key)

    def get_processing_status(self, key: str):
        return self.processing_status.get(key, 'not_started')

video_processor = VideoProcessor(app.config['VIDEO_FOLDER'], app.config['PROCESSED_FOLDER'])

# ==============================
# ROUTES
# ==============================

@app.route('/healthz')
def healthz():
    return 'ok', 200

# ----- หน้า index (ล็อก Basic Auth) + โหมดโฟลเดอร์ -----
@app.route('/', methods=['GET'])
@app.route('/index', methods=['GET'])
@app.route('/index.html', methods=['GET'])
@app.route('/video-streaming/', methods=['GET'])
@require_index_auth
def index():
    # ไม่ใช้ f-string เพื่อเลี่ยง { } ใน JS/CSS ชนกับ Python
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Video Streaming Platform</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { font-family: Arial, sans-serif; padding: 16px; }
            .row { display:flex; gap:16px; align-items:center; flex-wrap: wrap; }
            .crumbs a { color:#06c; text-decoration:none; }
            .crumbs a:hover { text-decoration:underline; }
            .btn { display:inline-block; padding:6px 10px; border:1px solid #ccc; border-radius:6px; cursor:pointer; background:#fafafa; }
            .btn:active { transform: translateY(1px); }
            .grid { display:grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap:12px; margin-top:12px; }
            .card { border:1px solid #ddd; padding:12px; border-radius:8px; background:#fff; }
            .folder { border:1px dashed #bbb; padding:12px; border-radius:8px; background:#fcfcfc; cursor:pointer; }
            .folder:hover { background:#f3f7ff; }
            code { background:#f5f5f5; padding:2px 6px; border-radius:4px; }
            #toast { position: fixed; top: 12px; right: 12px; background: rgba(0,0,0,.9); color: #fff;
                     padding: 8px 12px; border-radius: 6px; opacity: 0; pointer-events: none; transition: opacity .2s;
                     z-index: 9999; font-size: 14px; }
            #toast.show { opacity: .95; }
            a.copy-link { cursor: pointer; text-decoration: underline; }
        </style>
    </head>
    <body>
        <h1>🎬 Video Streaming Platform</h1>

        <div class="row">
            <div class="crumbs" id="crumbs"></div>
            <button class="btn" id="upBtn">⬆ Up</button>
            <a class="btn" id="openApi" target="_blank">Open JSON</a>
        </div>

        <h2>📁 Folders</h2>
        <div id="folders" class="grid"></div>

        <h2 style="margin-top:20px">🎞 Files in this folder</h2>
        <div id="files" class="grid"></div>

        <div id="toast"></div>

        <script>
            // รองรับทั้งรันตรงและใต้ /video-streaming/
            const prefix = location.pathname.startsWith('/video-streaming/') ? '/video-streaming' : '';

            function toast(msg) {
                const el = document.getElementById('toast');
                el.textContent = msg;
                el.classList.add('show');
                clearTimeout(window.__toastTimer);
                window.__toastTimer = setTimeout(()=> el.classList.remove('show'), 1200);
            }

            function buildCrumbs(cwd) {
                const cont = document.getElementById('crumbs');
                const parts = cwd ? cwd.split('/') : [];
                let html = '<strong>Path:</strong> ';
                let acc = '';
                html += `<a href="#" data-path="">Root</a>`;
                for (let i=0;i<parts.length;i++) {
                    acc += (acc ? '/' : '') + parts[i];
                    html += ' / ' + `<a href="#" data-path="${acc}">${parts[i]}</a>`;
                }
                cont.innerHTML = html;
            }

            function renderFolders(dirs) {
                const el = document.getElementById('folders');
                if (!dirs.length) { el.innerHTML = '<div style="color:#666">— No subfolders —</div>'; return; }
                el.innerHTML = dirs.map(d => `
                    <div class="folder" data-path="${d.relpath}">
                        <div>📁 <strong>${d.name}</strong></div>
                        <div><small><code>${d.relpath}</code></small></div>
                    </div>
                `).join('');
            }

            function renderFiles(files) {
                const el = document.getElementById('files');
                if (!files.length) { el.innerHTML = '<div style="color:#666">— No video files in this folder —</div>'; return; }
                el.innerHTML = files.map(v => {
                    const playerPath = `${prefix}/player_path/${v.relpath}?quality=720p`;
                    const directPath = `${prefix}/api/video_path/${v.relpath}?quality=720p`;
                    const directUrl  = `${location.origin}${directPath}`;
                    return `
                        <div class="card">
                            <div><strong>${v.title}</strong></div>
                            <div><small>relpath: <code>${v.relpath}</code></small></div>
                            <div><small>size: ${v.size} | duration: ${v.duration} | status: ${v.status}</small></div>
                            <div style="margin-top:6px">
                                <a href="${playerPath}" target="_blank">🎥 Player</a> |
                                <a href="${directPath}" class="copy-link" data-url="${directUrl}">🔗 Direct file</a> |
                                <a href="${prefix}/api/process_by_path/${v.relpath}" target="_blank">🔄 Process</a>
                            </div>
                        </div>
                    `;
                }).join('');
            }

            async function load(path='') {
                const url = `${prefix}/api/browse?path=${encodeURIComponent(path)}`;
                document.getElementById('openApi').href = url;
                const res = await fetch(url);
                const data = await res.json();

                buildCrumbs(data.cwd || '');
                renderFolders(data.dirs || []);
                renderFiles(data.files || []);

                const up = document.getElementById('upBtn');
                if (data.parent) { up.disabled = false; up.dataset.path = data.parent; }
                else             { up.disabled = true;  up.dataset.path = ''; }
            }

            document.addEventListener('click', async (e) => {
                // breadcrumb / folder / up
                if (e.target.matches('#upBtn')) {
                    e.preventDefault();
                    await load(e.target.dataset.path || '');
                    return;
                }
                const crumb = e.target.closest('.crumbs a[data-path]');
                if (crumb) {
                    e.preventDefault();
                    await load(crumb.dataset.path || '');
                    return;
                }
                const folder = e.target.closest('.folder[data-path]');
                if (folder) {
                    e.preventDefault();
                    await load(folder.dataset.path || '');
                    return;
                }
                // คัดลอก Direct URL
                const a = e.target.closest('a.copy-link');
                if (a) {
                    e.preventDefault();
                    const url = a.dataset.url || a.href;
                    try {
                        if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(url);
                        else {
                            const ta = document.createElement('textarea'); ta.value = url; document.body.appendChild(ta);
                            ta.select(); document.execCommand('copy'); document.body.removeChild(ta);
                        }
                        toast('Copied to clipboard');
                    } catch (err) { console.error(err); toast('Copy failed'); }
                }
            });

            // โหลด root ตอนเริ่ม
            load('');
        </script>
    </body>
    </html>
    '''

@app.route('/api/debug/paths')
def debug_paths():
    vf = Path(app.config['VIDEO_FOLDER']).resolve()
    pf = Path(app.config['PROCESSED_FOLDER']).resolve()
    exists_v = vf.exists()
    try:
        listing = [p.name for p in vf.iterdir()] if exists_v else []
    except Exception as e:
        listing = [f'!error: {e}']
    return jsonify({
        'video_folder_config': app.config['VIDEO_FOLDER'],
        'video_folder_resolved': str(vf),
        'video_folder_exists': exists_v,
        'video_folder_listing_sample': listing[:50],
        'processed_folder_resolved': str(pf),
    })

@app.route('/api/browse')
def browse():
    """
    คืนรายการเฉพาะภายใต้โฟลเดอร์ที่ระบุ (ไม่ recursive)
    query: ?path=<relpath> (ว่าง = root)
    """
    video_folder = Path(app.config['VIDEO_FOLDER']).resolve()
    req_path = (request.args.get('path', '') or '').strip('/')

    current_dir = (video_folder / req_path).resolve() if req_path else video_folder
    # ป้องกัน traversal
    if not str(current_dir).startswith(str(video_folder)):
        return jsonify({'error': 'forbidden path'}), 403
    if not current_dir.exists() or not current_dir.is_dir():
        return jsonify({'error': f'not a directory: {req_path}'}), 404

    dirs, files = [], []

    # โฟลเดอร์ย่อย
    for p in current_dir.iterdir():
        if p.is_dir():
            dirs.append({
                'name': p.name,
                'relpath': p.relative_to(video_folder).as_posix(),
                'type': 'dir'
            })

    # ไฟล์วิดีโอในโฟลเดอร์นี้
    for p in current_dir.iterdir():
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
            stat = p.stat()
            size_gb = stat.st_size / (1024**3)
            info = video_processor.get_video_info(p)
            duration_str = "Unknown"
            if info and info['duration'] > 0:
                minutes = int(info['duration'] // 60)
                seconds = int(info['duration'] % 60)
                duration_str = f"{minutes}:{seconds:02d}"

            relpath = p.relative_to(video_folder).as_posix()
            key = _safe_id_from_relpath(relpath)
            files.append({
                'id': p.stem,
                'relpath': relpath,
                'filename': p.name,
                'title': p.stem.replace('_', ' ').title(),
                'size': f"{size_gb:.2f} GB",
                'duration': duration_str,
                'path': f"/api/video_path/{relpath}",
                'player_url': f"/player_path/{relpath}",
                'status': video_processor.get_processing_status(key),
                'created': int(stat.st_mtime)
            })

    dirs.sort(key=lambda x: x['name'].lower())
    files.sort(key=lambda x: x['filename'].lower())

    parent_rel = None
    if current_dir != video_folder:
        parent_rel = current_dir.parent.relative_to(video_folder).as_posix()

    return jsonify({
        'cwd': '' if current_dir == video_folder else current_dir.relative_to(video_folder).as_posix(),
        'parent': parent_rel,
        'dirs': dirs,
        'files': files
    })

@app.route('/api/videos')
def list_videos():
    """(ยังคงไว้) ลิสต์ไฟล์วิดีโอทั้งหมดแบบ recursive"""
    videos = []
    video_folder = Path(app.config['VIDEO_FOLDER'])

    if not video_folder.exists():
        return jsonify({'error': f'VIDEO_FOLDER not found: {video_folder}'}), 500

    try:
        for video_file in video_folder.rglob('*'):
            if video_file.is_file() and video_file.suffix.lower() in VIDEO_EXTS:
                stat = video_file.stat()
                size_gb = stat.st_size / (1024**3)
                info = video_processor.get_video_info(video_file)
                duration_str = "Unknown"
                if info and info['duration'] > 0:
                    minutes = int(info['duration'] // 60)
                    seconds = int(info['duration'] % 60)
                    duration_str = f"{minutes}:{seconds:02d}"
                relpath = video_file.relative_to(video_folder).as_posix()
                key = _safe_id_from_relpath(relpath)
                videos.append({
                    'id': video_file.stem,
                    'relpath': relpath,
                    'filename': video_file.name,
                    'title': video_file.stem.replace('_', ' ').title(),
                    'size': f"{size_gb:.2f} GB",
                    'duration': duration_str,
                    'path': f"/api/video_path/{relpath}",
                    'player_url': f"/player_path/{relpath}",
                    'status': video_processor.get_processing_status(key),
                    'created': int(stat.st_mtime)
                })

        videos.sort(key=lambda x: x['created'], reverse=True)
        return jsonify(videos)

    except Exception as e:
        return jsonify({'error': f'เกิดข้อผิดพลาด: {str(e)}'}), 500

@app.route('/api/video/<filename>')
def serve_video_legacy(filename):
    """โหมดเดิม: เฉพาะไฟล์ระดับ root (เพื่อความเข้ากันได้)"""
    video_folder = Path(app.config['VIDEO_FOLDER'])
    video_path = video_folder / secure_filename(filename)
    if not video_path.exists():
        return jsonify({'error': 'ไม่พบไฟล์'}), 404

    key = _safe_id_from_relpath(video_path.stem)
    processed = Path(app.config['PROCESSED_FOLDER']) / key / 'mp4'
    final_path = None
    quality = request.args.get('quality')
    if quality:
        cand = processed / f"{quality}.mp4"
        if cand.exists():
            final_path = cand

    if final_path is None:
        for q in ['720p', '480p', '1080p']:
            cand = processed / f"{q}.mp4"
            if cand.exists():
                final_path = cand
                break

    if final_path is None:
        final_path = video_path

    return send_video_with_range(final_path)

@app.route('/api/video_path/<path:relpath>')
def serve_video_by_path(relpath):
    """เล่นไฟล์ตาม relpath (รองรับโฟลเดอร์ย่อย)"""
    video_folder = Path(app.config['VIDEO_FOLDER'])
    video_path = (video_folder / relpath).resolve()

    # ป้องกัน path traversal
    if not str(video_path).startswith(str(video_folder.resolve())):
        return jsonify({'error': 'forbidden path'}), 403
    if not video_path.exists():
        return jsonify({'error': 'ไม่พบไฟล์'}), 404

    # ถ้ามีไฟล์แปลงแล้วให้ใช้ หรือเลือกจาก ?quality=
    key = _safe_id_from_relpath(relpath)
    processed = Path(app.config['PROCESSED_FOLDER']) / key / 'mp4'

    final_path = None
    quality = request.args.get('quality')
    if quality:
        cand = processed / f"{quality}.mp4"
        if cand.exists():
            final_path = cand

    if final_path is None:
        for q in ['720p', '480p', '1080p']:
            cand = processed / f"{q}.mp4"
            if cand.exists():
                final_path = cand
                break

    if final_path is None:
        final_path = video_path

    return send_video_with_range(final_path)

@app.route('/player/<filename>')
def player_legacy(filename):
    return abort(410)  # ใช้ /player_path/<relpath> แทน

@app.route('/player_path/<path:relpath>')
def player_by_path(relpath):
    """Player แบบ MP4 progressive สำหรับไฟล์ในโฟลเดอร์ย่อย"""
    video_folder = Path(app.config['VIDEO_FOLDER'])
    video_path = (video_folder / relpath).resolve()
    if not str(video_path).startswith(str(video_folder.resolve())):
        return "Forbidden path", 403
    if not video_path.exists():
        return "ไม่พบไฟล์วิดีโอ", 404

    start_time = request.args.get('t', '0')
    autoplay = request.args.get('autoplay', '0') == '1'
    quality = request.args.get('quality', '720p')

    video_url = f"/api/video_path/{relpath}?quality={quality}"
    title = Path(relpath).stem.replace('_', ' ').title()

    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>{title}</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            html,body{{margin:0;height:100%;background:#000}}
            .wrap{{height:100%;display:flex;align-items:center;justify-content:center}}
            video{{width:100%;height:100%;object-fit:contain;background:#000}}
        </style>
    </head>
    <body>
        <div class="wrap">
            <video id="v" controls {"autoplay" if autoplay else ""} preload="metadata" playsinline>
                <source src="{video_url}" type="video/mp4">
                เบราว์เซอร์ของคุณไม่รองรับการเล่นวิดีโอ
            </video>
        </div>
        <script>
            const v = document.getElementById('v');
            const t = {start_time};
            v.addEventListener('loadedmetadata', ()=>{{ if (t>0) v.currentTime = t; }});
            document.addEventListener('contextmenu', e=>e.preventDefault());
        </script>
    </body>
    </html>
    """

@app.route('/hls/<video_key>/<path:subpath>')
def serve_hls(video_key, subpath):
    """เสิร์ฟไฟล์ HLS (master.m3u8, index.m3u8, .ts segments)"""
    base = Path(app.config['PROCESSED_FOLDER']) / video_key / 'hls'
    target = (base / subpath).resolve()
    if not str(target).startswith(str(base.resolve())):
        return abort(403)
    if not target.exists():
        return abort(404)
    ctype = mimetypes.guess_type(str(target))[0] or 'application/octet-stream'
    resp = send_file(str(target), mimetype=ctype, as_attachment=False)
    return _cache_headers(resp, 600)

@app.route('/hlsplayer/<video_key>')
def hls_player(video_key):
    """หน้า player สำหรับ HLS adaptive (ฝังใน H5P ผ่าน iframe ได้)"""
    base = Path(app.config['PROCESSED_FOLDER']) / video_key / 'hls'
    master = base / 'master.m3u8'
    title = video_key.replace('_', ' ').title()
    if not master.exists():
        return f"ยังไม่มี HLS สำหรับ {video_key}.<br>โปรดกด /api/process_by_path/<relpath> ก่อน", 404

    master_url = f"/hls/{video_key}/master.m3u8"
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8"/>
        <title>{title} (HLS)</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            html,body{{margin:0;height:100%;background:#000}}
            .wrap{{height:100%;display:flex;align-items:center;justify-content:center}}
            video{{width:100%;height:100%;object-fit:contain;background:#000}}
        </style>
    </head>
    <body>
        <div class="wrap">
            <video id="video" controls autoplay playsinline></video>
        </div>
        <script src="https://cdn.jsdelivr.net/npm/hls.js@latest"></script>
        <script>
            const video = document.getElementById('video');
            const src = "{master_url}";
            if (video.canPlayType('application/vnd.apple.mpegURL')) {{
                video.src = src; // Safari/iOS เล่น HLS ได้ตรง
            }} else if (window.Hls) {{
                const hls = new Hls();
                hls.loadSource(src);
                hls.attachMedia(video);
            }} else {{
                video.outerHTML = '<div style="color:#fff">เบราว์เซอร์นี้ไม่รองรับ HLS</div>';
            }}
            document.addEventListener('contextmenu', e=>e.preventDefault());
        </script>
    </body>
    </html>
    """

@app.route('/api/process/<video_id>')
def process_video_legacy(video_id):
    """โหมดเดิม: ประมวลผลจากชื่อไฟล์ (root)"""
    try:
        if not video_processor._find_input_file(video_id):
            return jsonify({'error': f'ไม่พบไฟล์ {video_id} ใน root'}), 404

        def bg():
            video_processor.create_web_optimized_version(video_id)

        threading.Thread(target=bg, daemon=True).start()
        return jsonify({'status': 'processing_started', 'video_id': video_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/process_by_path/<path:relpath>')
def process_by_path(relpath):
    """เริ่มประมวลผลไฟล์ตาม relpath (สร้าง MP4 หลายความละเอียด + HLS)"""
    video_folder = Path(app.config['VIDEO_FOLDER'])
    input_path = (video_folder / relpath).resolve()
    if not str(input_path).startswith(str(video_folder.resolve())):
        return jsonify({'error': 'forbidden path'}), 403
    if not input_path.exists():
        return jsonify({'error': f'ไม่พบไฟล์ {relpath}'}), 404

    key = _safe_id_from_relpath(relpath)

    def bg():
        video_processor.create_web_optimized_version_from_file(input_path, key, make_hls=True)

    threading.Thread(target=bg, daemon=True).start()
    return jsonify({'status': 'processing_started', 'video_key': key, 'relpath': relpath})

@app.route('/api/status/<key>')
def get_processing_status(key):
    """เช็คสถานะการประมวลผลตาม key (key = safe_id_from_relpath)"""
    status = video_processor.get_processing_status(key)
    processed_dir = Path(app.config['PROCESSED_FOLDER']) / key
    mp4_dir = processed_dir / 'mp4'
    hls_dir = processed_dir / 'hls'
    av_q = []
    for q in ['480p', '720p', '1080p']:
        if (mp4_dir / f"{q}.mp4").exists():
            av_q.append(q)
    return jsonify({
        'key': key,
        'status': status,
        'available_mp4_qualities': av_q,
        'hls_ready': (hls_dir / 'master.m3u8').exists()
    })

# ==============================
# ERROR HANDLERS
# ==============================
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'ไม่พบหน้าที่ต้องการ'}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({'error': 'เกิดข้อผิดพลาดภายในเซิร์ฟเวอร์'}), 500

# ==============================
# MAIN
# ==============================
if __name__ == '__main__':
    print("🎬 Video Streaming Server Starting...")
    print(f"📁 Video Folder: {app.config['VIDEO_FOLDER']}")
    print(f"⚙️ Processed Folder: {app.config['PROCESSED_FOLDER']}")
    print("🌐 Server: http://localhost:5000")

    # เตือนหาก path เป็น Windows แต่ระบบไม่ใช่ Windows
    if platform.system().lower() != 'windows' and app.config['VIDEO_FOLDER'].startswith(('C:\\', 'D:\\')):
        print(f"⚠️ คุณรันบน {platform.system()} แต่ VIDEO_FOLDER เป็น Windows path: {app.config['VIDEO_FOLDER']}")

    # ทดสอบ FFmpeg
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=10)
        print("✅ FFmpeg is ready" if result.returncode == 0 else "❌ FFmpeg not found - กรุณาติดตั้ง FFmpeg")
    except Exception:
        print("❌ FFmpeg not found - กรุณาติดตั้ง FFmpeg")

    # หลัง Apache แนะนำให้ bind loopback เท่านั้น
    app.run(host='127.0.0.1', port=5000, debug=True, threaded=True)
