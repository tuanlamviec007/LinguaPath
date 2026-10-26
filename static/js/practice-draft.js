/* Practice and mistake-review drafts use the same revision-checked protocol. */
(() => {
  const form = document.querySelector('[data-practice-draft]');
  if (!form) return;
  const status = form.querySelector('[data-draft-status]');
  const countLabel = form.querySelector('[data-answered-count]');
  const progress = form.querySelector('[data-progressbar]');
  const progressFill = form.querySelector('[data-progress-fill]');
  const saveButton = form.querySelector('[data-save-draft]');
  const reloadButton = form.querySelector('[data-reload-draft]');
  const revisionInput = form.querySelector('[data-draft-revision]');
  const submitButtons = [...form.querySelectorAll('[type="submit"]')];
  const csrfToken = form.querySelector('input[name="csrfmiddlewaretoken"]')?.value;
  const total = Number(form.dataset.total) || 0;
  let revision = Number(form.dataset.draftRevision);
  let version = 0;
  let dirty = form.dataset.draftUnsaved === 'true';
  let blocked = false;
  let submitting = false;
  let submitPending = false;
  let submitWaiting = false;
  let debounceTimer = null;
  let activeRequest = null;
  let epoch = 0;

  function updateProgress() {
    const answered = form.querySelectorAll('input[type="radio"]:checked').length;
    if (countLabel) countLabel.textContent = String(answered);
    if (progress) progress.setAttribute('aria-valuenow', String(answered));
    if (progressFill) progressFill.style.width = `${total ? Math.min(100, answered / total * 100) : 0}%`;
  }
  function setStatus(message, state = '') {
    if (status) { status.textContent = message; status.dataset.state = state; }
  }
  function warnBeforeLeave(event) {
    if (submitting || (!dirty && !activeRequest)) return;
    event.preventDefault();
    event.returnValue = '';
  }
  function updateWarning() {
    if (!submitting && (dirty || activeRequest)) window.addEventListener('beforeunload', warnBeforeLeave);
    else window.removeEventListener('beforeunload', warnBeforeLeave);
  }
  function clearDebounce() { window.clearTimeout(debounceTimer); debounceTimer = null; }
  function controls() {
    if (saveButton) saveButton.disabled = blocked || submitting || submitWaiting || Boolean(activeRequest);
    submitButtons.forEach((button) => { button.disabled = blocked || submitting || submitWaiting; });
  }
  function block(message) {
    blocked = true;
    dirty = true;
    submitWaiting = false;
    submitPending = false;
    clearDebounce();
    epoch += 1;
    activeRequest?.controller.abort();
    activeRequest = null;
    if (reloadButton) reloadButton.hidden = false;
    setStatus(message, 'conflict');
    controls();
    updateWarning();
  }
  function readAnswers() {
    const answers = {};
    form.querySelectorAll('input[type="radio"]:checked').forEach((input) => {
      const match = input.name.match(/^question_(\d+)$/);
      if (match) answers[match[1]] = input.value;
    });
    return answers;
  }
  function scheduleSave() {
    clearDebounce();
    if (!blocked && !submitting && !submitWaiting && dirty) debounceTimer = window.setTimeout(() => saveLatest(), 500);
  }
  function formatSavedAt(value) {
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? '' : ` · ${new Intl.DateTimeFormat('vi-VN', {hour: '2-digit', minute: '2-digit'}).format(date)}`;
  }
  function saveLatest() {
    clearDebounce();
    if (blocked || submitting || submitWaiting) return Promise.resolve(false);
    if (activeRequest) return activeRequest.promise;
    if (!dirty) return Promise.resolve(true);
    if (!form.dataset.draftUrl || !csrfToken) {
      setStatus('Không lưu được bản nháp. Lựa chọn hiện chỉ còn trên trang này; hãy thử lưu lại.', 'error');
      updateWarning();
      return Promise.resolve(false);
    }
    const savedVersion = version;
    const savedRevision = revision;
    const requestEpoch = epoch;
    const controller = new AbortController();
    const request = {controller, promise: null};
    activeRequest = request;
    controls();
    updateWarning();
    setStatus('Đang lưu bản nháp…', 'saving');
    request.promise = (async () => {
      let succeeded = false;
      let timeout;
      try {
        const result = await Promise.race([
          new Promise((_, reject) => { controller.signal.addEventListener('abort', () => reject(new Error('Đã hủy lưu.')), {once: true}); }),
          (async () => {
            const response = await fetch(form.dataset.draftUrl, {
              method: 'POST', credentials: 'same-origin', signal: controller.signal,
              headers: {'Accept': 'application/json', 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
              body: JSON.stringify({answers: readAnswers(), draft_revision: savedRevision}),
            });
            let body = {};
            try { body = await response.json(); } catch (_) { /* validate below */ }
            return {response, body};
          })(),
          new Promise((_, reject) => {
            timeout = window.setTimeout(() => {
              controller.abort();
              reject(new Error('Quá thời gian chờ lưu.'));
            }, 15000);
          }),
        ]);
        if (requestEpoch !== epoch || blocked || submitting) return false;
        const {response, body} = result;
        if (response.status === 409) {
          block(`${body.error || body.message || 'Bản nháp đã thay đổi hoặc lượt làm đã đóng.'} Lựa chọn trên trang vẫn được giữ. Hãy tải lại bản đã lưu trước khi tiếp tục.`);
          return false;
        }
        if (response.redirected || !response.ok || body.error || !Number.isInteger(body.saved_count)
          || typeof body.last_saved_at !== 'string' || !Number.isInteger(body.draft_revision)
          || body.draft_revision !== savedRevision + 1) throw new Error('Không nhận được xác nhận lưu hợp lệ.');
        revision = body.draft_revision;
        if (revisionInput) revisionInput.value = String(revision);
        form.dataset.draftRevision = String(revision);
        succeeded = true;
        dirty = savedVersion !== version;
        setStatus(dirty ? 'Đang chờ lưu lựa chọn mới nhất…' : `Đã lưu bản nháp (${body.saved_count} câu)${formatSavedAt(body.last_saved_at)}.`, dirty ? 'pending' : 'saved');
      } catch (_) {
        if (requestEpoch === epoch && !blocked && !submitting) {
          dirty = true;
          setStatus('Không lưu được bản nháp. Lựa chọn hiện chỉ còn trên trang này; hãy thử lưu lại. Nếu bản đã lưu thay đổi, bạn sẽ cần tải lại.', 'error');
        }
      } finally {
        window.clearTimeout(timeout);
        if (activeRequest === request) activeRequest = null;
        if (requestEpoch === epoch) {
          controls();
          updateWarning();
          if (succeeded && dirty && !submitWaiting) scheduleSave();
        }
      }
      return succeeded;
    })();
    return request.promise;
  }

  form.addEventListener('change', (event) => {
    if (!event.target.matches('input[type="radio"]')) return;
    version += 1;
    dirty = true;
    updateProgress();
    updateWarning();
    if (!blocked && !submitting && !submitWaiting) {
      setStatus('Đang chờ lưu lựa chọn…', 'pending');
      scheduleSave();
    }
  });
  saveButton?.addEventListener('click', () => {
    if (blocked || submitting || submitWaiting) return;
    if (!dirty && !activeRequest) setStatus('Không có lựa chọn mới cần lưu.', 'saved');
    else saveLatest();
  });
  reloadButton?.addEventListener('click', () => {
    if (!window.confirm('Tải lại bản đã lưu? Các lựa chọn chưa lưu trên trang này sẽ bị thay thế.')) return;
    submitting = true;
    updateWarning();
    window.location.reload();
  });

  form.addEventListener('submit', (event) => {
    if (blocked || submitting || submitPending || submitWaiting) { event.preventDefault(); return; }
    clearDebounce();
    if (activeRequest) {
      event.preventDefault();
      submitWaiting = true;
      controls();
      const submitter = event.submitter;
      setStatus('Đang chờ xác nhận bản nháp trước khi nộp…', 'saving');
      activeRequest.promise.then((saved) => {
        if (blocked || submitting || !submitWaiting) return;
        submitWaiting = false;
        controls();
        if (saved) form.requestSubmit(submitter || undefined);
        else setStatus('Chưa nộp bài vì chưa xác nhận được bản nháp. Lựa chọn vẫn được giữ; hãy lưu lại hoặc thử nộp lại.', 'error');
      });
      return;
    }
    const unanswered = Math.max(0, total - form.querySelectorAll('input[type="radio"]:checked').length);
    if (form.matches('.practice-form') && unanswered > 0
      && !window.confirm(`Bạn còn ${unanswered} câu chưa trả lời. Vẫn nộp bài?`)) {
      event.preventDefault();
      scheduleSave();
      updateWarning();
      return;
    }
    submitPending = true;
    // Native submit includes current visible choices, even if not autosaved yet.
    // Suppress leave warnings before its default navigation. Check cancellation
    // in a new task: native events can run microtasks between bubbling listeners.
    submitting = true;
    controls();
    updateWarning();
    window.setTimeout(() => {
      submitPending = false;
      if (!event.defaultPrevented || blocked) return;
      submitting = false;
      controls();
      scheduleSave();
      updateWarning();
    }, 0);
  });
  document.querySelector('[data-abandon-attempt]')?.addEventListener('submit', (event) => {
    if (!window.confirm('Dừng lượt làm này và xóa toàn bộ câu trả lời đã lưu?')) { event.preventDefault(); return; }
    submitting = true;
    dirty = false;
    submitWaiting = false;
    clearDebounce();
    epoch += 1;
    activeRequest?.controller.abort();
    activeRequest = null;
    controls();
    updateWarning();
  });
  window.addEventListener('pageshow', (event) => {
    if (event.persisted) {
      submitting = false;
      block('Trang được khôi phục có thể chứa bản nháp cũ. Lựa chọn trên trang vẫn được giữ; hãy tải lại bản đã lưu trước khi tiếp tục.');
    }
  });
  if (saveButton) saveButton.hidden = false;
  updateProgress();
  if (form.dataset.draftConflict === 'true' || !Number.isInteger(revision) || revision < 0) {
    block('Bản nháp trên trang không còn đồng bộ. Lựa chọn vẫn được giữ; hãy tải lại bản đã lưu trước khi tiếp tục.');
  } else { controls(); updateWarning(); if (dirty) scheduleSave(); }
})();
