(function () {
  "use strict";

  // History restores may execute the shell's script again. Keep one initializer
  // and dispose listeners attached to the previous shell before binding a new one.
  if (window._maInitTour) { window._maInitTour(); return; }
  let cleanup = () => {};

  function initTour() {
    const dialog = document.querySelector("[data-ma-tour]");
    if (!dialog || dialog._maTour || !dialog.showModal) return;
    cleanup();
    dialog._maTour = true;
    const lifecycle = new AbortController();
    cleanup = () => lifecycle.abort();
    const launchers = Array.from(document.querySelectorAll("[data-ma-tour-start]"));
    const card = dialog.querySelector("[data-tour-card]");
    const spotlight = dialog.querySelector("[data-tour-spotlight]");
    const title = dialog.querySelector("#ma-tour-title");
    const description = dialog.querySelector("#ma-tour-description");
    const next = dialog.querySelector("[data-tour-next]");
    const back = dialog.querySelector("[data-tour-back]");
    const steps = Array.from(dialog.querySelectorAll("[data-tour-step]"));
    let index = 0, returnFocus = null, interacted = false;

    function visibleTarget() {
      const selector = steps[index].dataset.target;
      if (!selector) return null;
      return Array.from(document.querySelectorAll(selector)).find(el => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && rect.right > 0 && rect.left < innerWidth
          && rect.bottom > 0 && rect.top < innerHeight && getComputedStyle(el).visibility !== "hidden";
      });
    }

    function position() {
      if (!dialog.open) return;
      const viewport = window.visualViewport;
      const width = viewport?.width || innerWidth, height = viewport?.height || innerHeight;
      const left = viewport?.offsetLeft || 0, top = viewport?.offsetTop || 0;
      const margin = 16;
      card.style.maxHeight = `${Math.max(100, height - margin * 2)}px`;
      card.style.width = `${Math.min(400, width - margin * 2)}px`;
      const bounds = card.getBoundingClientRect();
      let x = left + (width - bounds.width) / 2, y = top + (height - bounds.height) / 2;
      const target = visibleTarget();
      spotlight.hidden = !target;
      if (target) {
        const rect = target.getBoundingClientRect();
        Object.assign(spotlight.style, {
          left: `${Math.max(left + 4, rect.left - 5)}px`,
          top: `${Math.max(top + 4, rect.top - 5)}px`,
          width: `${Math.min(rect.width + 10, width - 8)}px`,
          height: `${Math.min(rect.height + 10, height - 8)}px`,
        });
        if (width >= 768 && rect.right + bounds.width + 36 < left + width) {
          x = rect.right + 20;
          y = rect.top + 8;
        } else {
          x = rect.right - bounds.width;
          y = rect.bottom + 20;
          if (y + bounds.height > top + height - margin) y = rect.top - bounds.height - 20;
        }
      }
      card.style.left = `${Math.max(left + margin, Math.min(x, left + width - bounds.width - margin))}px`;
      card.style.top = `${Math.max(top + margin, Math.min(y, top + height - bounds.height - margin))}px`;
    }

    function render() {
      const step = steps[index];
      title.textContent = step.content.querySelector("h2").textContent;
      description.textContent = step.content.querySelector("p").textContent;
      dialog.querySelector("[data-tour-count]").textContent = step.dataset.count;
      next.textContent = index === steps.length - 1 ? dialog.dataset.finish : dialog.dataset.next;
      back.hidden = index === 0;
      dialog.querySelectorAll(".ma-tour-progress i").forEach((dot, i) => {
        dot.classList.toggle("is-active", i <= index);
      });
      position();
      title.focus({ preventScroll: true });
    }

    function open() {
      if (dialog.open || !dialog.isConnected) return;
      returnFocus = document.activeElement;
      index = 0;
      dialog.setAttribute("aria-modal", "true");
      dialog.showModal();
      render();
    }

    async function close(outcome) {
      if (!dialog.open) return;
      dialog.close();
      dialog.removeAttribute("aria-modal");
      const focus = returnFocus?.isConnected && returnFocus !== document.body
        ? returnFocus : document.getElementById("main-content");
      focus?.focus({ preventScroll: true });
      try {
        const response = await fetch(dialog.dataset.url, {
          method: "POST", credentials: "same-origin", keepalive: true,
          headers: { "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content },
          body: new URLSearchParams({ outcome }), signal: AbortSignal.timeout(8000),
        });
        if (!response.ok || response.redirected) throw new Error("Tour preference not saved");
      } catch (_) {
        document.dispatchEvent(new CustomEvent("ma:toast", {
          detail: { level: "error", message: dialog.dataset.saveError },
        }));
      }
    }

    launchers.forEach(button => {
      button.hidden = false;
      button.addEventListener("click", open);
    });
    next.addEventListener("click", () => {
      if (index === steps.length - 1) close("completed");
      else { index += 1; render(); }
    });
    back.addEventListener("click", () => { if (index > 0) { index -= 1; render(); } });
    dialog.querySelector("[data-tour-skip]").addEventListener("click", () => close("dismissed"));
    dialog.querySelector("[data-tour-close]").addEventListener("click", () => close("dismissed"));
    dialog.addEventListener("cancel", event => { event.preventDefault(); close("dismissed"); });
    window.addEventListener("resize", position, { signal: lifecycle.signal });
    window.visualViewport?.addEventListener("resize", position, { signal: lifecycle.signal });
    window.visualViewport?.addEventListener("scroll", position, { signal: lifecycle.signal });
    // Do not interrupt an operator who has started working while status was loading.
    const interaction = () => { interacted = true; };
    document.addEventListener("pointerdown", interaction, { once: true, signal: lifecycle.signal });
    document.addEventListener("keydown", interaction, { once: true, signal: lifecycle.signal });
    fetch(dialog.dataset.url, { credentials: "same-origin", cache: "no-store", signal: AbortSignal.any([lifecycle.signal, AbortSignal.timeout(8000)]) })
      .then(response => response.ok && !response.redirected ? response.json() : null)
      .then(state => {
        if (state?.show && !interacted && !document.querySelector('[aria-modal="true"]:not([style*="display: none"])')) open();
      })
      .catch(() => {}) // A status outage must never block the workspace.
      .finally(() => {
        document.removeEventListener("pointerdown", interaction);
        document.removeEventListener("keydown", interaction);
      });
  }

  window._maInitTour = initTour;
  initTour();
  document.addEventListener("htmx:load", initTour);
})();
