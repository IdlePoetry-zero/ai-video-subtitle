"""Build reference captions into video pixels. The application never reads this reference."""
from pathlib import Path
import json
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from worker.core import ffmpeg_path, ass_time

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "artifacts/fixtures"
CAPTIONS = [
    (2, 5, "Welcome to the subtitle studio."),
    (7, 10, "Today we will translate a video."),
    (12, 15, "We need 12 samples, not 20."),
    (17, 20, "Keep the original timing."),
    (21.2, 21.7, "This is a short caption."),
    (23, 25, "Hello again."),
    (27, 29, "Hello again."),
    (31, 35, "Read both lines.\nThey belong together."),
    (37, 40, "The background keeps moving."),
    (42, 45, "Do not overwrite my edits."),
    (46, 49, "Save the project before exporting."),
    (51, 54, "Check the sound and the picture."),
    (56, 59, "Thank you for watching."),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ass = """[Script Info]
ScriptType: v4.00+
PlayResX: 1280
PlayResY: 720
[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Caption,Arial,40,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,2,20,20,42,1
Style: Title,Arial,34,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,8,20,20,20,1
[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
Dialogue: 0,0:00:00.00,0:01:00.00,Title,,0,0,0,,SUBTITLE STUDIO - outside the caption region
"""
    for start, end, text in CAPTIONS:
        encoded = text.replace("\n", r"\N")
        ass += f"Dialogue: 1,{ass_time(start)},{ass_time(end)},Caption,,0,0,0,,{encoded}\n"
    (OUT / "fixture.ass").write_text(ass)
    (OUT / "reference.json").write_text(json.dumps([{"start": a, "end": b, "text": t} for a, b, t in CAPTIONS], indent=2))
    command = [ffmpeg_path(), "-hide_banner", "-y", "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=60", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=60",
               "-vf", "drawbox=x=0:y=545:w=iw:h=165:color=black@0.90:t=fill,ass=fixture.ass", "-c:v", "libx264", "-crf", "22", "-preset", "fast", "-c:a", "aac", "-movflags", "+faststart", "硬字幕 测试视频.mp4"]
    with (OUT / "generate.log").open("w") as log:
        subprocess.run(command, cwd=OUT, stdout=log, stderr=log, check=True)
    # Uneven presentation timestamps; deliberately no constant fps arithmetic.
    command = [ffmpeg_path(), "-hide_banner", "-y", "-i", str(OUT / "硬字幕 测试视频.mp4"), "-t", "12", "-vf", "select='if(lt(t,6),not(mod(n,2)),not(mod(n,3)))'", "-fps_mode", "vfr", "-c:v", "libx264", "-preset", "fast", "-an", str(OUT / "variable-timestamps.mp4")]
    with (OUT / "generate-vfr.log").open("w") as log:
        subprocess.run(command, stdout=log, stderr=log, check=True)
    print(OUT / "硬字幕 测试视频.mp4")


if __name__ == "__main__":
    main()
