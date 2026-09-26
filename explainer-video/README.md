# IndianLawGPT Explainer — video project

A ~10:38 explainer for IndianLawGPT: your three avatar takes joined in order and shown as a
circular picture-in-picture over motion-graphic explainer scenes and real app screenshots.

## Outputs

| File | What it is |
|---|---|
| `out/IndianLawGPT_Explainer_Final.mp4` | The full video — 1920×1080, 30 fps, H.264 + AAC |
| `out/IndianLawGPT_Explainer_Preview.mp4` | ~1:44 cut of four representative sections (opening, hybrid retrieval, model results, closing), for reviewing the style |

Your original files (`First video.mp4`, `Second .mp4`, `Third.mp4`) are never modified.

## Folder layout

```
Ai Law video/
├─ First video.mp4, Second .mp4, Third.mp4   originals (read only)
├─ out/                                      final + preview renders
├─ assets/
│  ├─ screens/        real IndianLawGPT screenshots (captured from the running app)
│  ├─ mask_470.png    circular alpha mask for the avatar
│  ├─ shadow_470.png  soft shadow drawn under the avatar circle
│  └─ ring_470.png    accent ring drawn over the circle's edge
└─ build/
   ├─ make_slides.py  ← edit this: every scene's content, timing and avatar position
   ├─ slides.html     generated — all 72 scenes as HTML, with their animations
   ├─ shoot_slides.mjs  renders every animation frame → build/anim/, final frames → build/slides/,
   │                    and runs a layout check (clipping, overlaps, content under the avatar)
   ├─ capture_app.mjs   re-captures app screenshots (needs the app running)
   ├─ render.py       FFmpeg compositor — builds the video
   ├─ timeline.json   generated — scene start/end times and avatar states
   ├─ anim/           animation frames per scene (30 fps JPEG) + manifest.json
   ├─ slides/         settled final frame per scene (1920×1080)
   ├─ qc.py           automated checks on a finished render
   ├─ audio/          transcripts with timestamps (master_segments.json)
   └─ work/           intermediates: joined narration, normalised audio, logs
```

## Rerender

Prerequisites: `ffmpeg`, Python 3, Node, and the cached Playwright package (see note below).

```bash
cd "/Users/furqaanahmed/LAW LLM/Ai Law video"

# 1. regenerate scene HTML + timeline after editing build/make_slides.py
python3 build/make_slides.py

# 2. render every scene's animation frames (+ layout check)
#    (Playwright isn't a dependency here; run from a folder where it resolves, e.g.)
cp build/shoot_slides.mjs ~/.npm/_npx/e41f203b7505f1fb/ && node ~/.npm/_npx/e41f203b7505f1fb/shoot_slides.mjs

# 3. render the video
python3 build/render.py              # full film  -> out/IndianLawGPT_Explainer_Final.mp4
python3 build/render.py --preview    # preview    -> out/IndianLawGPT_Explainer_Preview.mp4
python3 build/render.py --from 400 --to 430 --out build/work/check.mp4   # any window
python3 build/qc.py                  # checks the final render
```

`render.py` writes to a `.partial.mp4` file and renames it only on success, so an interrupted
render never leaves a broken file under the final name. The full render takes a while; run it
detached (`nohup python3 build/render.py > build/work/render_full.log 2>&1 &`) if you may close the terminal.

## How it's built

1. **Narration.** The three takes are joined with FFmpeg's concat demuxer using stream copy —
   first → second → third — so your speech is bit-identical to the originals. Total: **636.70 s**.
2. **Timing.** The narration was transcribed locally with Whisper (mlx-whisper, on-device) to get
   real timestamps. Every scene change in `make_slides.py` sits on a sentence boundary from that
   transcript (`build/audio/master_segments.json`), not on estimated timings.
3. **Scenes and motion.** 72 scenes designed in HTML/CSS using the app's own typefaces
   (Newsreader, Geist, Geist Mono) and colours. Every scene has a choreographed entrance, rendered
   frame by frame in Chromium (each animation is paused and seeked to an exact time, so frames are
   deterministic and motion is sub-pixel smooth):
   - headlines reveal word by word out of a blur; the IndianLawGPT title builds letter by letter
   - flow diagrams build node by node with arrows drawing between them
   - corpus figures and results **count up** to their exact values; chart bars grow from zero
   - lists, status rows and chips stagger in; the rejected quotation is struck through
   - app screenshots rise into frame, then push in slowly for the whole scene
   After its entrance, each scene holds its settled frame, and scenes cross-dissolve (0.5 s).
4. **Avatar.** The face sits upper-right in the 1280×720 source (centred near x 835, y 185 — checked
   on frames from all three takes), so the circle is cropped from a 420×420 region at (625, 0), not
   the frame centre. It's built as one badge — soft shadow underneath, your face in a smooth circle,
   an accent ring over the edge — and its position and size follow eased curves, so it **glides**
   between corners (bottom-right by default, bottom-left when a chart or figure needs the right side)
   and grows for the opening and close, instead of jumping.
5. **Audio.** Only level correction: the takes were very quiet (−40.3 LUFS), so they are normalised
   to −16 LUFS with two-pass EBU R128 `loudnorm` (linear gain — no compression, no editing of speech).
   **No background music was added:** there is no licensed track in the project, and the narration
   runs continuously for the whole video.

## Changing things

- **Text or a scene:** edit its entry in the `S[...]` dictionary in `build/make_slides.py`.
- **When a scene appears / where the avatar sits:** edit the `SCENES` list (start time, slide id,
  avatar state). Avatar states are defined in `AVATAR_STATES`.
- **Face crop:** `CROP` at the top of `build/render.py`.
- Then run steps 1–3 above.

## Where the numbers come from

Every figure on screen comes from the project itself — nothing was added or rounded up:

| Figure | Source |
|---|---|
| 38,432 documents · 64,651 passages · 38,238 sections · 832 Acts · 194 judgments | live `/api/stats` from the running app |
| 106 / 112 sources, 94.6% held-out retrieval | `LegalPOC/data/distill/final_readiness_report.md` §3 |
| Legal correctness 15 / 6 / 50, citation accuracy 0 / 31 / 50 (Base / LoRA / Claude) | `LegalPOC/data/distill/pilot_lora/summary.md` |
| 30 training examples, Qwen3-1.7B, 4-bit, MLX, 50 held-out questions | same pilot report |

All app screenshots are real captures of the running IndianLawGPT interface (`build/capture_app.mjs`).
No API keys, environment variables or personal data appear in them.

## Notes for this repository copy

- **Not included** (too large, or regenerable): the three raw avatar takes (`First video.mp4`,
  `Second .mp4`, `Third.mp4`), the per-scene animation frames (`build/anim/`, ~1.1 GB), rendered
  slides, and render intermediates. `python3 build/make_slides.py` and `node build/shoot_slides.mjs`
  regenerate the frames; put the three takes next to `build/` to re-render.
- **Paths:** the build scripts point at the original working folder
  (`/Users/furqaanahmed/LAW LLM/Ai Law video`) and at this repo's `frontend/node_modules` for fonts.
  Adjust the constants at the top of `make_slides.py`, `shoot_slides.mjs` and `capture_app.mjs` to
  re-render from a different location.
- The MP4s are stored as ordinary git files (the final video is ~81 MiB).
