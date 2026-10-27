/* Local decorative interactions; no network, storage or learning-state writes. */
(() => {
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const greetings = ['Một từ mới cũng là một bước tiến.', 'Cứ thử trước nhé. Sai rồi mình học lại.', 'Bạn chọn nhịp học, Lumi cổ vũ bạn!', 'Học một chút, nghỉ một chút. Bạn đang làm tốt.'];
  document.querySelectorAll('[data-lumi]').forEach((companion) => {
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
