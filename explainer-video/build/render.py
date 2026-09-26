#!/usr/bin/env python3
"""
Renders the IndianLawGPT explainer video.

Pipeline
  1. concat the three avatar takes (first -> second -> third), audio stream-copied
  2. normalise narration level (two-pass EBU R128 loudnorm, linear gain only)
  3. BACKGROUND pass: each scene plays its browser-rendered entrance animation
     (build/anim/<id>/NNNN.jpg, from shoot_slides.mjs) then holds its settled last frame;
     scenes cross-dissolve (0.5 s). Rendered in chunks of CHUNK scenes, then dissolve-joined.
  4. COMPOSITE pass: the avatar badge — face in a circle, soft shadow beneath, accent ring over the
     edge — whose position and size follow eased curves, so it glides between corners and grows or
     shrinks smoothly instead of jumping. Narration muxed underneath.

Why two passes: one graph holding every scene plus alpha overlays exhausts FFmpeg's scaler
("Failed initializing scaling graph"). Split, each graph stays small.

Usage
  python3 build/render.py                     # full film -> out/IndianLawGPT_Explainer_Final.mp4
  python3 build/render.py --from 0 --to 28 --out build/work/clip.mp4
  python3 build/render.py --preview           # representative windows -> ..._Preview.mp4
"""
import argparse
import json
import math
import pathlib
import shutil
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SLIDES = HERE / "slides"
ANIM = HERE / "anim"
ASSETS = ROOT / "assets"
OUT = ROOT / "out"
WORK = HERE / "work"
FPS = 30
XF = 0.5                      # cross-dissolve length between scenes
CHUNK = 12                    # scenes per background chunk
CROP = "crop=420:420:625:0"   # face region inside the 1280x720 source (verified on frames)
BADGE = 470                   # avatar circle is built at its largest size, then scaled per frame
PAD = 26                      # shadow/ring canvas margin: canvas = BADGE + 2*PAD = 522
GLIDE = 0.9                   # seconds for the avatar to move / resize between states
LEAD = 0.25                   # start the move this much before the scene cut (moves with the dissolve)
SOURCES = ["First video.mp4", "Second .mp4", "Third.mp4"]
# windows start on scene boundaries so each entrance animation plays from its beginning
PREVIEW_WINDOWS = [(0, 28), (138, 160), (396.32, 427.84), (616, 638.2)]


def run(cmd, desc):
    print(f"  · {desc}", flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stderr[-4000:])
        raise SystemExit(f"FAILED: {desc}")
    return p


def ffprobe_dur(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nk=1:nw=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())


def atomic(cmd, out_path, desc):
    """Write to a .partial file and rename only on success — an interrupted render never
    leaves a broken file under the final name."""
    partial = out_path.with_name(out_path.stem + ".partial" + out_path.suffix)
    run(cmd[:-1] + [str(partial)], desc)
    partial.replace(out_path)
    return out_path


# ------------------------------------------------------------------ narration
def build_master():
    WORK.mkdir(parents=True, exist_ok=True)
    master = WORK / "avatar_master.mp4"
    if master.exists():
        return master
    lst = WORK / "concat.txt"
    lst.write_text("".join(f"file '{(ROOT / s).as_posix()}'\n" for s in SOURCES))
    # stream copy: the three takes share codec/params, so the speech is bit-identical
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(master)],
        "concat avatar takes (first -> second -> third)")
    print(f"    master narration: {ffprobe_dur(master):.2f}s")
    return master


