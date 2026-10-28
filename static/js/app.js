let speechRun = 0;
let activeSpeech = null;

function setSpeechState(state) {
  if (!activeSpeech) return;
  const { button, stop, status } = activeSpeech;
  if (status) status.textContent = state;
  const playing = state.startsWith('Đang') || state.startsWith('Đang chuẩn bị');
  if (button) button.disabled = playing;
  if (!playing && stop && document.activeElement === stop) button?.focus();
  if (stop) stop.hidden = !playing;
  if (!playing) activeSpeech = null;
}

function stopSpeech(message = 'Đã dừng phát.') {
  speechRun += 1;
  if ('speechSynthesis' in window) window.speechSynthesis.cancel();
  setSpeechState(message);
}

function loadVoices(synthesis) {
  const voices = synthesis.getVoices();
  if (voices.length) return Promise.resolve(voices);
  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      synthesis.removeEventListener('voiceschanged', finish);
      resolve(synthesis.getVoices());
    };
    const timer = setTimeout(finish, 1200);
    synthesis.addEventListener('voiceschanged', finish, { once: true });
  });
}

document.addEventListener('click', async (event) => {
  const flip = event.target.closest('[data-flip]');
  if (flip) {
    const card = flip.closest('[data-flashcard]');
    if (!card) return;
    const showBack = !card.classList.contains('is-flipped');
    const front = card.querySelector('.flash-front');
    const back = card.querySelector('.flash-back');
    card.classList.toggle('is-flipped', showBack);
    front?.setAttribute('aria-hidden', String(showBack));
    back?.setAttribute('aria-hidden', String(!showBack));
    if (front) front.inert = showBack;
    if (back) back.inert = !showBack;
    card.querySelectorAll('[data-flip]').forEach((control) => control.setAttribute('aria-expanded', String(showBack)));
    const focusTarget = showBack ? (back?.querySelector('[data-flashcard-meaning]') || back?.querySelector('[data-flip]')) : front?.querySelector('[data-flip]');
    focusTarget?.focus();
    return;
  }

  const stop = event.target.closest('[data-speech-stop]');
  if (stop) {
    stopSpeech();
    return;
  }

  const speak = event.target.closest('[data-speak]');
  if (speak) {
    if (!('speechSynthesis' in window) || !('SpeechSynthesisUtterance' in window)) {
      const status = speak.closest('.listening-player')?.querySelector('[data-speech-status]');
      if (status) status.textContent = 'Thiết bị không hỗ trợ phát giọng đọc. Mở transcript bên dưới để tiếp tục.';
      else window.alert('Trình duyệt này chưa hỗ trợ giọng đọc.');
      return;
    }

    stopSpeech('Đã dừng phát.');
    document.querySelectorAll('audio').forEach((audio) => audio.pause());
    const synthesis = window.speechSynthesis;
    const status = speak.closest('.listening-player')?.querySelector('[data-speech-status]');
    const stopButton = speak.closest('.listening-player')?.querySelector('[data-speech-stop]');
    const run = ++speechRun;
    activeSpeech = { button: speak, stop: stopButton, status };
    setSpeechState('Đang chuẩn bị giọng đọc…');

    const voices = await loadVoices(synthesis);
    if (run !== speechRun) return;
    const englishVoices = voices.filter((voice) => /^en([_-]|$)/i.test(voice.lang));
    const selectedRate = Number(speak.closest('.listening-player')?.querySelector('[data-speech-rate]')?.value || '1');
    const speechRate = [0.75, 1, 1.25].includes(selectedRate) ? selectedRate : 1;
    const turns = speak.dataset.speak.split(/(?=[AB]:\s)/).map((turn) => {
      const match = turn.match(/^([AB]):\s*([\s\S]*)$/);
      return match ? { speaker: match[1], text: match[2].trim() } : { speaker: 'A', text: turn.trim() };
    }).filter((turn) => turn.text);
    let turnIndex = 0;

    const playTurn = () => {
      if (run !== speechRun) return;
      if (turnIndex >= turns.length) {
        setSpeechState('Đã phát xong.');
        return;
      }
      const turn = turns[turnIndex++];
      const utterance = new SpeechSynthesisUtterance(turn.text);
      utterance.lang = 'en-US';
      utterance.rate = speechRate;
      utterance.volume = 1;
      utterance.pitch = turn.speaker === 'B' ? 1.04 : 0.96;
      if (englishVoices.length) {
        const voiceIndex = turn.speaker === 'B' && englishVoices.length > 1 ? 1 : 0;
        utterance.voice = englishVoices[voiceIndex];
      }
      utterance.onstart = () => { if (run === speechRun) setSpeechState('Đang phát bài nghe…'); };
      utterance.onend = playTurn;
      utterance.onerror = (error) => {
        if (run !== speechRun) return;
        setSpeechState(`Không phát được giọng đọc (${error.error || 'lỗi thiết bị'}). Mở transcript bên dưới để tiếp tục.`);
      };
      try {
        synthesis.speak(utterance);
        synthesis.resume();
      } catch (error) {
        setSpeechState('Không phát được giọng đọc trên thiết bị. Mở transcript bên dưới để tiếp tục.');
      }
    };
    playTurn();
    return;
  }
});

document.addEventListener('submit', (event) => {
  const form = event.target;
  if (form.matches('.practice-form') && !form.matches('[data-practice-draft]') && !event.defaultPrevented) {
    const unanswered = [...form.querySelectorAll('[data-question]')].filter((question) => !question.querySelector('input:checked')).length;
    if (unanswered > 0 && !window.confirm(`Bạn còn ${unanswered} câu chưa trả lời. Vẫn nộp bài?`)) event.preventDefault();
  }
});

document.addEventListener('error', (event) => {
  const audio = event.target;
  if (!(audio instanceof HTMLAudioElement)) return;
  audio.dataset.failed = 'true';
  const status = audio.parentElement?.querySelector('[data-audio-error]');
  if (status) status.hidden = false;
}, true);

// A learner should hear only one source at a time, including native controls.
document.addEventListener('play', (event) => {
  if (!(event.target instanceof HTMLAudioElement)) return;
  stopSpeech('Đã dừng giọng đọc để phát tệp âm thanh.');
  document.querySelectorAll('audio').forEach((audio) => {
    if (audio !== event.target) audio.pause();
  });
}, true);
window.addEventListener('pagehide', () => stopSpeech());
