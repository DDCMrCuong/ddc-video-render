#!/usr/bin/env python3
"""
DDC Media AI Factory - Video Render Engine (v2: hỗ trợ ảnh + clip video thật)

Mỗi scene trong scenes.json có:
  - image_url  (ảnh: AI sinh hoặc ảnh thật trong Drive)  HOẶC
  - video_url  (clip video thật trong Drive)
  - audio_url  (giọng đọc narration, tuỳ chọn)
  - duration   (giây, tuỳ chọn khi không có audio)

Quy tắc thời lượng:
  - Có audio_url  -> scene dài đúng bằng giọng đọc (clip video được lặp/cắt cho khớp,
                     tiếng gốc của clip bị tắt để không đè giọng đọc)
  - Không audio   -> ảnh: duration hoặc 5s; video: độ dài clip (tối đa 30s), giữ tiếng gốc

Mọi ảnh/clip giữ nguyên tỷ lệ (không méo): đặt vừa khung + nền mờ phóng to phía sau.
Render CẢ 2 bản: output/final_horizontal.mp4 (1920x1080) + output/final_vertical.mp4 (1080x1920).
Logo CheckFarm (assets/logo.png) luôn ở góc trái trên.

Cách dùng: python3 render.py scenes.json output/ [meta.json]
"""
import json
import os
import re
import subprocess
import sys
import urllib.request

FPS = 25
H_WIDTH, H_HEIGHT = 1920, 1080   # ngang - YouTube
V_WIDTH, V_HEIGHT = 1080, 1920   # dọc - TikTok/Facebook
AR = 44100                        # audio chuẩn chung cho mọi đoạn (để nối -c copy)
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
DEFAULT_IMAGE_SEC = 5.0
MAX_CLIP_SEC = 30.0

BRAND_COLORS = {
    "CheckFarm - Nông Nghiệp Xanh": "0x2E7D32",
    "CheckFarm": "0x00695C",
}
DEFAULT_BRAND_COLOR = "0x00695C"

VIDEO_ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
             "-pix_fmt", "yuv420p", "-r", str(FPS)]
AUDIO_ENC = ["-c:a", "aac", "-b:a", "160k", "-ar", str(AR), "-ac", "2"]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("LỆNH LỖI:", " ".join(cmd))
        print(r.stderr[-2500:])
        raise RuntimeError("ffmpeg/ffprobe thất bại")
    return r


# ---------------------------------------------------------------- tải file
def drive_id(url):
    m = re.search(r"[?&]id=([\w-]+)", url) or re.search(r"/d/([\w-]+)", url)
    return m.group(1) if m else None


def _fetch(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=180) as resp, open(dest, "wb") as f:
        ctype = resp.headers.get("Content-Type", "")
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
    return ctype


def download(url, dest):
    """Tải file; với Google Drive file lớn (trang cảnh báo virus) tự chuyển sang drive.usercontent."""
    print(f"  Tải: {url}")
    ctype = _fetch(url, dest)
    is_html = "text/html" in ctype
    if not is_html:
        with open(dest, "rb") as f:
            is_html = f.read(15).lstrip().lower().startswith((b"<!doctype", b"<html"))
    if is_html:
        fid = drive_id(url)
        if not fid:
            raise RuntimeError(f"URL trả về HTML, không phải file media: {url}")
        alt = f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t"
        print(f"  -> Drive trả trang HTML, thử lại: {alt}")
        ctype = _fetch(alt, dest)
        with open(dest, "rb") as f:
            if "text/html" in ctype or f.read(15).lstrip().lower().startswith((b"<!doctype", b"<html")):
                raise RuntimeError(f"Không tải được file Drive {fid} (kiểm tra quyền chia sẻ 'Anyone with link')")
    print(f"     OK {os.path.getsize(dest)/1e6:.1f} MB")


def probe_duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path])
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def has_audio(path):
    r = run(["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", path])
    return bool(r.stdout.strip())