def normalised_audio(master):
    """Two-pass EBU R128 normalisation — level only, speech untouched."""
    out = WORK / "narration_norm.m4a"
    if out.exists():
        return out
    p = subprocess.run(["ffmpeg", "-i", str(master), "-af",
                        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"],
                       capture_output=True, text=True)
    m = json.loads(p.stderr[p.stderr.rfind("{"):p.stderr.rfind("}") + 1])
    af = (f"loudnorm=I=-16:TP=-1.5:LRA=11:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
          f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    run(["ffmpeg", "-y", "-i", str(master), "-vn", "-af", af, "-c:a", "aac", "-b:a", "192k", str(out)],
        f"normalise narration (measured {float(m['input_i']):.1f} LUFS -> -16)")
    return out


# ------------------------------------------------------------------ scenes
def window_scenes(scenes, t0, t1):
    """Scenes overlapping [t0,t1), clipped and rebased to 0. `skip` = seconds of the scene's
    animation already elapsed when the window starts mid-scene."""
    out = []
    for s in scenes:
        if s["end"] <= t0 or s["start"] >= t1:
            continue
        st, en = max(s["start"], t0), min(s["end"], t1)
        if en - st < 0.25:
            continue
        out.append({**s, "start": round(st - t0, 3), "end": round(en - t0, 3), "dur": round(en - st, 3),
                    "skip": round(st - s["start"], 3)})
    return out


def xfade_chain(labels, durs, filters, out_label):
    """Cross-dissolve a list of streams; offset_i = sum of durations before item i."""
    chain, acc = labels[0], 0.0
    for i in range(1, len(labels)):
        acc += durs[i - 1]
        nxt = f"[xf{i}]"
        filters.append(f"{chain}{labels[i]}xfade=transition=fade:duration={XF}:offset={acc:.3f}{nxt}")
        chain = nxt
    filters.append(f"{chain}null{out_label}")


# ------------------------------------------------------------------ pass 1: background
def render_bg_chunk(scenes, out_path, tail, manifest):
    """One chunk of scenes. `tail` adds XF seconds so the next chunk can dissolve in."""
    inputs, filters, labels = [], [], []
    for i, sc in enumerate(scenes):
        info = manifest.get(sc["id"])
        n = info["frames"] if info else len(list((ANIM / sc["id"]).glob("*.jpg")))
        if not n:
            raise SystemExit(f"no animation frames for {sc['id']} — run shoot_slides.mjs")
        seg = sc["dur"] + XF
        first = min(n - 1, int(round(sc.get("skip", 0) * FPS)))
        remaining = (n - first) / FPS
        hold = max(0.0, seg - remaining)
        inputs += ["-framerate", str(FPS), "-start_number", str(first),
                   "-i", str(ANIM / sc["id"] / "%04d.jpg")]
        # play the entrance animation, then hold its settled last frame (same JPEG path: no colour jump)
        filters.append(
            f"[{i}:v]setsar=1,tpad=stop_mode=clone:stop_duration={hold + 0.1:.3f},"
            f"trim=duration={seg:.3f},setpts=PTS-STARTPTS,format=yuv420p[v{i}]")
        labels.append(f"[v{i}]")
    total = sum(s["dur"] for s in scenes) + (XF if tail else 0.0)
    xfade_chain(labels, [s["dur"] for s in scenes], filters, "[chain]")
    filters.append(f"[chain]trim=duration={total:.3f},setpts=PTS-STARTPTS[bg]")
    cmd = (["ffmpeg", "-y"] + inputs + ["-filter_complex", ";".join(filters), "-map", "[bg]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "-an", str(out_path)])
    return atomic(cmd, out_path, f"background chunk {out_path.stem} ({len(scenes)} scenes, {total:.1f}s)")


def render_background(scenes, out_path, tag):
    mf = ANIM / "manifest.json"
    manifest = json.loads(mf.read_text()) if mf.exists() else {}
    groups = [scenes[i:i + CHUNK] for i in range(0, len(scenes), CHUNK)]
    parts, durs = [], []
    for g_i, g in enumerate(groups):
        base = g[0]["start"]
        rebased = [{**s, "start": s["start"] - base, "end": s["end"] - base} for s in g]
        part = WORK / f"bg_{tag}_{g_i:02d}.mp4"
        render_bg_chunk(rebased, part, tail=g_i < len(groups) - 1, manifest=manifest)
        parts.append(part)
        durs.append(sum(s["dur"] for s in g))
    if len(parts) == 1:
        parts[0].replace(out_path)
        return out_path
    inputs, filters = [], []
    for i, p in enumerate(parts):
        inputs += ["-i", str(p)]
        filters.append(f"[{i}:v]settb=AVTB,fps={FPS},format=yuv420p[p{i}]")
    xfade_chain([f"[p{i}]" for i in range(len(parts))], durs, filters, "[joined]")
    total = sum(durs)
    filters.append(f"[joined]trim=duration={total:.3f},setpts=PTS-STARTPTS[bg]")
    cmd = (["ffmpeg", "-y"] + inputs + ["-filter_complex", ";".join(filters), "-map", "[bg]",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "14", "-pix_fmt", "yuv420p",
           "-r", str(FPS), "-an", str(out_path)])
    return atomic(cmd, out_path, f"join {len(parts)} background chunks ({total:.1f}s)")


# ------------------------------------------------------------------ pass 2: composite
def eased_signal(scenes, value):
    """ffmpeg expression in t: piecewise-constant per scene, with smoothstep transitions of GLIDE
    seconds starting LEAD before each change."""
    vals = [value(s) for s in scenes]
    expr = f"{vals[0]:.3f}"
    for i in range(1, len(scenes)):
        delta = vals[i] - vals[i - 1]
        if abs(delta) < 0.001:
            continue
        t0 = scenes[i]["start"] - LEAD
        c = f"clip((t-{t0:.3f})/{GLIDE},0,1)"
        expr += f"+({delta:.3f})*{c}*{c}*(3-2*{c})"
    return expr


def composite(bg, t0, total, scenes, states, master, audio, out_path, crf):
    canvas = BADGE + 2 * PAD
    cx = eased_signal(scenes, lambda s: states[s["avatar"]]["x"] + states[s["avatar"]]["size"] / 2)
    cy = eased_signal(scenes, lambda s: states[s["avatar"]]["y"] + states[s["avatar"]]["size"] / 2)
    sc = eased_signal(scenes, lambda s: states[s["avatar"]]["size"] / BADGE)
    inputs = ["-i", str(bg),
              "-ss", f"{t0:.3f}", "-t", f"{total:.3f}", "-i", str(master),
              "-ss", f"{t0:.3f}", "-t", f"{total:.3f}", "-i", str(audio),
              "-loop", "1", "-i", str(ASSETS / f"mask_{BADGE}.png"),
              "-loop", "1", "-i", str(ASSETS / f"shadow_{BADGE}.png"),
              "-loop", "1", "-i", str(ASSETS / f"ring_{BADGE}.png")]
    filters = [
        # the face, masked to a circle
        f"[1:v]fps={FPS},{CROP},scale={BADGE}:{BADGE}:flags=lanczos,format=rgba[av]",
        f"[3:v]format=gray,scale={BADGE}:{BADGE}[mk]",
        "[av][mk]alphamerge[face]",
        # badge = shadow (under) + face + ring (over the edge), on a transparent canvas
        "[4:v]format=rgba[sh]",
        f"[sh][face]overlay={PAD}:{PAD}:format=auto:shortest=1[b1]",
        "[5:v]format=rgba[rg]",
        "[b1][rg]overlay=0:0:format=auto:shortest=1[badge]",
        # per-frame size, re-centred on a fixed canvas so downstream sizes never change
        f"[badge]scale=w='2*trunc({canvas / 2}*({sc}))':h='2*trunc({canvas / 2}*({sc}))':eval=frame:flags=bicubic,"
        f"pad=w={canvas}:h={canvas}:x='(ow-iw)/2':y='(oh-ih)/2':color=black@0:eval=frame,format=yuva420p[bd]",
        # per-frame position (centre of the circle)
        f"[0:v][bd]overlay=x='({cx})-{canvas / 2}':y='({cy})-{canvas / 2}':format=yuv420:shortest=1[vo]",
        f"[vo]fade=t=in:st=0:d=0.6,fade=t=out:st={total - 0.9:.3f}:d=0.9,format=yuv420p[vout]",
    ]
    cmd = (["ffmpeg", "-y"] + inputs +
           ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "2:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-r", str(FPS), "-movflags", "+faststart",
            # pad the narration with silence through the closing hold, so audio and video end together
            "-af", "apad", "-c:a", "aac", "-b:a", "192k",
            "-t", f"{total:.3f}", str(out_path)])
    return atomic(cmd, out_path, f"composite animated avatar + narration -> {out_path.name}")


def render_window(t0, t1, out_path, timeline, master, audio, crf=19, tag="w"):
    scenes = window_scenes(timeline["scenes"], t0, t1)
    if not scenes:
        raise SystemExit(f"no scenes in window {t0}-{t1}")
    total = round(t1 - t0, 3)
    bg = WORK / f"background_{tag}.mp4"
    render_background(scenes, bg, tag)
    print(f"    background: {ffprobe_dur(bg):.2f}s (target {total:.2f}s)")
    return composite(bg, t0, total, scenes, timeline["avatar_states"], master, audio, out_path, crf)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="t0", type=float, default=0.0)
    ap.add_argument("--to", dest="t1", type=float, default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--crf", type=int, default=19)
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg not found")
    timeline = json.loads((HERE / "timeline.json").read_text())
    OUT.mkdir(parents=True, exist_ok=True)
    print("IndianLawGPT explainer render")
    master = build_master()
    audio = normalised_audio(master)

    if args.preview:
        parts = []
        for i, (a, b) in enumerate(PREVIEW_WINDOWS):
            parts.append(render_window(a, b, WORK / f"prev_{i}.mp4", timeline, master, audio,
                                       crf=args.crf, tag=f"prev{i}"))
        lst = WORK / "prev_concat.txt"
        lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts))
        dest = OUT / "IndianLawGPT_Explainer_Preview.mp4"
        atomic(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                "-c:v", "libx264", "-preset", "medium", "-crf", str(args.crf), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(dest)], dest, "join preview windows")
        print(f"\nPREVIEW: {dest}  ({ffprobe_dur(dest):.1f}s)")
        return

    t1 = args.t1 if args.t1 is not None else timeline["end"]
    dest = pathlib.Path(args.out) if args.out else OUT / "IndianLawGPT_Explainer_Final.mp4"
    tag = "full" if (args.t0 == 0 and args.t1 is None) else f"w{int(args.t0)}"
    render_window(args.t0, t1, dest, timeline, master, audio, crf=args.crf, tag=tag)
    print(f"\nFINAL: {dest}  ({ffprobe_dur(dest):.1f}s)")


if __name__ == "__main__":
    main()
