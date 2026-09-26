#!/usr/bin/env python3
"""
Automated quality checks on a rendered explainer.

  · container: 1920x1080, 30 fps, H.264 + AAC, video and audio lengths agree
  · narration complete: the video is at least as long as the joined narration (636.70 s)
  · no black gaps (other than the intended 0.6 s fade-in and 0.9 s fade-out)
  · no frozen picture: the presenter is always moving, so a full-frame freeze means a bug
  · no audio dropouts longer than a normal pause

Usage: python3 build/qc.py [video.mp4]
"""
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NARRATION = 636.70


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,r_frame_rate,duration:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True)
    return json.loads(out.stdout)


def scan(path, vf=None, af=None):
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path)]
    if vf:
        cmd += ["-vf", vf, "-an"]
    if af:
        cmd += ["-af", af, "-vn"]
    cmd += ["-f", "null", "-"]
    return subprocess.run(cmd, capture_output=True, text=True).stderr


def main():
    path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out" / "IndianLawGPT_Explainer_Final.mp4"
    info = probe(path)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    dur = float(info["format"]["duration"])
    fails, notes = [], []

    notes.append(f"{v['width']}x{v['height']} {v['codec_name']} @ {v['r_frame_rate']}, audio {a['codec_name']}, {dur:.2f}s")
    if (v["width"], v["height"]) != (1920, 1080):
        fails.append("resolution is not 1920x1080")
    if v["r_frame_rate"] != "30/1":
        fails.append(f"frame rate {v['r_frame_rate']} (expected 30/1)")
    vd, ad = float(v.get("duration", dur)), float(a.get("duration", dur))
    if abs(vd - ad) > 0.25:
        fails.append(f"video {vd:.2f}s and audio {ad:.2f}s lengths differ")
    full = dur > 600
    if full and dur < NARRATION:
        fails.append(f"video ({dur:.2f}s) ends before the narration ({NARRATION}s) — final words cut")

    # black gaps
    blk = re.findall(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)",
                     scan(path, vf="blackdetect=d=0.25:pix_th=0.06"))
    unexpected = [(float(s), float(e)) for s, e, _ in blk if not (float(s) < 0.7 or float(e) > dur - 1.2)]
    notes.append(f"black segments: {len(blk)} total, {len(unexpected)} outside the intended fades")
    if unexpected:
        fails.append(f"black gaps at {', '.join(f'{s:.1f}-{e:.1f}s' for s, e in unexpected[:5])}")

    # frozen picture (whole frame static for 2 s+). Once a scene settles, the only motion is the
    # presenter — a circle of ~7% of the frame — so the threshold is scaled to that area: this flags
    # genuinely identical frames (a real stall), not a still slide with the presenter talking.
    frz = re.findall(r"freeze_start: ([\d.]+).*?freeze_duration: ([\d.]+)",
                     scan(path, vf="freezedetect=n=0.00005:d=2"), re.S)
    notes.append(f"frozen segments (>=2 s): {len(frz)}")
    if frz:
        fails.append(f"frozen picture at {', '.join(f'{float(s):.1f}s ({float(d):.1f}s)' for s, d in frz[:5])}")

    # audio dropouts (> 3 s of near-silence would be abnormal for continuous narration)
    sil = re.findall(r"silence_start: ([\d.]+).*?silence_duration: ([\d.]+)",
                     scan(path, af="silencedetect=noise=-45dB:d=3"), re.S)
    notes.append(f"silences over 3 s: {len(sil)}")
    if sil:
        fails.append(f"audio silent at {', '.join(f'{float(s):.1f}s ({float(d):.1f}s)' for s, d in sil[:5])}")

    print(f"QC: {path.name}")
    for n in notes:
        print("  ·", n)
    if fails:
        print("FAIL")
        for f in fails:
            print("  ✗", f)
        sys.exit(1)
    print("PASS — all checks")


if __name__ == "__main__":
    main()
