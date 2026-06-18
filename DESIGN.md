# Design

Visual system for the Likes Archive web UI. Adaptive neutral: light by default,
dark via `prefers-color-scheme`, one cobalt accent. All tokens live in
`src/likes_archive/web/static/styles.css` under `:root` (light) and the
`@media (prefers-color-scheme: dark)` override.

## Theme

A quiet, content-first reading surface that follows the OS appearance. Near-white
in light mode, true-dark in dark mode, with a single cobalt accent reserved for
links, primary actions, focus, and the brand mark. Strategy: **Restrained** (one
accent, neutral surfaces) per the product register's floor.

## Color

Light:

| Role          | Token            | Value     |
| ------------- | ---------------- | --------- |
| App bg        | `--bg`           | `#fbfbfd` |
| Card surface  | `--surface`      | `#ffffff` |
| Inset surface | `--surface-2`    | `#f1f3f5` |
| Border        | `--border`       | `#e6e8eb` |
| Border strong | `--border-strong`| `#d6dadf` |
| Ink (primary) | `--ink`          | `#16181c` |
| Ink (2nd)     | `--ink-2`        | `#424852` |
| Ink (muted)   | `--ink-3`        | `#5b6470` |
| Accent        | `--accent`       | `#2563eb` |
| Accent hover  | `--accent-hover` | `#1d4ed8` |
| Warn bg/ink   | `--warn-*`       | amber set |

Dark: same roles, retuned — `--bg #0f1115`, `--surface #16181c`,
`--surface-2 #1c2027`, `--ink #e7e9ea`, `--ink-3 #8b929b`, `--accent #5b9bff`.

Contrast: muted text clears 4.5:1 on its surface in both themes; the accent
clears 4.5:1 as link text. Media badges/play buttons use opaque black scrims so
they read on any image.

## Typography

One family: the native system sans stack (`-apple-system, BlinkMacSystemFont,
"Segoe UI", Roboto, ...`). No web-font fetch — fast and fully offline, which
suits a self-hosted archive. Fixed rem scale (not fluid), tight ratio:

- Body / tweet content: `0.97rem`, line-height `1.55`
- Author name: `0.95rem` / weight 680; handle + meta: `0.8–0.82rem`, `--ink-3`
- Brand: `1.06rem` / 700; page title (section label): `1.05rem` / 680, `--ink-2`
- Letter-spacing `-0.01em`–`-0.02em` on the brand and titles only.

## Components

- **Topbar** — sticky, translucent (`--topbar-bg` + light blur), border-bottom.
  Brand (cobalt-gradient heart mark + wordmark) left; rounded search field right
  with an inline magnifier and a 3px focus ring.
- **Tweet card** (`.tweet_wrapper`) — `--surface`, 1px `--border`, `--r-lg`
  radius, `--shadow-1`, static (no hover state — the card itself isn't a target).
  Avatar (44px, links to X) + name/handle, content, optional quoted block,
  optional media collage, footer (local time + Original/Permalink links).
- **Media collage** — CSS grid, 1–4 + many count classes (16:9 / square aspect
  ratios), 3px gaps, rounded/clipped. Each item is a reset `<button>` trigger:
  - photo → `data-lb-type="image"`, `zoom-in` cursor, hover scale + zoom glyph
  - video → poster `<img>` + centered play badge, `data-lb-type="video"` (no
    inline `<video>`; the asset loads only in the viewer)
  - animated GIF → inline autoplay muted loop + "GIF" badge, `data-lb-type="gif"`
- **Lightbox** (`#lightbox`) — native `<dialog>`, full-viewport, dimmed/blurred
  `::backdrop`, centered media at <=92vw/vh, circular close button, pop-in
  animation. Populated and torn down by `static/lightbox.js` via click
  delegation (works for HTMX-inserted cards).
- **Token banner** — amber, full border, used for the expired-credential warning.
- **Empty states** — centered muted title + hint for the search landing and
  no-results cases.

## Layout

- Centered container, max-width `1240px`, `1.25rem` side padding.
- Feed is CSS-column masonry: 3 cols, 2 at <=1100px, 1 at <=680px;
  `break-inside: avoid` keeps cards intact. Single-tweet view caps at 600px.

## Motion

- 150–250ms transitions on hover/focus state changes only (`--ease`
  = `cubic-bezier(0.2,0.8,0.2,1)`, ease-out, no bounce).
- Lightbox: 0.28s scale+fade pop and backdrop fade.
- `prefers-reduced-motion: reduce` collapses all transitions/animations and
  disables the media hover scale.

## Z-index scale

Topbar `100`; lightbox uses the browser top-layer via `dialog.showModal()`.
