/* A local sample only: no storage, account, tracking, grading API or XP writes. */
(() => {
  'use strict';
  const root = document.querySelector('[data-welcome-demo]');
  if (!root) return;
  const form = root.querySelector('[data-demo-quiz]');
  const feedback = root.querySelector('[data-demo-feedback]');
  const finish = root.querySelector('[data-demo-finish]');
  root.addEventListener('click', (event) => {
    if (event.target.closest('.flash-front [data-flip]')) {
      root.querySelector('.welcome-quiz').open = true;
      root.querySelector('[data-demo-step="word"]')?.classList.add('is-done');
    }
  });
  form.addEventListener('submit', (event) => {
    const choice = event.submitter?.getAttribute('data-demo-choice');
    if (!['A', 'B', 'C'].includes(choice)) return; // Native GET remains the fallback.
    event.preventDefault();
    form.querySelectorAll('[data-demo-choice]').forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.demoChoice === choice));
    });
    const correct = choice === 'B';
    feedback.textContent = correct
      ? 'Đúng rồi! “Consistent” là đều đặn, nhất quán. Bạn vừa thử xong một vòng học nhỏ.'
      : 'Chưa đúng lần này. “Consistent” là đều đặn, nhất quán — chọn B để thử lại nhé.';
    feedback.classList.toggle('is-correct', correct);
    finish.hidden = !correct;
    root.classList.toggle('is-complete', correct);
    root.querySelector('[data-demo-step="recall"]')?.classList.toggle('is-done', correct);
    if (correct) root.dispatchEvent(new CustomEvent('linguapath:celebrate', { bubbles: true }));
  });
})();