# ---------------------------------------------------------------- dựng khung
def fit_blur_filter(src, w, h, out):
    """Giữ nguyên tỷ lệ: nền = bản phóng to lấp đầy + mờ; trước = bản vừa khung canh giữa."""
    return (
        f"[{src}]split[bgsrc][fgsrc];"
        f"[bgsrc]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        f"gblur=sigma=30,eq=brightness=-0.08[bg];"
        f"[fgsrc]scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[{out}]"
    )


def logo_filter(base, logo_idx, w, out):
    size = int(w * (0.07 if w > 1500 else 0.11))
    margin = int(w * (0.02 if w > 1500 else 0.03))
    return (f"[{logo_idx}:v]scale={size}:-1[lg];"
            f"[{base}][lg]overlay={margin}:{margin}[{out}]")


def render_image_scene(img, audio, duration, w, h, logo, out):
    frames = max(int(round(duration * FPS)), 1)
    inputs = ["-i", img]
    if audio:
        inputs += ["-i", audio]
    else:
        inputs += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", f"anullsrc=r={AR}:cl=stereo"]
    fc = fit_blur_filter("0:v", w, h, "fit") + ";"
    fc += (f"[fit]scale={w*2}:{h*2},zoompan=z='min(zoom+0.0005,1.10)':d={frames}"
           f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={FPS}[kb]")
    last = "kb"
    if logo:
        inputs += ["-i", logo]
        fc += ";" + logo_filter("kb", 2, w, "v")
        last = "v"
    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", fc, "-map", f"[{last}]", "-map", "1:a",
            "-af", f"aresample={AR}", "-t", f"{duration:.3f}"] + VIDEO_ENC + AUDIO_ENC + [out])
    run(cmd)


def render_video_scene(clip, audio, duration, keep_clip_audio, w, h, logo, out):
    inputs = ["-stream_loop", "-1", "-i", clip]
    if audio:
        inputs += ["-i", audio]
        amap = "1:a"
    elif keep_clip_audio:
        amap = "0:a"
    else:
        inputs += ["-f", "lavfi", "-t", f"{duration:.3f}", "-i", f"anullsrc=r={AR}:cl=stereo"]
        amap = "1:a"
    fc = f"[0:v]fps={FPS},setpts=PTS-STARTPTS[src];" + fit_blur_filter("src", w, h, "fit")
    last = "fit"
    if logo:
        logo_idx = 2 if (audio or not keep_clip_audio) else 1
        inputs += ["-i", logo]
        fc += ";" + logo_filter("fit", logo_idx, w, "v")
        last = "v"
    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", fc, "-map", f"[{last}]", "-map", amap,
            "-af", f"aresample={AR}", "-t", f"{duration:.3f}"] + VIDEO_ENC + AUDIO_ENC + [out])
    run(cmd)


def render_brand_card(text, out, w, h, color, duration=2.5):
    text = text.replace("'", "’").replace(":", "\\:")
    fs = max(int(w * 0.06), 36)
    run(["ffmpeg", "-y",
         "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}:d={duration}:r={FPS}",
         "-f", "lavfi", "-i", f"anullsrc=r={AR}:cl=stereo",
         "-vf", f"drawtext=fontfile={FONT_PATH}:text='{text}':fontsize={fs}:fontcolor=white:"
                f"x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=20",
         "-t", str(duration)] + VIDEO_ENC + AUDIO_ENC + [out])


def concat(files, out):
    lst = out + ".list.txt"
    with open(lst, "w") as f:
        for p in files:
            f.write(f"file '{os.path.abspath(p)}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy",
         "-movflags", "+faststart", out])


