# STAK · box reveal

The STAK hero box, animated: the beam lights up first, then six glass coins rise out of the box into the light.
This repo is the **source**, not just the outputs. From it, any size, background, timing, or format can be re-rendered in one command.

## What's here

```
src/render.py    the renderer (Python 3, numpy, opencv-python-headless, scipy, Pillow, ffmpeg)
plates/          exact Figma renders of the box, beam, front faces and each coin, over black and over white,
                 at 2400px (true alpha is solved from each black/white pair). Masters: every size is a downscale.
exports/         current outputs per surface (see below)
```

Design source: Figma file `DE-STAK`, node **634:9020** (`tile · product`). If the artwork changes, re-render the plates
(same node, scale 2400/580, each scene over #000 and over #FFF, coins hidden / beam hidden / faces only, plus each coin alone)
and nothing else needs to change.

## The motion

| coin    | starts | lasts | note |
|---------|--------|-------|------|
| NVIDIA  | 0.00 s | 1.9 s | first out of the box |
| Apple   | 1.25 s | 2.5 s | |
| Shopify | 1.67 s | 2.5 s | |
| Amazon  | 2.09 s | 2.5 s | |
| Twitch  | 2.63 s | 2.5 s | rises highest |
| Google  | 3.27 s | 2.5 s | last |

Beam: lights from 0.4 s to 1.6 s with a soft bloom. Coins begin at 1.5 s. Each coin starts hidden behind the box's
front faces, fades in there, clears the faces' top edge into the mouth, and floats up. Opacity is linear;
the rise uses `cubic-bezier(0,0,0,1)`. No scale, no rotation, no hover. Ends on the full state and holds. 9.3 s.
(Order and easing taken from the STAK hero animation, `STAK-hero-section-animation-preview-v2`.)

## Regenerate

```
pip install numpy opencv-python-headless scipy Pillow      # plus ffmpeg on PATH
python3 src/render.py --size 1200 --bg transparent --mode once --formats apng,webm,png
python3 src/render.py --size 1400 --bg "#0A1020"   --mode once --formats gif,mp4,webm
python3 src/render.py --size 1200 --bg "#0A1020"   --mode loop --formats gif
```

Flags: `--size` (square px) · `--fps` · `--bg transparent | #hex` · `--mode once | loop` · `--formats apng,webm,png,gif,mp4` · `--out`

## Which file for which surface

| surface | file | why |
|---------|------|-----|
| Website, any background | `…-alpha-once.webm` + `…-alpha-once.apng` | true soft transparency. WebM for Chrome/Firefox/Edge, APNG as the Safari fallback. Use `<video autoplay muted playsinline>` for the WebM and an `<img>` for the APNG. |
| After Effects / Jitter / Framer | `…-alpha-once-png-sequence.zip` | lossless RGBA frames, 30 fps |
| Behance | `…-0a1020-once.gif` (1400) | Behance animates GIFs; GIF can't do soft alpha, so the page colour is baked in. Plays once, holds the full state. |
| Website, on #0A1020 | `…-0a1020-once.mp4` (1400) | smallest file, holds the last frame |
| Figma prototype | `…-0a1020-loop.gif` (1200) | Figma animates GIFs on any plan; loops |
| Placeholder / poster | `…-poster.png` | the settled last frame |

Need it on a different colour? `--bg "#RRGGBB"` and re-render; the transparent masters never need it.

## Note on GIF transparency

GIF transparency is on/off per pixel, so a transparent GIF would fringe wherever the beam's glow or the glass edges
meet a background. Don't export transparent GIFs; bake the destination colour instead.
