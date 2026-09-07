(function () {
  "use strict";

  function storageGet(key, fallback) {
    try {
      const value = window.localStorage.getItem(key);
      return value === null ? fallback : JSON.parse(value);
    } catch (_) {
      return fallback;
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch (_) {}
  }

  function closeDialogHost() {
    const dialog = document.querySelector("[data-ma-dialog]");
    if (dialog && dialog._x_dataStack && dialog._x_dataStack[0]) {
      dialog._x_dataStack[0].close();
      return;
    }
    const host = document.getElementById("dialog-host");
    if (host) host.replaceChildren();
  }

  function showToast(detail) {
    const region = document.getElementById("toast-region");
    if (!region || !detail || !detail.message) return;
    const toast = document.createElement("div");
    toast.className = `ma-toast is-${detail.level || "info"}`;
    toast.setAttribute("role", "status");

    const icon = document.createElement("span");
    icon.className = "ma-toast-icon";
    icon.innerHTML = '<svg class="ma-icon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>';
    const message = document.createElement("span");
    message.textContent = detail.message;
    const dismiss = document.createElement("button");
    dismiss.setAttribute("aria-label", gettext("Dismiss"));
    dismiss.innerHTML = '<svg class="ma-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6 6 18M6 6l12 12"/></svg>';
    dismiss.addEventListener("click", () => toast.remove());
    toast.append(icon, message, dismiss);
    region.append(toast);
    requestAnimationFrame(() => toast.animate([{ opacity: 0, transform: "translateY(2px)" }, { opacity: 1, transform: "none" }], { duration: 150, easing: "ease-out" }));
    window.setTimeout(() => {
      const animation = toast.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 140 });
      animation.onfinish = () => toast.remove();
    }, 4300);
  }

  document.addEventListener("alpine:init", () => {
    // The browser top layer escapes clipping/stacking contexts in toolbars and rails.
    Alpine.directive("floating", (el, { expression, modifiers }, { effect, evaluateLater, cleanup }) => {
      const read = evaluateLater(expression);
      // A <details> panel is anchored to its summary, regardless of hidden form inputs.
      const anchor = el.parentElement?.matches("details")
        ? el.parentElement.querySelector(":scope > summary") : el.previousElementSibling;
      if (!anchor || !el.showPopover) return;
      el.setAttribute("popover", "manual");
      // Positioning must not depend on per-menu CSS (right/bottom offsets or margins).
      Object.assign(el.style, { position: "fixed", inset: "auto", margin: "0" });
      let active = false;
      const position = () => {
        if (!active || !el.isConnected || !el.matches(":popover-open")) return;
        const viewport = window.visualViewport;
        const left = viewport?.offsetLeft || 0;
        const top = viewport?.offsetTop || 0;
        const width = viewport?.width || innerWidth;
        const height = viewport?.height || innerHeight;
        const bounds = anchor.getBoundingClientRect();
        el.style.maxWidth = `${Math.max(0, width - 16)}px`;
        el.style.maxHeight = `${Math.max(0, height - 16)}px`;
        const panel = el.getBoundingClientRect();
        const above = bounds.bottom + panel.height + 6 > top + height - 8;
        const start = modifiers.includes("end") ? bounds.right - panel.width : bounds.left;
        el.style.left = `${Math.max(left + 8, Math.min(start, left + width - panel.width - 8))}px`;
        el.style.top = `${Math.max(top + 8, Math.min(above ? bounds.top - panel.height - 6 : bounds.bottom + 6, top + height - panel.height - 8))}px`;
      };
      effect(() => read(value => {
        active = Boolean(value);
        Alpine.nextTick(() => {
          if (!el.isConnected) return;
          if (active) {
            el.style.visibility = "hidden";
            el.showPopover();
            position();
            el.style.visibility = "visible";
          }
          else el.hidePopover();
        });
      }));
      const escape = event => {
        if (active && !event.defaultPrevented && event.key === "Escape") {
          event.preventDefault();
          event.stopPropagation();
          anchor.click();
          anchor.focus({ preventScroll: true });
        }
      };
      document.addEventListener("keydown", escape);
      const observer = new ResizeObserver(position);
      observer.observe(anchor);
      observer.observe(el);
      window.addEventListener("resize", position);
      window.addEventListener("scroll", position, true);
      window.visualViewport?.addEventListener("resize", position);
      window.visualViewport?.addEventListener("scroll", position);
      cleanup(() => {
        active = false;
        if (el.matches(":popover-open")) el.hidePopover();
        observer.disconnect();
        document.removeEventListener("keydown", escape);
        window.removeEventListener("resize", position);
        window.removeEventListener("scroll", position, true);
        window.visualViewport?.removeEventListener("resize", position);
        window.visualViewport?.removeEventListener("scroll", position);
      });
    });

    const choiceFilter = () => ({
      term: "", opened: false, selectedLabel: "", hasValue: false,
      summary() {
        const label = this.$root.dataset.label;
        return this.hasValue ? `${label}: ${this.selectedLabel}` : label;
      },
      init() { this.syncChoice(); },
      syncChoice() {
        const selected = Array.from(this.$root.querySelectorAll('input:checked'))
          .filter(input => input.value !== "");
        this.hasValue = selected.length > 0;
        this.selectedLabel = selected.map(input => input.closest("label").querySelector("span").textContent.trim()).join(", ");
      },
      toggled() { this.opened = this.$root.open; },
      closeOptions() { this.$root.open = false; },
      escape() { this.closeOptions(); this.$root.querySelector("summary").focus(); },
      chooseOption(event) {
        if (!event.target.matches('input[type="radio"], input[type="checkbox"]')) return;
        this.syncChoice();
        if (event.target.type === "radio") this.closeOptions();
        if (this.$root.dataset.autoSubmit === "true") event.target.form.requestSubmit();
      },
      matchesOption(el) { return el.textContent.toLocaleLowerCase().includes(this.term.toLocaleLowerCase()); }
    });
    Alpine.data("choiceFilter", choiceFilter);
    Alpine.data("relationFilter", () => ({
      ...choiceFilter(), page: 1, hasNext: false, hasPrevious: false, status: "", notice: "",
      controller: null,
      init() {
        this.hasValue = this.$refs.value.value !== "";
        this.selectedLabel = this.$root.dataset.selectedLabel || this.$refs.value.value;
      },
      toggled() {
        this.opened = this.$root.open;
        if (this.opened) this.load();
      },
      destroy() { this.controller?.abort(); },
      search() { this.page = 1; this.load(); },
      previous() { if (this.hasPrevious) { this.page--; this.load(); } },
      next() { if (this.hasNext) { this.page++; this.load(); } },
      clearValue() { this.choose("", ""); },
      choose(value, label) {
        this.$refs.value.value = value;
        this.hasValue = value !== "";
        this.selectedLabel = label;
        this.$refs.results.querySelectorAll("button").forEach(button => {
          button.setAttribute("aria-pressed", String(button.dataset.value === value));
        });
        this.closeOptions();
        if (this.$root.dataset.autoSubmit === "true") this.$refs.value.form.requestSubmit();
      },
      async load() {
        this.controller?.abort();
        const controller = new AbortController();
        this.controller = controller;
        this.status = "";
        this.notice = gettext("Loading…");
        this.hasNext = this.hasPrevious = false;
        this.$refs.results.replaceChildren();
        const url = new URL(this.$root.dataset.url, location.origin);
        url.searchParams.set("q", this.term);
        url.searchParams.set("page", this.page);
        try {
          const response = await fetch(url, { signal: controller.signal, headers: { Accept: "application/json" } });
          if (!response.ok) throw new Error("Request failed");
          const data = await response.json();
          if (controller.signal.aborted) return;
          this.page = data.page;
          this.hasNext = data.has_next; this.hasPrevious = data.has_previous;
          this.status = data.results.length ? interpolate(gettext("Page %(page)s of %(pages)s"), { page: data.page, pages: data.pages }, true) : "";
          this.notice = data.results.length ? "" : gettext("No matching records.");
          data.results.forEach(option => {
            const button = document.createElement("button");
            button.type = "button"; button.className = "ma-relation-option";
            button.dataset.value = option.value;
            button.textContent = option.label;
            button.setAttribute("aria-pressed", String(option.value === this.$refs.value.value));
            button.addEventListener("click", () => this.choose(option.value, option.label));
            this.$refs.results.append(button);
          });
        } catch (error) {
          if (error.name !== "AbortError") this.notice = gettext("Could not load records. Reopen or search to retry.");
        }
      }
    }));

    Alpine.data("appShell", () => ({
      dark: document.documentElement.classList.contains("dark"),
      sidebarCompact: storageGet("ma-sidebar-compact", false),
      mobileNav: false,
      commandOpen: false,
      commandReturnFocus: null,
      userMenu: false,
      init() {
        this.$watch("dark", value => {
          document.documentElement.classList.toggle("dark", value);
          window.localStorage.setItem("ma-theme", value ? "dark" : "light");
        });
        document.addEventListener("keydown", event => {
          if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
            event.preventDefault();
            this.openCommand();
          }
          if (event.key === "[" && !event.metaKey && !event.ctrlKey && !event.altKey
              && !event.target.matches("input, textarea, select")) {
            this.toggleSidebar();
          }
          if (!this.commandOpen) return;
          const items = Array.from(document.querySelectorAll("#command-results .ma-command-item"));
          const current = items.indexOf(document.activeElement);
          if (event.key === "ArrowDown") {
            event.preventDefault();
            (items[Math.min(current + 1, items.length - 1)] || items[0])?.focus();
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            (items[Math.max(current - 1, 0)] || items.at(-1))?.focus();
          } else if (event.key === "Enter" && document.activeElement === this.$refs.commandInput && items[0]) {
            event.preventDefault();
            items[0].click();
          }
        });
      },
      toggleSidebar() {
        this.sidebarCompact = !this.sidebarCompact;
        storageSet("ma-sidebar-compact", this.sidebarCompact);
      },
      toggleTheme() { this.dark = !this.dark; },
      openCommand() {
        this.commandReturnFocus = document.activeElement;
        this.commandOpen = true;
        this.$nextTick(() => {
          this.$refs.commandInput?.focus();
          if (window.htmx) htmx.trigger(this.$refs.commandInput, "load");
        });
      },
      closeCommand() {
        this.commandOpen = false;
        this.$nextTick(() => this.commandReturnFocus?.focus?.());
      },
      dialogSwapped(event) {
        if (event.detail.target?.id === "dialog-host") this.$nextTick(() => {});
      }
    }));

    Alpine.data("dialog", () => ({
      visible: false,
      closing: false,
      previousFocus: null,
      open() {
        this.previousFocus = document.activeElement;
        this.visible = true;
        this.$nextTick(() => {
          const element = this.$root.querySelector("input:not([type=hidden]), select, textarea")
            || this.$root.querySelector("button, a[href]");
          element?.focus();
        });
      },
      closePreview() { if (!document.querySelector("[data-ma-dialog]")) this.close(); },
      async close() {
        if (this.closing) return;
        this.closing = true;
        const root = this.$root;
        const panel = root.querySelector('[aria-modal="true"]');
        const focus = this.previousFocus;
        const duration = matchMedia('(prefers-reduced-motion: reduce)').matches ? 0 : 140;
        const animations = [root.animate(
          [{ backgroundColor: getComputedStyle(root).backgroundColor }, { backgroundColor: 'transparent' }],
          { duration, easing: 'ease-out', fill: 'forwards' }
        )];
        if (panel) animations.push(panel.animate(
          [{ opacity: getComputedStyle(panel).opacity }, { opacity: 0 }],
          { duration, easing: 'ease-out', fill: 'forwards' }
        ));
        await Promise.allSettled(animations.map(animation => animation.finished));
        root.remove();
        const returnFocus = focus?.isConnected ? focus
          : document.querySelector('[data-ma-preview] button') || document.querySelector('#resource-search');
        returnFocus?.focus({ preventScroll: true });
      },
      trap(event) {
        const focusable = Array.from(this.$root.querySelectorAll(
          'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )).filter(element => element.offsetParent !== null);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }));

    Alpine.data("resourceTable", () => ({
      activeFilter: "",
      filterPanel: false,
      viewsOpen: false,
      columnsOpen: false,
      hiddenColumns: [],
      init() {
        this._shortcut = event => {
          if (event.key === "/" && !event.metaKey && !event.ctrlKey
              && !event.target.matches("input, textarea, select")) {
            event.preventDefault();
            this.$root.querySelector('.ma-search-field input')?.focus();
          }
        };
        document.addEventListener("keydown", this._shortcut);
      },
      destroy() { document.removeEventListener("keydown", this._shortcut); },
      toggleColumn(index) {
        this.hiddenColumns = this.hiddenColumns.includes(index)
          ? this.hiddenColumns.filter(value => value !== index)
          : [...this.hiddenColumns, index];
      }
    }));

    Alpine.data("tableSelection", () => ({
      wideMobile: false,
      selected: [],
      get selectionSummary() {
        return interpolate(ngettext("%(count)s row selected", "%(count)s rows selected", this.selected.length), { count: this.selected.length }, true);
      },
      get allSelected() {
        const inputs = this.$root.querySelectorAll('input[name="selected"]');
        return inputs.length > 0 && this.selected.length === inputs.length;
      },
      toggle(value) {
        this.selected = this.selected.includes(value)
          ? this.selected.filter(item => item !== value)
          : [...this.selected, value];
      },
      syncIndeterminate(element) { element.indeterminate = this.selected.length > 0 && !this.allSelected; },
      toggleAll(event) {
        const inputs = Array.from(this.$root.querySelectorAll('input[name="selected"]'));
        inputs.forEach(input => { input.checked = event.target.checked; });
        this.selected = event.target.checked ? inputs.map(input => input.value) : [];
      },
      clear() {
        this.$root.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = false; });
        this.selected = [];
      }
    }));

    Alpine.data("detailTabs", initial => ({
      active: initial,
      select(key, button) {
        this.active = key;
        window.history.pushState({}, "", button.href);
        if (window.htmx) {
          htmx.ajax("GET", button.dataset.tabUrl, { target: "#detail-tab-panel", swap: "innerHTML" });
        }
      },
      overview(url) {
        this.active = "overview";
        window.history.pushState({}, "", url);
      }
    }));

    // Long permission lists need filtering and group toggles; the checkboxes stay
    // ordinary form inputs, so a submit without JavaScript still posts the truth.
    Alpine.data("accessPicker", () => ({
      query: "",
      selected: 0,
      total: 0,
      revision: 0,
      init() { this.sync(); },
      get selectionSummary() {
        return interpolate(gettext("%(selected)s of %(total)s selected"), { selected: this.selected, total: this.total }, true);
      },
      get noMatchMessage() {
        return interpolate(gettext("No match for “%(query)s”."), { query: this.query }, true);
      },
      options(root) {
        return Array.from((root || this.$root).querySelectorAll('.ma-access-option input[type="checkbox"]'));
      },
      sync() {
        const options = this.options();
        this.total = options.length;
        this.selected = options.filter(option => option.checked).length;
        this.revision++;
        this.$root.querySelectorAll(".ma-access-group").forEach(group => {
          const toggle = group.querySelector("[data-group-toggle]");
          if (!toggle) return;
          const inputs = this.options(group);
          const checked = inputs.filter(input => input.checked).length;
          toggle.checked = checked > 0 && checked === inputs.length;
          toggle.indeterminate = checked > 0 && checked < inputs.length;
        });
      },
      toggleGroup(event) {
        const group = event.target.closest(".ma-access-group");
        this.options(group)
          .filter(input => this.matches(input.closest(".ma-access-option")))
          .forEach(input => { input.checked = event.target.checked; });
        this.sync();
      },
      clear() {
        this.options().forEach(input => { input.checked = false; });
        this.sync();
      },
      matches(element) {
        if (!this.query) return true;
        return (element?.dataset.search || "").toLowerCase().includes(this.query.toLowerCase());
      },
      groupVisible(group) {
        return !this.query || this.options(group).some(input => this.matches(input.closest(".ma-access-option")));
      },
      groupSummary(element) {
        this.revision;
        const inputs = this.options(element.closest(".ma-access-group"));
        return `${inputs.filter(input => input.checked).length}/${inputs.length}`;
      },
      visible() {
        return this.options().some(input => this.matches(input.closest(".ma-access-option")));
      }
    }));

    Alpine.data("toast", () => ({
      visible: true,
      start() { window.setTimeout(() => { this.visible = false; }, 4300); }
    }));
  });

  document.addEventListener("keydown", event => {
    if (event.key !== "Tab" || event.defaultPrevented) return;
    const overlay = Array.from(document.querySelectorAll('[aria-modal="true"]'))
      .filter(element => element.getClientRects().length).at(-1);
    if (!overlay) return;
    const controls = Array.from(overlay.querySelectorAll(
      'a[href], button:not([disabled]), input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])'
    )).filter(element => element.getClientRects().length);
    if (!controls.length) return;
    const first = controls[0], last = controls.at(-1);
    if (!overlay.contains(document.activeElement) || (!event.shiftKey && document.activeElement === last)) {
      event.preventDefault(); first.focus();
    } else if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last.focus();
    }
  });

  document.addEventListener("click", event => {
    const row = event.target.closest("tr[data-row-url]");
    if (!row || event.target.closest("a, button, input, select, textarea, [role=menu]")) return;
    window.location.href = row.dataset.rowUrl;
  });

  document.addEventListener("htmx:beforeSwap", event => {
    if (event.detail.xhr.status === 422) {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });

  document.addEventListener("htmx:responseError", event => {
    if (event.detail.xhr.status === 403) return;
    showToast({ level: "error", message: gettext("That request could not be completed. Please try again.") });
  });

  document.addEventListener("ma:toast", event => showToast(event.detail));
  document.addEventListener("ma:dialog-close", closeDialogHost);
  document.addEventListener("ma:refresh", event => {
    (event.detail.targets || []).forEach(selector => {
      const target = document.querySelector(selector);
      if (target && window.htmx) {
        if (selector === "#resource-detail") {
          const url = new URL(location.href);
          url.searchParams.set("fragment", "detail");
          htmx.ajax("GET", url.pathname + url.search, { target, swap: "outerHTML" });
          return;
        }
        // A parent refresh includes its related list; avoid two racing replacements.
        if (selector === "#related-list" && (event.detail.targets || []).includes("#resource-detail")
            && document.querySelector("#resource-detail")) return;
        htmx.trigger(target, "ma:reload");
      }
    });
  });
})();
