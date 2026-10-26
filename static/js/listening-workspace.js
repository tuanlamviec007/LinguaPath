/* Native audio remains available if these study controls cannot run. */
(() => {
  document.querySelectorAll('[data-listening-player]').forEach((player) => {
    const audio = player.querySelector('audio');
    if (!audio) return;
    const replay = player.querySelector('[data-audio-replay]');
    const back = player.querySelector('[data-audio-back]');
    const rate = player.querySelector('[data-audio-rate]');
    const status = player.querySelector('[data-audio-status]');
    const error = player.querySelector('[data-audio-error]');
    const say = (message) => { if (status) status.textContent = message; };
    const ready = () => {
      const canSeek = Number.isFinite(audio.duration) && audio.duration > 0;
      if (replay) replay.disabled = !canSeek;
      if (back) back.disabled = !canSeek;
      if (error) error.hidden = true;
      say('Âm thanh đã sẵn sàng. Bạn có thể tua lại hoặc nghe nhiều lần.');
    };
    audio.addEventListener('loadedmetadata', ready);
    audio.addEventListener('canplay', ready);
    const failed = () => {
      if (error) error.hidden = false;
      if (replay) replay.disabled = true;
      if (back) back.disabled = true;
      say('Chưa phát được âm thanh. Các lựa chọn trả lời vẫn được giữ.');
    };
    audio.addEventListener('error', failed);
    if (audio.error) failed();
    else if (audio.readyState >= 1) ready();
    audio.addEventListener('play', () => say('Đang phát bài nghe.'));
    audio.addEventListener('pause', () => say(audio.ended ? 'Đã nghe hết đoạn. Bạn có thể phát lại.' : 'Đã tạm dừng bài nghe.'));
    audio.addEventListener('ended', () => say('Đã nghe hết đoạn. Bạn có thể phát lại.'));
    back?.addEventListener('click', () => {
      if (!Number.isFinite(audio.duration) || audio.duration <= 0) return;
      audio.currentTime = Math.max(0, audio.currentTime - 10);
      say('Đã tua lại tối đa 10 giây.');
    });
    replay?.addEventListener('click', async () => {
      if (!Number.isFinite(audio.duration) || audio.duration <= 0) return;
      audio.currentTime = 0;
      try { await audio.play(); }
      catch { say('Trình duyệt chưa cho phép phát. Hãy bấm nút phát trên thanh âm thanh.'); }
    });
    rate?.addEventListener('change', () => {
      const value = Number(rate.value);
      if (![0.75, 1, 1.25].includes(value)) return;
      audio.playbackRate = value;
      say(`Tốc độ phát ${String(value).replace('.', ',')}×. Đây là công cụ hỗ trợ luyện nghe.`);
    });
  });
  window.addEventListener('pagehide', () => {
    document.querySelectorAll('audio').forEach((audio) => audio.pause());
  });
})();
