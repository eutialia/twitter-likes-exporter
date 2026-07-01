// Masonry feed. The tweet list is a CSS grid; each card's height is turned
// into a grid-row span so varied-height cards pack tightly into columns.
//
// Why grid + JS instead of CSS `column-count`: multi-column re-balances *all*
// columns whenever content is added, so every HTMX infinite-scroll batch shoves
// the cards already on screen. Grid tracks are stable — cards that are already
// placed never move when a new batch is appended.
//
// A single ResizeObserver re-spans a card whenever its height changes (image
// decode, viewport resize, or a column-count breakpoint). New batches inserted
// by HTMX are picked up via `htmx:afterSwap`. Triggers are height-driven, so
// cards with unmeasured media self-correct once the media lays out.
(() => {
  "use strict";

  const list = document.querySelector(".tweet_list");
  if (!list || !("ResizeObserver" in window)) return;

  const styles = getComputedStyle(list);
  const row = parseFloat(styles.gridAutoRows) || 8; // px per implicit row track
  const gap = parseFloat(styles.rowGap) || parseFloat(styles.columnGap) || row;

  const span = (card) => {
    const height = card.getBoundingClientRect().height;
    const rows = Math.max(1, Math.ceil((height + gap) / row));
    card.style.gridRowEnd = "span " + rows;
  };

  const observer = new ResizeObserver((entries) => {
    for (const entry of entries) span(entry.target);
  });

  // Span + observe every not-yet-claimed card. Idempotent, so it's safe to run
  // on the initial DOM and again after each HTMX swap.
  const claim = () => {
    for (const card of list.querySelectorAll(".tweet_wrapper")) {
      if (card.dataset.masonry) continue;
      card.dataset.masonry = "1";
      span(card); // synchronous first pass avoids a flash of unspanned cards
      observer.observe(card);
    }
  };

  claim();
  document.body.addEventListener("htmx:afterSwap", claim);
})();
