"""Assemble the ORBIT Search demo video.

Visuals are real application captures (cropped to 16:9) plus natively rendered
1920x1080 code/card frames. Audio is the per-sentence narration built by
make_narration.py over a quiet ambient bed. Captions are burned from the same
timeline that drives the audio, so they cannot drift.
"""
import json
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
FRAMES = BASE / "frames"
CAPTIONS = BASE / "captions"
BUILD = BASE / "build"
BUILD.mkdir(exist_ok=True)
FFMPEG = BASE / "bin" / "ffmpeg"

FPS = 30
OUT = BASE / "ORBIT_Search_SerpApi_Hackathon_Demo.mp4"
TOTAL = 121.8

# (start, end, image, crop_y or None when the source is already 1920x1080)
SHOTS = [
    (0.0, 7.4, "R_card_title.png", None),
    (7.4, 16.3, "01_landing_full.png", 0),
    (16.3, 20.5, "02_question_filled.png", 0),
    (20.5, 25.0, "03_loading.png", 0),
    (25.0, 30.1, "01_landing_full.png", 480),
    (30.1, 36.5, "04_queries_coverage.png", 0),
    (36.5, 44.7, "10_source_cards_closeup.png", 100),
    (44.7, 54.0, "19_s4_answer.png", 0),
    (54.0, 63.2, "19_s4_answer.png", 560),
    (63.2, 71.5, "07_degraded_banner.png", 0),
    (71.5, 80.8, "08_footer_honesty.png", 880),
    (80.8, 85.5, "R_code_main.png", None),
    (85.5, 89.5, "R_code_search.png", None),
    (89.5, 93.5, "R_code_research_degraded.png", None),
    (93.5, 96.6, "R_tree.png", None),
    (96.6, 100.0, "R_tests.png", None),
    (100.0, TOTAL, "R_card_closing.png", None),
]

CROP_W, CROP_H = 1034, 581


def build_clips() -> list[Path]:
    clips = []
    for i, (start, end, name, crop_y) in enumerate(SHOTS, 1):
        src = FRAMES / name
        if not src.exists():
            raise SystemExit(f"missing frame: {src}")
        dur = end - start
        frames = round(dur * FPS)
        pre = (
            f"crop={CROP_W}:{CROP_H}:0:{crop_y},scale=1920:1080"
            if crop_y is not None
            else "null"
        )
        vf = (
            f"{pre},"
            f"zoompan=z='min(1+0.055*on/{frames},1.055)'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s=1920x1080:fps={FPS},format=yuv420p"
        )
        clip = BUILD / f"clip_{i:02d}.mp4"
        subprocess.run(
            [
                str(FFMPEG), "-y", "-loglevel", "error", "-i", str(src),
                "-vf", vf, "-t", f"{dur:.3f}", "-r", str(FPS),
                "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                "-pix_fmt", "yuv420p", str(clip),
            ],
            check=True,
        )
        clips.append(clip)
        print(f"clip {i:02d} {name} {dur:.1f}s")
    return clips


def concat(clips: list[Path]) -> Path:
    listing = BUILD / "concat.txt"
    listing.write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
    video = BUILD / "video_silent.mp4"
    subprocess.run(
        [
            str(FFMPEG), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
            "-i", str(listing), "-c", "copy", str(video),
        ],
        check=True,
    )
    return video


def ass_time(t: float) -> str:
    cs = round(t * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def chunks(sentence: str, limit: int = 9) -> list[str]:
    words, out, current = sentence.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate.split()) > limit and current:
            out.append(current)
            current = word
        else:
            current = candidate
    if current:
        out.append(current)
    # Keep caption lines balanced instead of a long chunk plus a stub.
    if len(out) > 1 and len(out[-1].split()) < 4:
        mid = len(" ".join(out).split()) // 2
        allw = " ".join(out).split()
        out = [" ".join(allw[:mid]), " ".join(allw[mid:])]
    return out


