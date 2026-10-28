/* Review filters only change visibility; grading and rewards stay on the server. */
(() => {
  const review = document.querySelector('[data-result-review]');
  if (!review) return;
  const toolbar = review.querySelector('[data-result-filters]');
  const status = review.querySelector('[data-result-status]');
  const cards = [...review.querySelectorAll('[data-result-card]')];
  const buttons = [...review.querySelectorAll('[data-result-filter]')];
  if (!toolbar || !status || !cards.length || !buttons.length) return;
  toolbar.hidden = false;
  buttons.forEach((button) => button.addEventListener('click', () => {
    const mode = button.dataset.resultFilter;
    if (!['all', 'missed'].includes(mode)) return;
    let visible = 0;
    cards.forEach((card) => {
      card.hidden = mode === 'missed' && card.dataset.resultCorrect === 'true';
      if (!card.hidden) visible++;
    });
    buttons.forEach((item) => item.setAttribute('aria-pressed', String(item === button)));
    status.textContent = visible ? `Đang xem ${visible} từ${mode === 'missed' ? ' cần ôn' : ''}.` : 'Không có câu sai trong lượt này. Bạn vẫn có thể xem lại tất cả từ.';
  }));
})();
