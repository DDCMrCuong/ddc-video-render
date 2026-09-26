#!/usr/bin/env python3
"""
DDC Media AI Factory - Video Render Engine
Đọc scenes.json (danh sách scene: image_url, audio_url), tải về,
áp hiệu ứng Ken Burns cho từng ảnh đồng bộ với độ dài audio, rồi nối
tất cả thành video MP4 hoàn chỉnh.

Render CẢ 2 định dạng từ cùng 1 bộ ảnh/audio:
- Ngang 16:9 1920x1080 (YouTube)           -> output/final_horizontal.mp4
- Dọc  9:16 1080x1920 (TikTok/Facebook)     -> output/final_vertical.mp4
  (ảnh gốc giữ nguyên, không bị cắt mất chi tiết - nền mờ phóng to lấp
  đầy phần trên/dưới, kiểu Instagram Reels/TikTok chuẩn)

Cách dùng: python3 render.py scenes.json output/
scenes.json format:
[
  {"scene_number": 1, "image_url": "https://...", "audio_url": "https://..."},
  {"scene_number": 2, "image_url": "https://...", "audio_url": "https://..."}
]
"""
import json
import subprocess
import sys
import os
import urllib.request

FPS = 25
H_WIDTH, H_HEIGHT = 1920, 1080   # ngang - YouTube
V_WIDTH, V_HEIGHT = 1080, 1920   # dọc - TikTok/Facebook
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# Màu thương hiệu theo kênh (cả 2 kênh cùng hệ sinh thái CheckFarm)
BRAND_COLORS = {
    "CheckFarm - Nông Nghiệp Xanh": "0x2E7D32",   # xanh lá - chủ đề hữu cơ/xanh
    "CheckFarm": "0x00695C",                       # xanh teal - công nghệ/chuyên nghiệp
}
DEFAULT_BRAND_COLOR = "0x00695C"

# Nhãn ngắn cho watermark góc màn hình (tên đầy đủ dùng cho intro/outro)
WATERMARK_LABELS = {
    "CheckFarm - Nông Nghiệp Xanh": "CheckFarm",
    "CheckFarm": "CheckFarm",
}


def download(url, dest):
    print(f"  Tải: {url} -> {dest}")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        f.write(resp.read())


def get_audio_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True
    )
    return float(out.stdout.strip())


