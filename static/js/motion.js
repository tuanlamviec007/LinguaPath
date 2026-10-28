/* Decorative only. No scores, learning state or network requests. */
(() => {
  'use strict';
  const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
  const root = document.documentElement;
  const toggles = [...document.querySelectorAll('[data-motion-toggle]')];
  const celebrateButtons = [...document.querySelectorAll('[data-celebrate]')];
  let paused = false;
  try { paused = window.localStorage.getItem('linguapath.motion.paused') === 'true'; } catch (_) {}
  let particles = [];
  let cleanupTimer;
  let lastCelebration = -Infinity;
  const stopped = () => paused || preference.matches;
  function clearCelebration() {
    window.clearTimeout(cleanupTimer);
    particles.forEach((particle) => particle.remove());
    particles = [];
  }
  function sync() {
    root.classList.toggle('motion-paused', stopped());
    if (stopped()) clearCelebration();
    toggles.forEach((button) => {
      button.hidden = false;
      button.disabled = preference.matches;
      button.setAttribute('aria-pressed', String(stopped()));
      button.textContent = preference.matches ? 'Đã giảm chuyển động theo thiết bị' : paused ? 'Bật hiệu ứng' : 'Tắt hiệu ứng';
    });
    celebrateButtons.forEach((button) => { button.hidden = stopped(); });
  }
  toggles.forEach((button) => button.addEventListener('click', () => {
    paused = !paused;
    try { window.localStorage.setItem('linguapath.motion.paused', String(paused)); } catch (_) {}
    sync();
  }));
  preference.addEventListener('change', sync);
  window.addEventListener('storage', (event) => {
    if (event.key !== 'linguapath.motion.paused' && event.key !== null) return;
    paused = event.key === null ? false : event.newValue === 'true';
    sync();
  });
  function celebrate(target) {
    if (stopped() || document.hidden || !target?.getBoundingClientRect) return;
    const now = Date.now();
    if (now - lastCelebration < 1600) return;
    const bounds = target.getBoundingClientRect();
    if (bounds.bottom < 0 || bounds.top > window.innerHeight) return;
    lastCelebration = now;
    clearCelebration();
    const x = Math.max(24, Math.min(window.innerWidth - 24, bounds.left + bounds.width / 2));
    const y = Math.max(24, Math.min(window.innerHeight - 24, bounds.top + bounds.height / 3));
    for (let index = 0; index < 16; index++) {
      const particle = document.createElement('span');
      particle.className = 'learning-spark';
      particle.setAttribute('aria-hidden', 'true');
      particle.style.setProperty('--spark-x', `${x}px`);
      particle.style.setProperty('--spark-y', `${y}px`);
      particle.style.setProperty('--spark-dx', `${Math.cos(index * Math.PI / 8) * (55 + index * 4)}px`);
      particle.style.setProperty('--spark-dy', `${Math.sin(index * Math.PI / 8) * 95 - 45}px`);
      particle.style.setProperty('--spark-turn', `${index * 47}deg`);
      particle.style.setProperty('--spark-color', ['#6879e9', '#b296ed', '#e7b14c', '#74b9b2'][index % 4]);
      document.body.appendChild(particle);
      particles.push(particle);
    }
    cleanupTimer = window.setTimeout(clearCelebration, 1400);
  }
  document.addEventListener('linguapath:celebrate', (event) => celebrate(event.target));
  celebrateButtons.forEach((button) => button.addEventListener('click', () => celebrate(button)));
  document.addEventListener('visibilitychange', () => { if (document.hidden) clearCelebration(); });
  window.addEventListener('pagehide', clearCelebration);
  sync();
})();
