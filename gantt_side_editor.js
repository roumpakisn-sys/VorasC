/* Optional UI only. No network requests, assignment data or database writes. */
(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.StaffProSideEditor = api;
})(typeof window === 'undefined' ? globalThis : window, function () {
  'use strict';
  const MESSAGE = 'Υπάρχουν αλλαγές χωρίς αποθήκευση. Να τις αφήσουμε και να συνεχίσουμε;';

  function snapshot(form) {
    return JSON.stringify(Array.from(form.querySelectorAll(
      'input, textarea, select, [role="spinbutton"], [data-baseweb="select"], [role="group"][aria-label="Selected values"]'
    )).map(el => [el.tagName, el.type || '', el.checked || false,
      el.getAttribute('aria-valuenow') || '',
      el.matches('[data-baseweb="select"], [role="group"][aria-label="Selected values"]')
        ? el.textContent : el.value || el.textContent]));
  }

  function install(frame, config) {
    let win, doc;
    try { win = frame.parent; doc = win.document; } catch (_) { return; }
    const previous = win.staffProSideEditor;
    const same = previous && previous.identity === config.identity && previous.selector === config.selector;
    const state = {identity: config.identity, selector: config.selector, dirty: same ? previous.dirty : false,
      baseline: same ? previous.baseline : null};
    if (previous) previous.cleanup();
    let pane, form, timer, observer, style, disposed = false, wasAttached = false;
    const selector = config.selector;
    const listeners = [];
    const listen = (target, type, fn, options) => {
      target.addEventListener(type, fn, options);
      listeners.push(() => target.removeEventListener(type, fn, options));
    };

    state.allowLeave = function (barId) {
      if (barId && barId === config.barId) return true;
      refreshDirty();
      return !state.dirty || win.confirm(MESSAGE);
    };
    state.cleanup = function () {
      if (disposed) return;
      disposed = true;
      win.clearInterval(timer);
      if (observer) observer.disconnect();
      listeners.forEach(remove => remove());
      if (pane) pane.classList.remove('staffpro-drawer-active');
      if (style) style.remove();
      if (win.staffProSideEditor === state) delete win.staffProSideEditor;
    };
    win.staffProSideEditor = state;

    function refreshDirty() {
      if (!pane || !pane.isConnected) return;
      form = pane.querySelector('[data-testid="stForm"]');
      if (!form || !form.querySelector('[data-staffpro-form="' + config.identity + '"]')) return;
      if (!form || !Array.from(form.querySelectorAll('button')).some(
        b => b.textContent.includes('Αποθήκευση'))) return;
      const current = snapshot(form);
      if (state.baseline === null) state.baseline = current;
      else state.dirty = current !== state.baseline;
    }

    function attach() {
      const next = doc.querySelector(selector);
      if (!next) {
        // Remove listeners/styles when navigating away; a later run installs anew.
        if (wasAttached) state.cleanup();
        return;
      }
      pane = next;
      wasAttached = true;
      pane.classList.add('staffpro-drawer-active');
      refreshDirty();
    }

    // Leave the original inline form usable if parent access or JS is unavailable.
    style = doc.createElement('style');
    style.textContent = `
      ${selector}.staffpro-drawer-active {
        position: fixed !important; top: 70px; right: 16px;
        width: min(540px, calc(100vw - 32px)) !important;
        max-height: calc(100dvh - 86px); overflow-y: auto;
        overscroll-behavior: contain; z-index: 99;
        background: var(--background-color, #fff); color: var(--text-color, #17212f);
        padding: 16px; border: 1px solid #b8c5d5; border-radius: 14px;
        box-shadow: 0 12px 40px #0f172a30;
      }
      ${selector}.staffpro-drawer-active h3 { font-size: 1.2rem; }
      ${selector}.staffpro-drawer-active [data-testid="stForm"] { min-width: 0; }
      ${selector}.staffpro-drawer-active .st-key-gantt_side_editor_desktop_close,
      ${selector}.staffpro-drawer-active .st-key-gantt_side_editor_mobile_close {
        position: sticky; top: -16px; z-index: 2;
        background: var(--background-color, #fff); padding: 6px 0;
      }
      @media (max-width: 767px) {
        ${selector}.staffpro-drawer-active {
          top: auto; bottom: 0; right: 0; width: 100% !important;
          max-height: 78dvh; border-radius: 16px 16px 0 0;
          padding-bottom: max(16px, env(safe-area-inset-bottom));
        }
      }
    `;
    doc.head.appendChild(style);

    const stop = event => {
      event.preventDefault(); event.stopImmediatePropagation();
    };
    function mayDiscard(event) {
      const target = event.target;
      if (!target || !target.closest || !pane) return false;
      if (form && form.contains(target)) return false;
      // Select/time/date popovers live outside the form DOM. Their opening
      // controls are checked before they open, so editing an open popup is safe.
      if (target.closest('[data-baseweb="popover"], [role="listbox"], [role="dialog"]')) return false;
      return !!target.closest('button, a, input, select, textarea, label, [role="combobox"], [role="checkbox"], summary');
    }
    let approvedControl = null, approvedAt = 0;
    const control = event => event.target.closest('button, a, label, [data-baseweb="select"], input, select, textarea, [role="combobox"], [role="checkbox"], summary');
    function onClick(event) {
      if (approvedControl && approvedControl === control(event) && Date.now() - approvedAt < 1000) {
        approvedControl = null;
        return;
      }
      if (mayDiscard(event) && !state.allowLeave()) stop(event);
    }
    function onMouseDown(event) {
      // React select/checkbox controls act before click, buttons act on click.
      if (mayDiscard(event) && !event.target.closest('button, a, summary')) {
        if (!state.allowLeave()) stop(event);
        else { approvedControl = control(event); approvedAt = Date.now(); }
      }
    }
    function onKey(event) {
      if (event.key === 'Escape' && !doc.querySelector('[data-baseweb="popover"]')) {
        const close = pane && pane.querySelector('button');
        if (close) { stop(event); close.click(); }
      } else if ((event.key === 'Enter' || event.key === ' ') && mayDiscard(event)) {
        if (!state.allowLeave()) stop(event);
        else { approvedControl = control(event); approvedAt = Date.now(); }
      }
    }
    listen(doc, 'click', onClick, true);
    listen(doc, 'pointerdown', onMouseDown, true);
    listen(doc, 'keydown', onKey, true);
    listen(win, 'beforeunload', event => {
      refreshDirty();
      if (state.dirty) { event.preventDefault(); event.returnValue = ''; }
    });
    // The Gantt is an iframe; its click handler explicitly consults this guard.
    listen(frame, 'pagehide', () => {
      // Keep the baseline for a form submit/rerun. The next installer takes over.
      if (win.staffProSideEditor === state) {
        win.setTimeout(() => { if (!doc.querySelector(selector)) state.cleanup(); }, 500);
      }
    });
    observer = new win.MutationObserver(attach);
    observer.observe(doc.body, {childList: true, subtree: true});
    timer = win.setInterval(refreshDirty, 250);
    attach();
    return state;
  }
  return {install, snapshot};
});