def wrap(piece: str, limit: int = 46) -> str:
    if len(piece) <= limit:
        return piece
    words = piece.split()
    best, diff = 1, 99
    for i in range(1, len(words)):
        left, right = " ".join(words[:i]), " ".join(words[i:])
        if len(left) <= limit and len(right) <= limit:
            d = abs(len(left) - len(right))
            if d < diff:
                best, diff = i, d
    return " ".join(words[:best]) + "\\N" + " ".join(words[best:])


def write_captions() -> Path:
    timeline = json.loads((CAPTIONS / "timeline.json").read_text())
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,Helvetica,52,&H00FFFFFF,&H00FFFFFF,&H0010141c,&H96000000,0,0,0,0,100,100,0,0,3,14,2,2,90,90,64,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for entry in timeline:
        pieces = chunks(entry["text"])
        weights = [len(p) + 1 for p in pieces]
        span = entry["dur"]
        t = entry["start"]
        for piece, weight in zip(pieces, weights):
            piece_dur = span * weight / sum(weights)
            display = wrap(piece)
            lines.append(
                f"Dialogue: 0,{ass_time(t)},{ass_time(t + piece_dur - 0.06)},Caption,,0,0,0,,{display}"
            )
            t += piece_dur
    path = CAPTIONS / "captions.ass"
    path.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    print(f"captions: {len(lines)} events")
    return path


def build_narration(total: float) -> Path:
    timeline = json.loads((CAPTIONS / "timeline.json").read_text())
    args = [str(FFMPEG), "-y", "-loglevel", "error"]
    for entry in timeline:
        args += ["-i", str(BASE / entry["file"])]
    filters = []
    for i, entry in enumerate(timeline):
        delay = round(entry["start"] * 1000)
        filters.append(f"[{i}:a]adelay={delay}|{delay}[n{i}]")
    mixed = "".join(f"[n{i}]" for i in range(len(timeline)))
    filters.append(
        f"{mixed}amix=inputs={len(timeline)}:normalize=0,"
        "loudnorm=I=-15:TP=-1.5:LRA=11,apad[audio]"
    )
    out = BUILD / "narration.wav"
    args += [
        "-filter_complex", ";".join(filters), "-map", "[audio]",
        "-t", f"{total}", "-ar", "48000", "-ac", "2", str(out),
    ]
    subprocess.run(args, check=True)
    return out


def build_music(total: float) -> Path:
    out = BUILD / "music.wav"
    d = int(total) + 5
    pad = (
        f"sine=frequency=110:duration={d},"
        "tremolo=f=0.11:d=0.35[a];"
        f"sine=frequency=164.81:duration={d}[b];"
        f"sine=frequency=220:duration={d}[c];"
        f"sine=frequency=277.18:duration={d}[d];"
        "[a][b][c][d]amix=inputs=4:normalize=1,"
        "lowpass=f=900,highpass=f=70,"
        f"volume=0.055,"
        f"afade=t=in:st=0:d=3,afade=t=out:st={total - 4}:d=4,"
        f"apad=whole_dur={total}"
    )
    subprocess.run(
        [
            str(FFMPEG), "-y", "-loglevel", "error", "-f", "lavfi", "-i", pad,
            "-t", f"{total}", "-ar", "48000", "-ac", "2", str(out),
        ],
        check=True,
    )
    return out


def finalize(video: Path, narration: Path, music: Path, captions: Path) -> None:
    subprocess.run(
        [
            str(FFMPEG), "-y", "-loglevel", "error",
            "-i", str(video), "-i", str(narration), "-i", str(music),
            "-filter_complex",
            (
                f"[1:a][2:a]amix=inputs=2:normalize=0,"
                f"alimiter=limit=0.9,"
                f"afade=t=in:st=0:d=0.6,afade=t=out:st={TOTAL - 1.2}:d=1.2[aout];"
                f"[0:v]subtitles={captions}:fontsdir=/System/Library/Fonts,"
                "format=yuv420p[vout]"
            ),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "slow", "-crf", "19",
            "-profile:v", "high", "-level", "4.1",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", "-shortest", str(OUT),
        ],
        check=True,
    )


if __name__ == "__main__":
    clips = build_clips()
    video = concat(clips)
    narration = build_narration(TOTAL)
    music = build_music(TOTAL)
    captions = write_captions()
    finalize(video, narration, music, captions)
    print("wrote", OUT)
