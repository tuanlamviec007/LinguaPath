(() => {
  document.querySelectorAll('.mobile-nav').forEach((details) => {
    const summary = details.querySelector('summary');
    details.querySelectorAll('.mobile-nav__links a').forEach((link) => {
      link.addEventListener('click', () => { details.open = false; });
    });
    details.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && details.open) {
        details.open = false;
        summary?.focus();
        event.preventDefault();
      }
    });
  });
})();