# ---------------------------------------------------------------- main
def main():
    if len(sys.argv) not in (3, 4):
        print("Dùng: python3 render.py scenes.json output_dir/ [meta.json]")
        sys.exit(1)
    scenes_path, out_dir = sys.argv[1], sys.argv[2]
    meta = {}
    if len(sys.argv) == 4 and os.path.exists(sys.argv[3]):
        with open(sys.argv[3]) as f:
            meta = json.load(f)
    with open(scenes_path) as f:
        scenes = json.load(f)
    scenes = sorted(scenes, key=lambda s: float(s.get("scene_number") or 0))

    render_mode = meta.get("render_mode") or "standard"
    channel = meta.get("channel") or ""
    branded = render_mode == "branded"
    color = BRAND_COLORS.get(channel, DEFAULT_BRAND_COLOR)
    print(f"Render mode: {render_mode} | Kênh: {channel or '(không xác định)'} | {len(scenes)} scene")

    os.makedirs("work", exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "logo.png")
    logo = logo if os.path.exists(logo) else None
    print(f"Logo CheckFarm: {'có' if logo else 'KHÔNG có, bỏ qua'}")

    h_files, v_files = [], []
    if branded:
        render_brand_card(channel or "CheckFarm", "work/intro_h.mp4", H_WIDTH, H_HEIGHT, color)
        render_brand_card(channel or "CheckFarm", "work/intro_v.mp4", V_WIDTH, V_HEIGHT, color)
        h_files.append("work/intro_h.mp4")
        v_files.append("work/intro_v.mp4")

    for i, s in enumerate(scenes, start=1):
        video_url = (s.get("video_url") or "").strip()
        image_url = (s.get("image_url") or "").strip()
        audio_url = (s.get("audio_url") or "").strip()
        kind = "VIDEO" if video_url else "ẢNH"
        print(f"Scene {i}/{len(scenes)} [{kind}]")
        if not video_url and not image_url:
            raise RuntimeError(f"Scene {s.get('scene_number')} không có image_url/video_url")

        audio = None
        if audio_url:
            audio = f"work/s{i}_audio"
            download(audio_url, audio)

        h_out, v_out = f"work/s{i}_h.mp4", f"work/s{i}_v.mp4"
        if video_url:
            clip = f"work/s{i}_clip"
            download(video_url, clip)
            clip_len = probe_duration(clip) or DEFAULT_IMAGE_SEC
            if audio:
                duration, keep = probe_duration(audio), False
            else:
                duration = float(s.get("duration") or min(clip_len, MAX_CLIP_SEC))
                keep = has_audio(clip)
            print(f"  clip {clip_len:.1f}s -> scene {duration:.1f}s")
            render_video_scene(clip, audio, duration, keep, H_WIDTH, H_HEIGHT, logo, h_out)
            render_video_scene(clip, audio, duration, keep, V_WIDTH, V_HEIGHT, logo, v_out)
        else:
            img = f"work/s{i}_img"
            download(image_url, img)
            duration = probe_duration(audio) if audio else float(s.get("duration") or DEFAULT_IMAGE_SEC)
            print(f"  ảnh -> scene {duration:.1f}s")
            render_image_scene(img, audio, duration, H_WIDTH, H_HEIGHT, logo, h_out)
            render_image_scene(img, audio, duration, V_WIDTH, V_HEIGHT, logo, v_out)
        h_files.append(h_out)
        v_files.append(v_out)

    if branded:
        cta = (channel or "CheckFarm") + "\nTheo dõi để xem thêm"
        render_brand_card(cta, "work/outro_h.mp4", H_WIDTH, H_HEIGHT, color)
        render_brand_card(cta, "work/outro_v.mp4", V_WIDTH, V_HEIGHT, color)
        h_files.append("work/outro_h.mp4")
        v_files.append("work/outro_v.mp4")

    print("Nối bản NGANG...")
    concat(h_files, os.path.join(out_dir, "final_horizontal.mp4"))
    print("Nối bản DỌC...")
    concat(v_files, os.path.join(out_dir, "final_vertical.mp4"))
    print("Hoàn tất cả 2 bản.")


if __name__ == "__main__":
    main()
