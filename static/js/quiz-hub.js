/* Keep source links usable as normal GET navigation, including open-in-new-tab. */
(() => {
  const form = document.querySelector('[data-quiz-builder]');
  if (!form) return;
  const links = [...form.querySelectorAll('[data-quiz-source]')];
  const sources = new Set(['all', 'saved', 'weak', 'due']);
  const hubPath = form.dataset.quizHubUrl || '';
  // Never construct a cross-origin, protocol-relative or executable destination.
  if (!hubPath.startsWith('/') || hubPath.startsWith('//') || hubPath.includes('\\')) return;
  let hub;
  try { hub = new URL(hubPath, window.location.origin); } catch (_) { return; }
  if (hub.origin !== window.location.origin || !['https:', 'http:'].includes(hub.protocol)) return;

  function syncSourceLinks() {
    const mode = form.querySelector('input[name="mode"]:checked')?.value;
    const count = form.querySelector('input[name="count"]:checked')?.value;
    const level = form.querySelector('[name="level"]')?.value || '';
    const topic = form.querySelector('[name="topic"]')?.value || '';
    for (const link of links) {
      if (!sources.has(link.dataset.quizSource)) continue;
      const query = new URLSearchParams({
        source: link.dataset.quizSource,
        mode: link.dataset.quizSource === 'due' || mode === 'recall' ? 'recall' : 'meaning',
        count: ['5', '10', '15'].includes(count) ? count : '10',
      });
      if (level) query.set('level', level);
      if (topic) query.set('topic', topic);
      // Relative paths prevent an href supplied by markup from controlling origin.
      link.setAttribute('href', `${hub.pathname}?${query.toString()}`);
    }
  }
  form.addEventListener('input', syncSourceLinks);
  form.addEventListener('change', syncSourceLinks);
  window.addEventListener('pageshow', syncSourceLinks);
  syncSourceLinks();
})();
