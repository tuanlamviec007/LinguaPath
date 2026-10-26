/* Human annotations only: source evidence, hashes and publication stay untouched. */
(function (host, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else {
    host.LinguaPathReviewEditor = api;
    const boot = () => {
      const root = document.getElementById('review-editor-root');
      const data = document.getElementById('review-packet-data');
      if (root && data) {
        try { api.attach(root, JSON.parse(data.textContent), document, host); }
        catch (_) { root.textContent = 'Chưa thể mở phiếu. Hãy kiểm tra lại tệp và xuất một phiếu mới.'; }
      }
    };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();
  }
})(typeof window === 'object' ? window : globalThis, function () {
  'use strict';
  const CHECKS = Object.freeze({
    sense_and_context: 'Nghĩa và ngữ cảnh', answer_key: 'Khóa đáp án',
    distractors_and_explanations: 'Phương án nhiễu và lời giải', cefr_reference: 'Mức CEFR tham khảo',
    source_and_rights: 'Nguồn và quyền sử dụng', audio_and_accessibility: 'Âm thanh và khả năng tiếp cận',
  });
  const CONCLUSIONS = Object.freeze({pass: 'Đồng ý', needs_changes: 'Cần sửa', insufficient_info: 'Chưa đủ thông tin'});
  const RESULTS = Object.freeze({pass: 'Đạt', fail: 'Cần sửa', not_applicable: 'Không áp dụng — cần lý do'});
  const REVIEW_FIELDS = ['reviewer_name', 'qualifications', 'reviewed_at', 'conclusion', 'notes'];
  const IDENTITY_FIELDS = ['reviewer_name', 'qualifications', 'reviewed_at'];
  const TEXT_LIMITS = {reviewer_name: 200, qualifications: 2000, notes: 4000};
  const clone = value => JSON.parse(JSON.stringify(value));
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const present = value => typeof value === 'string' && value.trim().length > 0;
  function validDate(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value || '')) return false;
    const date = new Date(`${value}T00:00:00Z`);
    return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
  }
  function validReviewedAt(value) {
    if (validDate(value)) return true;
    return typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)
      && validDate(value.slice(0, 10)) && !Number.isNaN(Date.parse(value));
  }
  function createState(packet) {
    if (!packet || !['linguapath-content-review-v1', 'linguapath-content-review-v2'].includes(packet.schema_version) || !Array.isArray(packet.contents) || !packet.human_review) throw new Error('invalid-packet');
    const pending = [{value: packet, depth: 0}];
    const seen = new Set();
    while (pending.length) {
      const {value, depth} = pending.pop();
      if (depth > 16) throw new Error('invalid-source-nesting');
      if (typeof value === 'number' && !Number.isSafeInteger(value)) throw new Error('unsafe-source-number');
      if (value && typeof value === 'object') {
        if (seen.has(value)) throw new Error('invalid-source-cycle');
        seen.add(value);
        Object.values(value).forEach(child => pending.push({value: child, depth: depth + 1}));
      }
    }
    const state = {packet: clone(packet), items: [], dirty: false};
    state.packet.contents.forEach((content, contentIndex) => {
      ['flashcards', 'questions'].forEach(kind => {
        if (!Array.isArray(content[kind])) throw new Error('invalid-items');
        content[kind].forEach((item, index) => {
          if (!item.human_review || !item.checklist || !Object.keys(CHECKS).every(key => own(item.checklist, key))) throw new Error('invalid-annotations');
          state.items.push({contentIndex, kind, index});
        });
      });
    });
    return state;
  }
  function itemAt(state, index) {
    if (!Number.isInteger(index) || index < 0 || index >= state.items.length) throw new Error('invalid-item');
    const location = state.items[index];
    return state.packet.contents[location.contentIndex][location.kind][location.index];
  }
  function reviewAt(state, index) { return index === null ? state.packet.human_review : itemAt(state, index).human_review; }
  function updateReview(state, index, key, value) {
    if (!REVIEW_FIELDS.includes(key)) throw new Error('invalid-review-field');
    if (key === 'conclusion') {
      if (value !== null && !own(CONCLUSIONS, value)) throw new Error('invalid-conclusion');
    } else if (key === 'reviewed_at') {
      if (value !== null && (typeof value !== 'string' || !validDate(value))) throw new Error('invalid-date');
    } else if (typeof value !== 'string' || value.length > TEXT_LIMITS[key]) throw new Error('invalid-review-text');
    reviewAt(state, index)[key] = value;
    state.dirty = true;
  }
  function updateChecklist(state, index, key, field, value) {
    if (!own(CHECKS, key) || !['result', 'notes'].includes(field)) throw new Error('invalid-checklist-field');
    if (field === 'result' && value !== null && !own(RESULTS, value)) throw new Error('invalid-result');
    if (field === 'notes' && (typeof value !== 'string' || value.length > 4000)) throw new Error('invalid-notes');
    itemAt(state, index).checklist[key][field] = value;
    state.dirty = true;
  }
  function assessed(item) {
    return item.human_review.conclusion !== null || present(item.human_review.notes) || Object.keys(CHECKS).some(key => item.checklist[key].result !== null || present(item.checklist[key].notes));
  }
  function copyReviewer(state, index) {
    const source = state.packet.human_review;
    const targets = index === 'assessed' ? state.items.map((_, at) => at).filter(at => assessed(itemAt(state, at))) : [index];
    targets.forEach(at => {
      const target = itemAt(state, at).human_review;
      IDENTITY_FIELDS.forEach(key => { target[key] = source[key]; });
    });
    if (targets.length) state.dirty = true;
    return targets.length;
  }
  function complete(item) {
    const review = item.human_review;
    return present(review.reviewer_name) && present(review.qualifications) && validReviewedAt(review.reviewed_at)
      && own(CONCLUSIONS, review.conclusion)
      && (review.conclusion === 'pass' || present(review.notes))
      && (review.conclusion !== 'pass' || !Object.keys(CHECKS).some(key => item.checklist[key].result === 'fail'))
      && Object.keys(CHECKS).every(key => own(RESULTS, item.checklist[key].result)
        && (item.checklist[key].result === 'pass' || present(item.checklist[key].notes)));
  }
  function summary(state) {
    const counts = {total: state.items.length, complete: 0, pending: 0, pass: 0, needs_changes: 0, insufficient_info: 0};
    state.items.forEach((_, index) => {
      const item = itemAt(state, index);
      if (complete(item)) counts.complete += 1; else counts.pending += 1;
      if (own(CONCLUSIONS, item.human_review.conclusion)) counts[item.human_review.conclusion] += 1;
    });
    return counts;
  }
  function conflicts(state) {
    let items = 0;
    let nonpass = false;
    state.items.forEach((_, index) => {
      const item = itemAt(state, index);
      if (item.human_review.conclusion === 'pass' && Object.keys(CHECKS).some(key => item.checklist[key].result === 'fail')) items += 1;
      if (['needs_changes', 'insufficient_info'].includes(item.human_review.conclusion)) nonpass = true;
    });
    return {items, overall: state.packet.human_review.conclusion === 'pass' && nonpass};
  }
  function attach(root, packet, doc, win) {
    const state = createState(packet);
    let active = 0;
    const el = (tag, text, className) => {
      const node = doc.createElement(tag);
      if (text !== undefined && text !== null) node.textContent = String(text);
      if (className) node.className = className;
      return node;
    };
    const append = (parent, ...children) => { children.forEach(child => parent.appendChild(child)); return parent; };
    const button = (text, action, extraClass) => {
      const node = el('button', text, extraClass); node.type = 'button'; node.addEventListener('click', action); return node;
    };
    const notice = el('p', 'Thay đổi chỉ nằm trong phiên này. Tải phiếu để giữ nhận xét; trang không tự lưu hoặc phê duyệt học liệu.', 'review-editor-notice');
    const progress = el('p', '', 'review-editor-progress'); progress.setAttribute('role', 'status'); progress.setAttribute('aria-live', 'polite');
    const conflict = el('p', '', 'review-editor-conflict'); conflict.setAttribute('role', 'alert'); conflict.hidden = true;
    const status = el('p', '', 'review-editor-status'); status.setAttribute('role', 'status');
    const overall = el('section', null, 'review-editor-panel'); append(overall, el('h2', 'Thông tin người duyệt'));
    const help = el('p', 'Nhập thông tin thực của bạn. Nút sao chép bên dưới ghi thông tin này vào mục đã chọn; nhận xét và kết luận của từng mục được giữ nguyên.');
    overall.appendChild(help);
    const formField = (parent, label, id, tag, value, onChange, choices) => {
      const wrapper = el('div', null, 'review-editor-field');
      const caption = el('label', label); caption.htmlFor = id;
      const field = el(tag); field.id = id;
      if (tag === 'select') {
        append(field, el('option', 'Chưa chọn')); field.firstChild.value = '';
        Object.entries(choices).forEach(([key, text]) => { const option = el('option', text); option.value = key; field.appendChild(option); });
      } else if (tag === 'textarea') { field.rows = 3; field.maxLength = 4000; }
      else { field.type = id.includes('reviewed_at') ? 'date' : 'text'; field.maxLength = id.includes('reviewer_name') ? 200 : 2000; }
      field.value = field.type === 'date' && typeof value === 'string' ? value.slice(0, 10) : (value || '');
      field.addEventListener(tag === 'select' || field.type === 'date' ? 'change' : 'input', () => {
        try { onChange(field.value || (tag === 'select' || field.type === 'date' ? null : '')); refresh(); status.textContent = ''; }
        catch (_) { status.textContent = 'Giá trị chưa hợp lệ. Hãy kiểm tra lại ngày và giới hạn ghi chú.'; }
      });
      append(wrapper, caption, field); parent.appendChild(wrapper); return field;
    };
    const topFields = el('div', null, 'review-editor-grid');
    [['reviewer_name', 'Họ tên người duyệt'], ['qualifications', 'Chuyên môn / vai trò'], ['reviewed_at', 'Ngày rà soát']].forEach(([key, title]) => {
      formField(topFields, title, `review-top-${key}`, 'input', state.packet.human_review[key], value => updateReview(state, null, key, value));
    });
    overall.appendChild(topFields);
    formField(overall, 'Kết luận chung (tùy chọn)', 'review-top-conclusion', 'select', state.packet.human_review.conclusion, value => updateReview(state, null, 'conclusion', value), CONCLUSIONS);
    formField(overall, 'Ghi chú chung', 'review-top-notes', 'textarea', state.packet.human_review.notes, value => updateReview(state, null, 'notes', value));
    const nav = el('section', null, 'review-editor-panel');
    append(nav, el('h2', 'Rà soát từng mục'), el('p', 'Mỗi mục cần checklist và kết luận riêng. “Đủ trường” chỉ mô tả việc điền phiếu; không xác minh chuyên môn hay chất lượng.'));
    const navigation = el('div', null, 'review-editor-navigation');
    const selectLabel = el('label', 'Chọn mục để rà soát'); selectLabel.htmlFor = 'review-item-select';
    const select = el('select'); select.id = 'review-item-select';
    state.items.forEach((location, index) => {
      const content = state.packet.contents[location.contentIndex]; const item = itemAt(state, index);
      const title = item.term || item.prompt || '';
      const option = el('option', `${index + 1}. ${location.kind === 'flashcards' ? 'Thẻ' : 'Câu'} #${item.id} · ${String(title).slice(0, 75)} · ${content.content.title}`);
      option.value = String(index); select.appendChild(option);
    });
    const previous = button('← Mục trước', () => navigate(active - 1));
    const next = button('Mục sau →', () => navigate(active + 1));
    append(navigation, selectLabel, select, previous, next); nav.appendChild(navigation);
    const viewer = el('div', null, 'review-editor-viewer'); nav.appendChild(viewer);
    const actions = el('div', null, 'review-editor-actions');
    const download = button('Tải phiếu đã điền · JSON', () => {
      const blob = new win.Blob([JSON.stringify(state.packet, null, 2)], {type: 'application/json;charset=utf-8'});
      const url = win.URL.createObjectURL(blob); const link = el('a');
      link.href = url; link.download = 'linguapath-human-review-annotated.json';
      doc.body.appendChild(link); link.click(); link.remove();
      win.setTimeout(() => win.URL.revokeObjectURL(url), 30000);
      state.dirty = false; status.textContent = 'Đã tạo tệp tải xuống. Kiểm tra tệp đã lưu trước khi đóng trang; tải phiếu không phê duyệt học liệu.';
    });
    actions.appendChild(download);
    append(root, notice, progress, conflict, overall, nav, actions, status);
    function refresh() {
      const count = summary(state);
      progress.textContent = `${count.complete}/${count.total} mục đủ trường · ${count.pending} mục còn thiếu · ${count.needs_changes} cần sửa · ${count.insufficient_info} chưa đủ thông tin`;
      const mismatches = conflicts(state);
      conflict.hidden = mismatches.items === 0 && !mismatches.overall;
      conflict.textContent = [mismatches.items ? `${mismatches.items} mục có kết luận “Đồng ý” nhưng checklist còn “Cần sửa”. Hãy đối chiếu lại.` : '', mismatches.overall ? 'Kết luận chung “Đồng ý” đang mâu thuẫn với mục cần sửa hoặc chưa đủ thông tin.' : ''].filter(Boolean).join(' ');
      previous.disabled = active === 0; next.disabled = active >= state.items.length - 1;
    }
    function sourceField(parent, title, value) {
      if (value === '' || value === null || value === undefined) return;
      const block = el('div', null, 'review-editor-evidence'); append(block, el('h4', title), el('p', value)); parent.appendChild(block);
    }
    function renderItem() {
      viewer.replaceChildren();
      if (!state.items.length) { viewer.appendChild(el('p', 'Phiếu chưa có mục để rà soát.')); return; }
      const location = state.items[active]; const content = state.packet.contents[location.contentIndex]; const item = itemAt(state, active);
      const source = el('section', null, 'review-editor-source');
      append(source, el('h3', `${location.kind === 'flashcards' ? 'Flashcard' : 'Câu hỏi'} #${item.id}`), el('p', content.content.title, 'review-editor-parent'));
      const scope = content.coverage;
      if (scope) append(source, el('p', `Mẫu của bộ: ${scope.flashcards.exported}/${scope.flashcards.total} thẻ; ${scope.questions.exported}/${scope.questions.total} câu. Các mục ngoài mẫu chưa được rà soát.`, 'review-editor-muted'));
      sourceField(source, 'Mô tả bộ học liệu', content.content.description);
      sourceField(source, 'Metadata tham khảo của bộ', `${content.content.exam_type || 'Chưa ghi kỳ thi'} · ${content.content.skill || 'Chưa ghi kỹ năng'} · ${content.content.cefr_level || 'Chưa ghi mức'} · ${content.content.question_type || 'Chưa ghi dạng câu'}`);
      sourceField(source, 'Phiên bản toàn bộ nguồn', content.content_hash);
      sourceField(source, 'Phiên bản mục', item.version_hash);
      if (location.kind === 'flashcards' && typeof item.is_available === 'boolean') {
        sourceField(source, 'Trạng thái sử dụng thẻ', item.is_available ? 'Có thể sử dụng nếu bộ học liệu khả dụng' : 'Đang tạm giữ, chưa dùng trong phiên học mới');
        sourceField(source, 'Ghi chú tạm giữ', item.availability_note);
      }
      const labels = location.kind === 'flashcards' ? {
        term: 'Từ / cụm từ', meaning_vi: 'Nghĩa tiếng Việt', part_of_speech: 'Từ loại', cefr_level: 'Mức tham khảo', topic: 'Chủ điểm',
        example_en: 'Ví dụ tiếng Anh', example_vi: 'Ví dụ tiếng Việt', pronunciation: 'Phiên âm', audio_url: 'Đường dẫn âm thanh',
      } : {prompt: 'Đề câu hỏi', passage: 'Đoạn đọc', audio_script: 'Lời thoại', transcript: 'Bản chép lời', audio_url: 'Đường dẫn âm thanh', explanation: 'Lời giải', explanation_vi: 'Lời giải tiếng Việt'};
      Object.entries(labels).forEach(([key, label]) => sourceField(source, label, item[key]));
      if (location.kind === 'questions') {
        const options = el('div', null, 'review-editor-options'); options.appendChild(el('h4', 'Lựa chọn và khóa chấm của nguồn'));
        (item.options || []).forEach(option => {
          const row = el('article', null, option.is_correct ? 'review-editor-option is-correct' : 'review-editor-option');
          append(row, el('h5', `${option.label}. ${option.text}${option.is_correct ? ' · Khóa đúng theo nguồn' : ''}`));
          sourceField(row, 'Giải thích lựa chọn', option.explanation_vi); options.appendChild(row);
        }); source.appendChild(options);
      }
      ['source_name', 'source_url', 'rights_note'].forEach((key, index) => {
        const names = ['Nguồn', 'Đường dẫn nguồn', 'Ghi chú quyền sử dụng'];
        sourceField(source, `${names[index]} · bộ học liệu`, content.content[key] || 'Chưa ghi trong nguồn');
        if (location.kind === 'flashcards') sourceField(source, `${names[index]} · flashcard`, item[key] || 'Chưa ghi trong nguồn');
      });
      append(source, el('p', 'Đường dẫn chỉ hiển thị để đối chiếu. Không tự tải âm thanh; hãy nghe nguồn thực và ghi nhận xét khi kiểm tra.', 'review-editor-muted'));
      const annotations = el('section', null, 'review-editor-annotations');
      annotations.appendChild(el('h3', 'Nhận xét của người duyệt'));
      const copyActions = el('div', null, 'review-editor-actions');
      append(copyActions, button('Sao chép người duyệt vào mục này', () => {
        copyReviewer(state, active); renderItem(); refresh(); status.textContent = 'Đã sao chép tên, chuyên môn và ngày vào mục hiện tại.';
      }), button('Sao chép vào mọi mục đã đánh giá', () => {
        const copied = copyReviewer(state, 'assessed'); renderItem(); refresh(); status.textContent = `Đã sao chép tên, chuyên môn và ngày vào ${copied} mục có nhận xét hoặc kết luận.`;
      }, 'review-editor-secondary'));
      append(annotations, el('p', 'Sao chép sẽ thay tên, chuyên môn và ngày đang có ở các mục được chọn. Kết luận và ghi chú không đổi.'), copyActions);
      IDENTITY_FIELDS.forEach((key, index) => formField(annotations, ['Họ tên tại mục này', 'Chuyên môn / vai trò tại mục này', 'Ngày rà soát mục này'][index], `review-item-${key}`, 'input', item.human_review[key], value => updateReview(state, active, key, value)));
      Object.entries(CHECKS).forEach(([key, title]) => {
        const check = el('fieldset', null, 'review-editor-check'); check.appendChild(el('legend', title));
        formField(check, 'Kết quả kiểm tra', `review-check-${key}-result`, 'select', item.checklist[key].result, value => updateChecklist(state, active, key, 'result', value), RESULTS);
        formField(check, 'Bằng chứng / lý do (bắt buộc nếu cần sửa hoặc không áp dụng)', `review-check-${key}-notes`, 'textarea', item.checklist[key].notes, value => updateChecklist(state, active, key, 'notes', value));
        annotations.appendChild(check);
      });
      formField(annotations, 'Kết luận cho mục này', 'review-item-conclusion', 'select', item.human_review.conclusion, value => updateReview(state, active, 'conclusion', value), CONCLUSIONS);
      formField(annotations, 'Nhận xét / sửa đề xuất (bắt buộc nếu chưa đồng ý)', 'review-item-notes', 'textarea', item.human_review.notes, value => updateReview(state, active, 'notes', value));
      append(viewer, source, annotations);
    }
    function navigate(index) {
      if (!Number.isInteger(index) || index < 0 || index >= state.items.length) return;
      active = index; select.value = String(index); renderItem(); refresh();
    }
    select.addEventListener('change', () => navigate(Number(select.value)));
    win.addEventListener('beforeunload', event => { if (state.dirty) { event.preventDefault(); event.returnValue = ''; } });
    renderItem(); refresh();
    return {state, navigate};
  }
  return {CHECKS, CONCLUSIONS, RESULTS, createState, itemAt, updateReview, updateChecklist, copyReviewer, complete, summary, conflicts, attach};
});
