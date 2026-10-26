/* Explicit save/remove requests are idempotent, including after a lost response. */
(() => {
  'use strict';
  const forms = Array.from(document.querySelectorAll('[data-save-word]'));
  const busy = new Set();
  for (const form of forms) {
    form.addEventListener('submit', async event => {
      const id = form.getAttribute('data-card-id');
      const action = form.querySelector('input[name="action"]');
      const csrf = form.querySelector('input[name="csrfmiddlewaretoken"]');
      if (!id || !action || !csrf || typeof fetch !== 'function') return;
      event.preventDefault();
      if (busy.has(id)) return;
      busy.add(id);
      const siblings = forms.filter(item => item.getAttribute('data-card-id') === id);
      const requested = action.value;
      const setStatus = (state, message) => siblings.forEach(item => {
        const status = item.querySelector('[data-save-status]');
        if (status) { status.textContent = message; status.setAttribute('data-state', state); }
      });
      siblings.forEach(item => { item.querySelector('button[type="submit"]').disabled = true; });
      setStatus('saving', 'Đang lưu…');
      const controller = typeof AbortController === 'function' ? new AbortController() : null;
      const timeout = controller ? window.setTimeout(() => controller.abort(), 12000) : null;
      try {
        const payload = new URLSearchParams({action: requested, csrfmiddlewaretoken: csrf.value});
        const response = await fetch(form.getAttribute('action'), {
          method: 'POST', credentials: 'same-origin', body: payload.toString(),
          headers: {'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8', 'X-CSRFToken': csrf.value},
          ...(controller ? {signal: controller.signal} : {}),
        });
        const result = await response.json();
        if (!response.ok || response.redirected || result.ok !== true || String(result.card_id) !== id
            || result.saved !== (requested === 'save') || !Number.isSafeInteger(result.saved_count) || result.saved_count < 0) throw new Error('save-unconfirmed');
        siblings.forEach(item => {
          const button = item.querySelector('button[type="submit"]');
          item.querySelector('input[name="action"]').value = result.saved ? 'remove' : 'save';
          button.classList.toggle('is-saved', result.saved);
          button.setAttribute('aria-pressed', String(result.saved));
          button.setAttribute('aria-label', `${result.saved ? 'Bỏ' : 'Lưu'} ${item.getAttribute('data-term')} ${result.saved ? 'khỏi' : 'vào'} sổ từ`);
          item.querySelector('[data-save-label]').textContent = result.saved ? 'Đã lưu' : 'Lưu từ';
          item.querySelector('[data-save-icon]').textContent = result.saved ? '★' : '☆';
        });
        document.querySelectorAll('[data-saved-word-count]').forEach(item => { item.textContent = String(result.saved_count); });
        setStatus('saved', result.saved ? 'Đã thêm vào sổ từ.' : 'Đã bỏ khỏi sổ từ.');
      } catch (_) {
        setStatus('error', 'Chưa xác nhận được. Hãy thử lại; trạng thái trên trang được giữ nguyên.');
      } finally {
        if (timeout !== null) window.clearTimeout(timeout);
        busy.delete(id);
        siblings.forEach(item => { item.querySelector('button[type="submit"]').disabled = false; });
      }
    });
  }
})();
