"""Generate per-sentence narration with macOS `say` and build the caption timeline.

Narration text is the verbatim storyboard script. Splitting per sentence gives
exact audio durations, which subtitle timing is derived from.
"""
import json
import re
import subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
AUDIO = BASE / "audio"
CAPTIONS = BASE / "captions"
AUDIO.mkdir(exist_ok=True)
CAPTIONS.mkdir(exist_ok=True)

VOICE = "Samantha"
RATE = 172
SENTENCE_GAP = 0.40
SCENE_GAP = 1.05

SCENES = {
    1: (
        "Researching a complex question often means opening dozens of tabs, "
        "repeating searches, and manually connecting evidence. "
        "ORBIT Search brings this process into one research workspace, combining "
        "live web search with AI-assisted analysis and source citations."
    ),
    2: (
        "Instead of relying on a single search query, ORBIT Search approaches a "
        "question as a research task. "
        "It identifies useful search angles, collects relevant web evidence, and "
        "organizes the results for review."
    ),
    3: (
        "SerpApi provides the web search results. "
        "ORBIT Search collects evidence across the executed queries, reduces "
        "duplicate sources, and presents the original links so users can inspect "
        "the underlying material themselves."
    ),
    4: (
        "When Gemini is available, ORBIT Search uses AI-assisted planning and "
        "synthesis to turn retrieved evidence into a more useful research answer. "
        "Citations connect the answer to retrieved sources, allowing users to "
        "investigate the evidence instead of treating the output as an "
        "unquestionable black box."
    ),
    5: (
        "Research tools also need to handle failures responsibly. "
        "If Gemini synthesis is unavailable, ORBIT Search can preserve the "
        "collected evidence and source information rather than inventing an "
        "answer. "
        "This keeps the research workflow useful while clearly communicating the "
        "limitation."
    ),
    6: (
        "Under the hood, ORBIT Search uses FastAPI for its backend, SerpApi for "
        "web search, and Gemini for AI-assisted research. "
        "The application separates search, research orchestration, and the "
        "browser interface, with automated tests covering important behavior and "
        "failure scenarios."
    ),
    7: (
        "ORBIT Search is designed to make web research more organized, "
        "inspectable, and resilient. "
        "By combining live search, AI-assisted synthesis, and accessible source "
        "evidence, it helps users move from a question toward a better-informed "
        "understanding. "
        "This is ORBIT Search, built for the SerpApi India Hackathon."
    ),
}


def sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=\.)\s+", text) if p.strip()]


def duration(path: Path) -> float:
    out = subprocess.run(
        ["afinfo", str(path)], capture_output=True, text=True, check=True
    ).stdout
    for line in out.splitlines():
        if line.strip().startswith("estimated duration"):
            return float(line.split(":")[1].strip().split()[0])
    raise RuntimeError(f"no duration for {path}")


timeline = []
t = 0.0
for scene, text in SCENES.items():
    for i, sentence in enumerate(sentences(text)):
        stem = f"s{scene}_{i + 1}"
        aiff, wav = AUDIO / f"{stem}.aiff", AUDIO / f"{stem}.wav"
        if not wav.exists() or wav.stat().st_size == 0:
            subprocess.run(
                ["say", "-v", VOICE, "-r", str(RATE), "-o", str(aiff), sentence],
                check=True,
            )
            subprocess.run(
                [
                    str(BASE / "bin" / "ffmpeg"), "-y", "-loglevel", "error",
                    "-i", str(aiff), "-ar", "48000", "-ac", "1", str(wav),
                ],
                check=True,
            )
        dur = duration(wav)
        timeline.append(
            {
                "scene": scene,
                "index": i + 1,
                "text": sentence,
                "file": str(wav.relative_to(BASE)),
                "start": round(t, 3),
                "dur": round(dur, 3),
                "end": round(t + dur, 3),
            }
        )
        t += dur + (SCENE_GAP if i == len(sentences(text)) - 1 else SENTENCE_GAP)
        print(f"{stem}: {dur:5.2f}s  {sentence[:60]}...")

total = t - (SCENE_GAP if True else 0)
print(f"\ntotal narration: {int(total // 60)}m {total % 60:04.1f}s")
(CAPTIONS / "timeline.json").write_text(json.dumps(timeline, indent=2), encoding="utf-8")
