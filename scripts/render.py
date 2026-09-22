#!/usr/bin/env python3
"""
DDC Media AI Factory - Video Render Engine
Đọc scenes.json (danh sách scene: image_url, audio_url), tải về,
áp hiệu ứng Ken Burns cho từng ảnh đồng bộ với độ dài audio, rồi nối
tất cả thành 1 video MP4 hoàn chỉnh (final.mp4).

Cách dùng: python3 render.py scenes.json output/final.mp4
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
WIDTH = 1920
HEIGHT = 1080


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


def render_scene(image_path, audio_path, out_path, duration):
    frames = max(int(duration * FPS), FPS)
    # Ken Burns: zoom chậm dần từ 1.0 -> 1.15 trong suốt cảnh
    zoompan = (
        f"scale={WIDTH*2}:{HEIGHT*2},"
        f"zoompan=z='min(zoom+0.0006,1.15)':d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
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
    print(f"  Render scene: {out_path} ({duration:.1f}s)")
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def concat_scenes(scene_files, out_path):
    list_path = "concat_list.txt"
    with open(list_path, "w") as f:
        for sf in scene_files:
            f.write(f"file '{os.path.abspath(sf)}'\n")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
           "-c", "copy", out_path]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def main():
    if len(sys.argv) != 3:
        print("Dùng: python3 render.py scenes.json output/final.mp4")
        sys.exit(1)

    scenes_json_path, output_path = sys.argv[1], sys.argv[2]
    with open(scenes_json_path) as f:
        scenes = json.load(f)

    os.makedirs("work", exist_ok=True)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    scene_files = []
    for i, scene in enumerate(scenes, start=1):
        print(f"Scene {i}/{len(scenes)}")
        img_path = f"work/scene{i}.jpg"
        audio_path = f"work/scene{i}.mp3"
        out_path = f"work/scene{i}_rendered.mp4"

        download(scene["image_url"], img_path)
        download(scene["audio_url"], audio_path)

        duration = get_audio_duration(audio_path)
        render_scene(img_path, audio_path, out_path, duration)
        scene_files.append(out_path)

    print("Nối tất cả scene...")
    concat_scenes(scene_files, output_path)
    print(f"Hoàn tất: {output_path}")


if __name__ == "__main__":
    main()
