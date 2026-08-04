// Masonry feed + GIF hygiene. No build step — plain browser JS.
//
// Layout: CSS grid; each card's height becomes a grid-row span so varied cards
// pack tightly. Grid tracks stay put when HTMX appends a batch (unlike
// column-count, which re-balances everything).
//
// Perf (kept simple on purpose):
// 1. content-visibility:auto after measure — skip off-screen layout/paint.
// 2. GIF <video> only plays near the viewport; far ones pause and drop src.
// Cards are never removed — scroll-back always shows what you already loaded.
//
// GIF arming is global (not only inside .tweet_list) so the single-tweet
// permalink page works too.
(() => {
  "use strict";

  const GIF_ROOT_MARGIN = "200px 0px"; // start load a little early

  // --- GIF media: play near viewport only ---------------------------------

  const releaseGif = (video) => {
    if (!video) return;
    try {
      video.pause();
    } catch (_) {
      /* ignore */
    }
    // Only tear down when an explicit src attribute is present. Reading
    // video.src after removeAttribute still yields a resolved document URL
    // in some browsers, which is not a real media source.
    if (video.getAttribute("src")) {
      video.removeAttribute("src");
      video.load();
    }
  };

  const armGif = (video) => {
    const want = video.dataset.src;
    if (!want) return;
    if (video.getAttribute("src") !== want) {
      video.src = want;
    }
    const p = video.play();
    if (p && typeof p.catch === "function") p.catch(() => {});
  };

  let gifIO = null;
  if ("IntersectionObserver" in window) {
    gifIO = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          const video = e.target;
          if (e.isIntersecting) armGif(video);
          else releaseGif(video);
        }
      },
      { rootMargin: GIF_ROOT_MARGIN, threshold: 0.01 },
    );
  }

  const claimGifs = (root) => {
    const scope = root && root.querySelectorAll ? root : document;
    for (const video of scope.querySelectorAll("video[data-src]")) {
      if (video.dataset.gifIo) continue;
      video.dataset.gifIo = "1";
      if (gifIO) {
        releaseGif(video);
        gifIO.observe(video);
      } else {
        armGif(video);
      }
    }
  };

  // --- Masonry (feed only) ------------------------------------------------

  const list = document.querySelector(".tweet_list");
  if (list && "ResizeObserver" in window) {
    const styles = getComputedStyle(list);
    const row = parseFloat(styles.gridAutoRows) || 8;
    // column-gap is `var(--masonry-gap)` in CSS — computed style is already px.
    const gap = parseFloat(styles.columnGap) || row;

    const span = (card) => {
      const height = card.getBoundingClientRect().height;
      const rows = Math.max(1, Math.ceil((height + gap) / row));
      card.style.gridRowEnd = "span " + rows;
    };

    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const card = entry.target;
        // content-visibility collapses off-screen cards to their placeholder
        // size and fires resize — ignore that, or we re-span from the fallback.
        if (card.checkVisibility && !card.checkVisibility({ contentVisibilityAuto: true })) {
          continue;
        }
        span(card);
      }
    });

    const claimCards = () => {
      const fresh = [];
      for (const card of list.querySelectorAll(".tweet_wrapper")) {
        if (card.dataset.masonry) continue;
        card.dataset.masonry = "1";
        span(card);
        ro.observe(card);
        fresh.push(card);
      }
      // Measure every fresh card first, then enable off-screen skipping.
      for (const card of fresh) card.style.contentVisibility = "auto";
    };

    const claim = () => {
      claimCards();
      claimGifs(list);
    };

    claim();
    document.body.addEventListener("htmx:afterSwap", claim);
  } else {
    // Permalink / pages without a masonry grid: still arm GIF videos.
    claimGifs(document);
  }
})();
