// Center-screen media viewer. A single native <dialog> is reused for every
// image, GIF and video. Triggers are matched by delegation on the document so
// cards inserted later by HTMX (infinite scroll) work without re-binding.
(() => {
  "use strict";

  const dialog = document.getElementById("lightbox");
  if (!dialog) return;
  const stage = dialog.querySelector(".lightbox_stage");
  const closeBtn = dialog.querySelector(".lightbox_close");

  function buildMedia(type, src) {
    if (type === "video" || type === "gif") {
      const video = document.createElement("video");
      video.className = "lightbox_media";
      video.src = src;
      video.autoplay = true;
      video.playsInline = true;
      video.loop = type === "gif";
      // GIFs stay muted (so autoplay is always allowed); real videos play with
      // sound — the click that opened the viewer counts as the user gesture.
      video.muted = type === "gif";
      video.controls = type === "video";
      return video;
    }
    const img = document.createElement("img");
    img.className = "lightbox_media";
    img.src = src;
    img.alt = "";
    return img;
  }

  function open(type, src) {
    stage.replaceChildren(buildMedia(type, src));
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
  }

  function close() {
    if (dialog.open) dialog.close();
    else dialog.removeAttribute("open");
  }

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-lb-type]");
    if (!trigger) return;
    event.preventDefault();
    open(trigger.dataset.lbType, trigger.dataset.lbSrc);
  });

  // Click on the dialog's own padding (outside the media) closes it.
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog || event.target === stage) close();
  });

  closeBtn?.addEventListener("click", close);

  // Native ESC + close button both fire "close"; tear the media down so videos
  // stop playing and release their buffers.
  dialog.addEventListener("close", () => stage.replaceChildren());
})();
