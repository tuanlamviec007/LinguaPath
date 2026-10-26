(() => {
  const form = document.querySelector('[data-mistake-review]');
  if (!form) return;
  // Shared draft persistence owns saving, leave warnings and abandon prompts.
  const autosaveEnabled = 'practiceDraft' in form.dataset;

  const questions = [...form.querySelectorAll('[data-question]')];
  const total = Number(form.dataset.total) || questions.length;
  const answeredCount = form.querySelector('[data-answered-count]');
  const status = form.querySelector('[data-review-status]');
  const progressbar = form.querySelector('[data-progressbar]');
  const progressFill = form.querySelector('[data-progress-fill]');
  const submitButton = form.querySelector('[data-review-submit]');
  const submitStatus = form.querySelector('[data-submit-status]');
  const initialSubmitLabel = submitButton ? submitButton.textContent : '';
  let dirty = false;
  let submitting = false;
  let submitPending = false;
  let abandoning = false;

  const updateCount = () => {
    const answered = questions.filter((question) => question.querySelector('input[type="radio"]:checked')).length;
    const unanswered = Math.max(0, total - answered);
    if (answeredCount) answeredCount.textContent = String(answered);
    if (progressbar) progressbar.setAttribute('aria-valuenow', String(answered));
    if (progressFill) progressFill.style.width = `${total ? (answered / total) * 100 : 0}%`;
    if (status) status.textContent = unanswered
      ? `Còn ${unanswered} câu chưa trả lời.${autosaveEnabled ? '' : ' Lựa chọn chỉ được lưu khi bạn nộp lượt ôn.'}`
      : `Đã trả lời tất cả câu.${autosaveEnabled ? ' Bạn có thể nộp để xem lời giải.' : ' Lựa chọn chỉ được lưu khi bạn nộp lượt ôn.'}`;
  };

  updateCount();
  form.addEventListener('change', (event) => {
    if (event.target.matches('input[type="radio"]')) {
      if (!autosaveEnabled) dirty = true;
      updateCount();
    }
  });

  if (!autosaveEnabled) {
    window.addEventListener('beforeunload', (event) => {
      if (!dirty || submitting || abandoning) return;
      event.preventDefault();
      event.returnValue = '';
    });
  }

  const abandonForm = document.querySelector('[data-mistake-abandon]');
  if (abandonForm && !autosaveEnabled) {
    abandonForm.addEventListener('submit', (event) => {
      if (!window.confirm('Dừng lượt ôn này? Các lựa chọn hiện tại sẽ bị mất.')) {
        event.preventDefault();
        return;
      }
      abandoning = true;
      dirty = false;
    });
  }

  if (!autosaveEnabled) form.addEventListener('submit', (event) => {
    if (submitting || submitPending) {
      event.preventDefault();
      return;
    }
    submitPending = true;
    // Let other form/document submit handlers cancel first. If they do, keep
    // the answers and leave-page warning intact and allow another attempt.
    queueMicrotask(() => {
      submitPending = false;
      if (event.defaultPrevented) return;
      submitting = true;
      dirty = false;
      if (submitButton) {
        submitButton.disabled = true;
        submitButton.textContent = 'Đang nộp lượt ôn…';
      }
      if (submitStatus) submitStatus.textContent = 'Đang chấm lượt ôn.';
    });
  });

  window.addEventListener('pageshow', (event) => {
    submitting = false;
    submitPending = false;
    abandoning = false;
    dirty = !autosaveEnabled && Boolean(event.persisted && questions.some((question) => question.querySelector('input[type="radio"]:checked')));
    if (submitButton && !autosaveEnabled) {
      submitButton.disabled = false;
      submitButton.textContent = initialSubmitLabel;
    }
    if (submitStatus) submitStatus.textContent = '';
    updateCount();
  });
})();
