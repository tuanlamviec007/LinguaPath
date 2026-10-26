(() => {
  const form = document.querySelector('[data-tutor-form]');
  if (!form) return;
  const textarea = form.querySelector('textarea[name="question"]');
  const contextQuestion = form.querySelector('input[name="question_id"]');
  const counter = form.querySelector('[data-char-count]');
  const submitButton = form.querySelector('[data-submit-question]');
  const submitStatus = form.querySelector('[data-submit-status]');
  const automaticQuery = form.querySelector('input[name="query_mode"][value="auto"]');
  const descriptionQuery = form.querySelector('input[name="query_mode"][value="description"]');
  const lookupResponse = form.querySelector('input[name="response_mode"][value="lookup"]');
  const aiResponse = form.querySelector('input[name="response_mode"][value="ai"]');
  const initialSubmitLabel = submitButton ? submitButton.innerHTML : '';
  const automaticSubmitLabel = automaticQuery ? 'Gửi câu hỏi <span aria-hidden="true">→</span>' : initialSubmitLabel;
  if (!textarea) return;

  const updateCount = () => {
    if (counter) counter.textContent = String(textarea.value.length);
  };

  const syncQueryMode = () => {
    const description = descriptionQuery?.checked === true;
    if (aiResponse) aiResponse.disabled = description;
    if (description) {
      if (lookupResponse) lookupResponse.checked = true;
      if (aiResponse) aiResponse.checked = false;
      if (contextQuestion) contextQuestion.value = '';
    }
    textarea.placeholder = description
      ? 'Ví dụ: Một người học cùng lớp với mình.'
      : 'Ví dụ: Khi nào dùng despite và although?';
    if (submitButton && form.dataset.submitting !== 'true') {
      if (description) submitButton.textContent = 'Tìm từ gợi ý →';
      else submitButton.innerHTML = automaticSubmitLabel;
    }
  };

  updateCount();
  syncQueryMode();
  textarea.addEventListener('input', updateCount);
  automaticQuery?.addEventListener('change', syncQueryMode);
  descriptionQuery?.addEventListener('change', syncQueryMode);

  document.querySelectorAll('[data-prompt]').forEach((button) => {
    button.addEventListener('click', () => {
      textarea.value = button.dataset.prompt || '';
      if (contextQuestion) contextQuestion.value = '';
      if (automaticQuery) automaticQuery.checked = true;
      if (descriptionQuery) descriptionQuery.checked = false;
      if (lookupResponse) lookupResponse.checked = true;
      if (aiResponse) aiResponse.checked = false;
      syncQueryMode();
      updateCount();
      textarea.focus();
      const end = textarea.value.length;
      textarea.setSelectionRange(end, end);
    });
  });

  form.addEventListener('submit', (event) => {
    if (!form.checkValidity()) return;
    syncQueryMode();
    if (form.dataset.submitting === 'true') {
      event.preventDefault();
      return;
    }
    form.dataset.submitting = 'true';
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = descriptionQuery?.checked ? 'Đang tìm từ gợi ý…' : 'Đang tìm câu trả lời…';
    }
    if (submitStatus) submitStatus.textContent = descriptionQuery?.checked ? 'Đang đối chiếu mô tả với học liệu.' : 'Đang tra cứu học liệu liên quan.';
  });

  // Browsers may restore a submitted page from the back-forward cache.
  // Clear the one-submit guard so a returning learner can ask again.
  window.addEventListener('pageshow', () => {
    form.dataset.submitting = 'false';
    if (submitButton) {
      submitButton.disabled = false;
      submitButton.innerHTML = initialSubmitLabel;
    }
    if (submitStatus) submitStatus.textContent = '';
    syncQueryMode();
  });
})();
