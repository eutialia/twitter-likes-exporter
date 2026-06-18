# Product

## Register

product

## Users

A single self-hoster browsing their own archive of X (Twitter) likes, privately,
on their homelab. Context is relaxed and reference-driven: revisiting saved
posts, searching for a half-remembered tweet, looking at saved media. Used on
both desktop and phone, often in the evening. There is no second user, no
sharing, no audience.

## Product Purpose

A private, fast, searchable reader over one's liked-tweet archive. Tweet text and
metadata live in Postgres (full-text + trigram search); media is served from a
local NFS mount. Success is that the archive is genuinely pleasant to browse and
search, and any image, GIF, or video can be viewed full-size without leaving the
page or triggering a download.

## Brand Personality

Calm, modern, unobtrusive. It reads like a personal reading app, not a social
network. Quiet confidence: the interface is precise and gets out of the way so
the saved content is the thing you look at.

## Anti-references

- The dated flat-UI-colors palette the old build shipped (`#3498db` links,
  `#95a5a6` greys on `#eee`). That look is the thing being replaced.
- Social-media chrome: engagement counts, "trending", ads, algorithmic noise,
  notification dots. None of it belongs here; this is an archive, not a feed.
- Heavy, decorated, "dashboard-y" product UI. No gratuitous cards-in-cards,
  gradients-for-flavor, or motion that doesn't convey state.

## Design Principles

1. **Content first.** The tweet (and its media) is the hero. Chrome stays thin.
2. **Earned familiarity.** X-adjacent enough to feel natural, cleaner and calmer
   than the source. Don't reinvent standard affordances.
3. **The tool disappears.** Browsing and searching should feel instant and
   frictionless; nothing should demand attention it hasn't earned.
4. **Respect the reader's environment.** Follow the system light/dark setting,
   honor reduced-motion, never disable zoom.
5. **No decoration without purpose.** Every shadow, border, and animation either
   communicates state or improves legibility, or it's removed.

## Accessibility & Inclusion

Target WCAG AA. Body and meta text meet >=4.5:1 against their surfaces in both
themes. Fully keyboard-operable: the media viewer is a native `<dialog>` (focus
trap, ESC to close) and all interactive elements show a visible focus ring.
`prefers-reduced-motion` removes transitions and the lightbox pop. The viewport
permits pinch-zoom.
