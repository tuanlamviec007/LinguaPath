/* Progressive quiz navigation and revision-checked drafts. Scoring stays on the server. */
(() => {
  'use strict';
  const form = document.querySelector('[data-quiz-form]');
  if (!form) return;
  const questions = Array.from(form.querySelectorAll('[data-quiz-question]'));
  if (!questions.length) return;
  const previous = form.querySelector('[data-quiz-prev]');
  const next = form.querySelector('[data-quiz-next]');
  const submit = form.querySelector('[data-quiz-submit]');
  const nav = form.querySelector('[data-quiz-nav]');
  const steps = Array.from(form.querySelectorAll('[data-quiz-goto]'));
  const position = form.querySelector('[data-quiz-position]');
  const answeredLabel = form.querySelector('[data-quiz-answered]');
  const progress = form.querySelector('[data-quiz-progress]');
  const feedback = form.querySelector('[data-quiz-feedback]');
  const savebar = form.querySelector('[data-quiz-savebar]');
  const saveStatus = form.querySelector('[data-quiz-save-status]');
  const saveButton = form.querySelector('[data-quiz-save]');
  const reloadButton = form.querySelector('[data-quiz-reload]');
  const revisionInput = form.querySelector('[data-quiz-revision]');
  const csrfInput = form.querySelector('input[name="csrfmiddlewaretoken"]');
  const draftUrl = form.getAttribute('data-quiz-draft-url');
  const resumeUrl = form.getAttribute('data-quiz-resume-url');
  let revision = Number(form.getAttribute('data-quiz-draft-revision') || '0');
  let editVersion = form.getAttribute('data-quiz-draft-dirty') === 'true' ? 1 : 0;
  let savedVersion = 0;
  let blocked = form.getAttribute('data-quiz-draft-conflict') === 'true';
  let index = 0;
  let submitted = false;
  let submitWaiting = false;
  let inFlight = null;
  let timer = null;
  const textInputs = new Set(questions.map(question => question.querySelector('input[data-quiz-text-answer]')).filter(Boolean));
  const composingInputs = new Set();
  const textInput = question => question.querySelector('input[data-quiz-text-answer]');
  const answerInput = question => textInput(question) || question.querySelector('input[type="radio"]:checked');
  const isAnswered = question => {
    const answer = answerInput(question);
    return Boolean(answer && (!textInput(question) || answer.value.trim()));
  };
  const answerSignature = () => JSON.stringify(questions.map(question => {
    const answer = answerInput(question);
    return answer ? answer.value : '';
  }));
  let observedAnswers = answerSignature();
  const answerCount = () => questions.filter(isAnswered).length;
  const dirty = () => editVersion !== savedVersion;
  const clearDebounce = () => { if (timer !== null) { window.clearTimeout(timer); timer = null; } };
  const setStatus = (state, message) => {
    if (saveStatus) { saveStatus.textContent = message; saveStatus.setAttribute('data-state', state); }
  };
  function lockDraft(message, state = 'conflict') {
    blocked = true;
    clearDebounce();
    if (saveButton) saveButton.disabled = true;
    if (submit) submit.disabled = true;
    if (reloadButton) reloadButton.hidden = false;
    setStatus(state, message);
  }
  function update() {
    const count = answerCount();
    if (answeredLabel) answeredLabel.textContent = `${count}/${questions.length} câu đã trả lời`;
    if (position) position.textContent = `Câu ${index + 1} / ${questions.length}`;
    if (progress) {
      progress.setAttribute('aria-valuenow', String(count));
      const fill = progress.querySelector('span');
      if (fill) fill.style.width = `${100 * count / questions.length}%`;
    }
    steps.forEach((step, stepIndex) => {
      const done = isAnswered(questions[stepIndex]);
      step.classList.toggle('is-answered', done);
      step.classList.toggle('is-current', stepIndex === index);
      step.setAttribute('aria-label', `Câu ${stepIndex + 1}${done ? ', đã trả lời' : ', chưa trả lời'}`);
      if (stepIndex === index) step.setAttribute('aria-current', 'step');
      else step.removeAttribute('aria-current');
    });
  }
  function show(number, focus = true) {
    index = Math.max(0, Math.min(number, questions.length - 1));
    questions.forEach((question, questionIndex) => { question.hidden = questionIndex !== index; });
    if (previous) { previous.hidden = false; previous.disabled = index === 0; }
    if (next) next.hidden = index === questions.length - 1;
    if (submit) submit.hidden = index !== questions.length - 1;
    if (feedback) feedback.textContent = '';
    update();
    if (focus) (textInput(questions[index]) || questions[index]).focus();
  }
  function navigate(number) {
    if (composingInputs.size) {
      if (feedback) feedback.textContent = 'Hãy hoàn tất nhập từ trước khi chuyển câu.';
      return;
    }
    show(number);
  }
  function scheduleSave() {
    clearDebounce();
    if (!draftUrl || blocked || submitted || submitWaiting || composingInputs.size) return;
    timer = window.setTimeout(() => { timer = null; saveLatest(); }, 600);
  }
  function formatSavedAt(value) {
    if (!value) return '';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return '';
    return ` · ${date.toLocaleTimeString('vi-VN', {hour: '2-digit', minute: '2-digit'})}`;
  }
  function saveLatest() {
    clearDebounce();
    if (blocked || submitted) return Promise.resolve(false);
    if (composingInputs.size) {
      setStatus('pending', 'Đang nhập từ; bản nháp sẽ lưu khi bạn nhập xong.');
      return Promise.resolve(false);
    }
    if (inFlight) return inFlight;
    if (!dirty()) { setStatus('saved', 'Các câu trả lời hiện tại đã được lưu.'); return Promise.resolve(true); }
    if (!draftUrl || !csrfInput || !Number.isSafeInteger(revision)) {
      setStatus('error', 'Chưa lưu được bản nháp. Câu trả lời vẫn còn trên trang; bạn có thể nộp bài hoặc tải lại sau khi lưu.');
      return Promise.resolve(false);
    }
    const sentVersion = editVersion;
    const sentRevision = revision;
    const payload = new URLSearchParams();
    payload.set('csrfmiddlewaretoken', csrfInput.value);
    payload.set('revision', String(sentRevision));
    questions.forEach((question, questionIndex) => {
      const answer = answerInput(question);
      if (isAnswered(question)) payload.set(`answer_${questionIndex + 1}`, answer.value);
    });
    setStatus('saving', 'Đang lưu câu trả lời…');
    if (saveButton) saveButton.disabled = true;
    const controller = typeof AbortController === 'function' ? new AbortController() : null;
    const timeout = controller ? window.setTimeout(() => controller.abort(), 15000) : null;
    let succeeded = false;
    const task = (async () => {
      await Promise.resolve();
      try {
        const response = await fetch(draftUrl, {
          method: 'POST', credentials: 'same-origin',
          headers: {'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8', 'X-CSRFToken': csrfInput.value},
          body: payload.toString(), ...(controller ? {signal: controller.signal} : {}),
        });
        let result;
        try { result = await response.json(); } catch (_) { throw new Error('invalid-response'); }
        if (response.redirected) throw new Error('login-expired');
        if (response.status === 409) {
          lockDraft(result.status === 'submitted'
            ? 'Lượt quiz đã được nộp ở một tab khác. Hãy tải lại để xem kết quả.'
            : 'Bản nháp đã thay đổi ở tab khác. Câu trả lời trên trang vẫn được giữ; tải lại để dùng bản mới nhất.');
          return false;
        }
        if (response.status === 410) {
          lockDraft('Lượt quiz không còn khả dụng. Câu trả lời trên trang vẫn được giữ; tải lại để kiểm tra.', 'error');
          return false;
        }
        if (!response.ok || !result || result.ok !== true || result.status !== 'saved'
            || !Number.isSafeInteger(result.revision) || ![sentRevision, sentRevision + 1].includes(result.revision)
            || !Number.isSafeInteger(result.saved_count) || result.saved_count < 0 || result.saved_count > questions.length) {
          throw new Error('save-rejected');
        }
        if (blocked) return false;
        revision = result.revision;
        if (revisionInput) revisionInput.value = String(revision);
        savedVersion = sentVersion;
        succeeded = true;
        if (dirty()) setStatus('pending', 'Đã lưu bản trước; các câu trả lời mới đang chờ lưu…');
        else setStatus('saved', `Đã lưu ${result.saved_count}/${questions.length} câu${formatSavedAt(result.last_saved_at)}.`);
        return true;
      } catch (_) {
        if (!blocked) setStatus('error', 'Chưa xác nhận được bản nháp đã lưu. Câu trả lời vẫn còn trên trang; hãy bấm Lưu ngay để thử lại.');
        return false;
      } finally {
        if (timeout !== null) window.clearTimeout(timeout);
        inFlight = null;
        if (saveButton) saveButton.disabled = blocked;
        if (succeeded && dirty() && !submitWaiting && !blocked && !submitted) scheduleSave();
      }
    })();
    inFlight = task;
    return task;
  }
  function markSubmitted() {
    submitted = true;
    clearDebounce();
    if (submit) { submit.disabled = true; submit.textContent = 'Đang chấm bài…'; }
  }
  form.noValidate = true;
  form.classList.add('is-enhanced');
  if (nav) nav.hidden = false;
  if (savebar) savebar.hidden = false;
  if (previous) previous.addEventListener('click', () => navigate(index - 1));
  if (next) next.addEventListener('click', () => navigate(index + 1));
  steps.forEach(step => step.addEventListener('click', () => {
    const target = Number(step.getAttribute('data-quiz-goto'));
    if (Number.isInteger(target)) navigate(target);
  }));
  function answerEdited() {
    const signature = answerSignature();
    if (signature === observedAnswers) return;
    observedAnswers = signature;
    editVersion += 1;
    update();
    if (feedback) feedback.textContent = '';
    if (blocked || submitted) return;
    setStatus('pending', composingInputs.size
      ? 'Đang nhập từ; bản nháp sẽ lưu khi bạn nhập xong.'
      : 'Có câu trả lời mới, đang chờ lưu…');
    scheduleSave();
  }
  form.addEventListener('change', event => {
    if (!textInputs.has(event.target)) answerEdited();
  });
  form.addEventListener('input', event => {
    if (!textInputs.has(event.target)) return;
    if (event.isComposing) { composingInputs.add(event.target); clearDebounce(); }
    answerEdited();
  });
  form.addEventListener('compositionstart', event => {
    if (!textInputs.has(event.target)) return;
    composingInputs.add(event.target);
    clearDebounce();
  });
  form.addEventListener('compositionend', event => {
    if (!textInputs.has(event.target)) return;
    composingInputs.delete(event.target);
    answerEdited();
    if (dirty() && !blocked && !submitted) scheduleSave();
  });
  form.addEventListener('keydown', event => {
    if (!textInputs.has(event.target) || (event.key !== 'Enter' && event.keyCode !== 13)) return;
    // Let the IME consume Enter to commit text. The submit handler separately
    // blocks submissions while composition is active.
    if (event.isComposing || event.keyCode === 229 || composingInputs.size) return;
    event.preventDefault();
    if (submitted || submitWaiting) return;
    if (index < questions.length - 1) navigate(index + 1);
    else form.requestSubmit();
  });
  if (saveButton) saveButton.addEventListener('click', () => saveLatest());
  if (reloadButton) reloadButton.addEventListener('click', () => {
    if (resumeUrl) window.location.assign(resumeUrl);
    else window.location.reload();
  });
  form.addEventListener('submit', event => {
    if (composingInputs.size) {
      event.preventDefault();
      if (feedback) feedback.textContent = 'Hãy hoàn tất nhập từ trước khi nộp bài.';
      return;
    }
    if (submitted || submitWaiting) { event.preventDefault(); return; }
    const unanswered = questions.findIndex(question => !isAnswered(question));
    if (unanswered !== -1) {
      event.preventDefault();
      show(unanswered);
      if (feedback) feedback.textContent = `Còn ${questions.length - answerCount()} câu chưa trả lời. Hãy trả lời câu ${unanswered + 1}.`;
      const firstOption = textInput(questions[unanswered]) || questions[unanswered].querySelector('input[type="radio"]');
      if (firstOption) firstOption.focus();
      return;
    }
    if (blocked) {
      event.preventDefault();
      if (feedback) feedback.textContent = 'Hãy tải lại bản mới nhất trước khi nộp để tránh ghi đè câu trả lời ở tab khác.';
      if (reloadButton) reloadButton.focus();
      return;
    }
    clearDebounce();
    if (inFlight) {
      event.preventDefault();
      submitWaiting = true;
      if (submit) { submit.disabled = true; submit.textContent = 'Đang chờ lưu…'; }
      const pending = inFlight;
      pending.then(ok => {
        submitWaiting = false;
        if (submit) { submit.disabled = blocked; submit.textContent = 'Nộp bài & xem kết quả ✦'; }
        if (ok && !blocked) form.requestSubmit();
        else if (feedback) feedback.textContent = blocked
          ? 'Chưa thể nộp do bản nháp đã thay đổi. Hãy kiểm tra thông báo lưu.'
          : 'Lưu bản nháp chưa thành công. Câu trả lời vẫn được giữ; thử Lưu ngay hoặc nộp lại để máy chủ kiểm tra.';
      });
      return;
    }
    if (revisionInput) revisionInput.value = String(revision);
    markSubmitted();
  });
  window.addEventListener('beforeunload', event => {
    if (submitted || (!dirty() && !inFlight && !composingInputs.size)) return;
    event.preventDefault();
    event.returnValue = '';
  });
  window.addEventListener('pageshow', event => {
    if (!event.persisted) return;
    submitted = false;
    submitWaiting = false;
    if (submit) { submit.disabled = false; submit.textContent = 'Nộp bài & xem kết quả ✦'; }
    update();
    lockDraft('Trang được khôi phục từ bộ nhớ trình duyệt. Tải lại để tiếp tục từ bản nháp mới nhất.');
  });
  if (blocked) lockDraft('Bản nháp đã thay đổi ở tab khác. Câu trả lời trên trang vẫn được giữ; tải lại để dùng bản mới nhất.');
  else if (dirty()) { setStatus('pending', 'Câu trả lời trên trang chưa được lưu.'); scheduleSave(); }
  const firstUnanswered = questions.findIndex(question => !isAnswered(question));
  show(firstUnanswered === -1 ? 0 : firstUnanswered, false);
})();