def render_scene_horizontal(image_path, audio_path, out_path, duration):
    """Ken Burns ngang 16:9, giống bản gốc."""
    frames = max(int(duration * FPS), FPS)
    zoompan = (
        f"scale={H_WIDTH*2}:{H_HEIGHT*2},"
        f"zoompan=z='min(zoom+0.0006,1.15)':d={frames}:s={H_WIDTH}x{H_HEIGHT}:fps={FPS}"
    )
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", image_path, "-i", audio_path,
        "-filter_complex", f"[0:v]{zoompan}[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-t", str(duration),
        "-shortest", out_path
    ]
    print(f"  Render scene NGANG: {out_path} ({duration:.1f}s)")
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def render_scene_vertical(image_path, audio_path, out_path, duration):
    """
    Ken Burns dọc 9:16 cho TikTok/Facebook - ảnh gốc (16:9) được:
    - Lớp nền: phóng to lấp đầy khung dọc + làm mờ mạnh (che phần thừa)
    - Lớp trước: giữ nguyên toàn bộ ảnh gốc, canh giữa, áp Ken Burns
    Không cắt mất chi tiết ảnh gốc như crop thẳng sẽ làm.
    """
    frames = max(int(duration * FPS), FPS)
    zoompan_fg = (
        f"scale={V_WIDTH*2}:-2,"
        f"zoompan=z='min(zoom+0.0006,1.12)':d={frames}:s={V_WIDTH}x{round(V_WIDTH*9/16)}:fps={FPS}"
    )
    filter_complex = (
        f"[0:v]scale={V_WIDTH}:{V_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={V_WIDTH}:{V_HEIGHT},gblur=sigma=30,eq=brightness=-0.05[bg];"
        f"[1:v]{zoompan_fg}[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-loop", "1", "-i", image_path,
        "-i", audio_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "2:a",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-t", str(duration),
        "-shortest", out_path
    ]
    print(f"  Render scene DỌC: {out_path} ({duration:.1f}s)")
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def add_watermark(in_path, out_path, channel_text, width, height):
    """Chèn watermark tên kênh mờ ở góc dưới phải, xuyên suốt video."""
    fontsize = max(int(width * 0.022), 20)
    margin = int(width * 0.03)
    drawtext = (
        f"drawtext=fontfile={FONT_PATH}:text='{channel_text}':"
        f"fontsize={fontsize}:fontcolor=white@0.55:"
        f"x=w-tw-{margin}:y=h-th-{margin}:"
        f"box=1:boxcolor=black@0.25:boxborderw=10"
    )
    cmd = [
        "ffmpeg", "-y", "-i", in_path,
        "-vf", drawtext,
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        out_path
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def render_brand_card(text_lines, out_path, width, height, bg_color, duration=2.5):
    """Thẻ thương hiệu (intro/outro): nền màu thương hiệu + chữ căn giữa + audio câm."""
    text = text_lines.replace("'", "\u2019")
    fontsize = max(int(width * 0.06), 36)
    drawtext = (
        f"drawtext=fontfile={FONT_PATH}:text='{text}':"
        f"fontsize={fontsize}:fontcolor=white:"
        f"x=(w-text_w)/2:y=(h-text_h)/2:line_spacing=20"
    )
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c={bg_color}:s={width}x{height}:d={duration}:r={FPS}",
        "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=stereo",
        "-vf", drawtext,
        "-t", str(duration),
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "160k",
        "-shortest", out_path
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def concat_scenes(scene_files, out_path):
    list_path = out_path + ".list.txt"
    with open(list_path, "w") as f:
        for sf in scene_files:
            f.write(f"file '{os.path.abspath(sf)}'\n")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
           "-c", "copy", out_path]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def main():
    if len(sys.argv) not in (3, 4):
        print("Dùng: python3 render.py scenes.json output_dir/ [meta.json]")
        sys.exit(1)

    scenes_json_path, output_dir = sys.argv[1], sys.argv[2]
    meta_json_path = sys.argv[3] if len(sys.argv) == 4 else None

    with open(scenes_json_path) as f:
        scenes = json.load(f)

    render_mode = "standard"
    channel = ""
    if meta_json_path and os.path.exists(meta_json_path):
        with open(meta_json_path) as f:
            meta = json.load(f)
        render_mode = meta.get("render_mode") or "standard"
        channel = meta.get("channel") or ""
    branded = render_mode == "branded"
    brand_color = BRAND_COLORS.get(channel, DEFAULT_BRAND_COLOR)
    print(f"Render mode: {render_mode} | Kênh: {channel or '(không xác định)'}")

    os.makedirs("work", exist_ok=True)
    os.makedirs(output_dir, exist_ok=True)

    h_files, v_files = [], []

    if branded:
        print("Tạo thẻ intro thương hiệu...")
        intro_h = "work/intro_h.mp4"
        intro_v = "work/intro_v.mp4"
        render_brand_card(channel or "CheckFarm", intro_h, H_WIDTH, H_HEIGHT, brand_color)
        render_brand_card(channel or "CheckFarm", intro_v, V_WIDTH, V_HEIGHT, brand_color)
        h_files.append(intro_h)
        v_files.append(intro_v)

    for i, scene in enumerate(scenes, start=1):
        print(f"Scene {i}/{len(scenes)}")
        img_path = f"work/scene{i}.jpg"
        audio_path = f"work/scene{i}.mp3"
        h_out = f"work/scene{i}_h.mp4"
        v_out = f"work/scene{i}_v.mp4"

        download(scene["image_url"], img_path)
        download(scene["audio_url"], audio_path)

        duration = get_audio_duration(audio_path)
        render_scene_horizontal(img_path, audio_path, h_out, duration)
        render_scene_vertical(img_path, audio_path, v_out, duration)

        if branded and channel:
            h_wm = f"work/scene{i}_h_wm.mp4"
            v_wm = f"work/scene{i}_v_wm.mp4"
            watermark_text = WATERMARK_LABELS.get(channel, channel)
            add_watermark(h_out, h_wm, watermark_text, H_WIDTH, H_HEIGHT)
            add_watermark(v_out, v_wm, watermark_text, V_WIDTH, V_HEIGHT)
            h_out, v_out = h_wm, v_wm

        h_files.append(h_out)
        v_files.append(v_out)

    if branded:
        print("Tạo thẻ outro thương hiệu...")
        outro_h = "work/outro_h.mp4"
        outro_v = "work/outro_v.mp4"
        cta = (channel or "CheckFarm") + "\nTheo dõi để xem thêm"
        render_brand_card(cta, outro_h, H_WIDTH, H_HEIGHT, brand_color)
        render_brand_card(cta, outro_v, V_WIDTH, V_HEIGHT, brand_color)
        h_files.append(outro_h)
        v_files.append(outro_v)

    print("Nối bản NGANG...")
    concat_scenes(h_files, os.path.join(output_dir, "final_horizontal.mp4"))
    print("Nối bản DỌC...")
    concat_scenes(v_files, os.path.join(output_dir, "final_vertical.mp4"))
    print("Hoàn tất cả 2 bản.")


if __name__ == "__main__":
    main()
