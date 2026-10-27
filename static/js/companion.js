/* Local decorative interactions. Only an optional display preference is stored. */
(() => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  let collapsed = false;
  try { collapsed = window.localStorage.getItem('linguapath.lumi.collapsed') === 'true'; } catch (_) {}
  const companions = [...document.querySelectorAll('[data-lumi]')];
  function updateVisibility() {
    companions.forEach((companion) => {
      companion.classList.toggle('is-collapsed', collapsed);
      const toggle = companion.querySelector('[data-lumi-toggle]');
      if (!toggle) return;
      toggle.hidden = false;
      toggle.textContent = collapsed ? 'Mở Lumi · Bạn đồng hành' : 'Thu gọn Lumi';
      toggle.setAttribute('aria-expanded', String(!collapsed));
    });
  }
  updateVisibility();
  const greetings = ['Một từ mới cũng là một bước tiến.', 'Cứ thử trước nhé. Sai rồi mình học lại.', 'Bạn chọn nhịp học, Lumi cổ vũ bạn!', 'Học một chút, nghỉ một chút. Bạn đang làm tốt.'];
  companions.forEach((companion) => {
    const toggle = companion.querySelector('[data-lumi-toggle]');
    if (toggle) toggle.addEventListener('click', () => {
      collapsed = !collapsed;
      try { window.localStorage.setItem('linguapath.lumi.collapsed', String(collapsed)); } catch (_) {}
      updateVisibility();
    });
    const button = companion.querySelector('[data-lumi-greet]');
    const message = companion.querySelector('[data-lumi-message]');
    if (!button || !message) return;
    let index = 0;
    button.addEventListener('click', () => {
      message.textContent = greetings[index++ % greetings.length];
      button.classList.remove('is-waving');
      if (!reduced.matches) {
        void button.offsetWidth;
        button.classList.add('is-waving');
      }
    });
  });
  const fine = window.matchMedia('(hover: hover) and (pointer: fine)');
  document.querySelectorAll('.welcome-demo, .lp-discovery-card').forEach((card) => {
    const reset = () => { card.style.removeProperty('--lumi-rx'); card.style.removeProperty('--lumi-ry'); };
    card.addEventListener('pointermove', (event) => {
      if (reduced.matches || !fine.matches) return reset();
      const rect = card.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      card.style.setProperty('--lumi-rx', `${(0.5 - (event.clientY - rect.top) / rect.height) * 3}deg`);
      card.style.setProperty('--lumi-ry', `${((event.clientX - rect.left) / rect.width - 0.5) * 3}deg`);
    });
    card.addEventListener('pointerleave', reset);
    reduced.addEventListener('change', reset);
  });
})();
