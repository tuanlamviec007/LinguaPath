const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'app.js'), 'utf8');

function setup() {
  const handlers = new Map();
  const audios = [];
  const document = {
    activeElement: null,
    addEventListener(type, handler) {
      const listeners = handlers.get(type) || [];
      listeners.push(handler);
      handlers.set(type, listeners);
    },
    querySelectorAll(selector) { return selector === 'audio' ? audios : []; },
  };
  class Element {
    constructor(matches = []) {
      this.matches = new Set(matches);
      this.disabled = false;
      this.hidden = false;
      this.dataset = {};
      this.textContent = '';
      this.nodes = {};
      this.focusCalls = 0;
    }
    closest(selector) {
      if (this.matches.has(selector)) return this;
      return selector === '.listening-player' ? this.player || null : null;
    }
    querySelector(selector) { return this.nodes[selector] || null; }
    focus() { this.focusCalls += 1; document.activeElement = this; }
  }
  class Audio extends Element {
    constructor() { super(); this.pauseCalls = 0; }
    pause() { this.pauseCalls += 1; }
  }
  class Utterance {
    constructor(text) { this.text = text; }
  }
  const synthesis = {
    utterances: [], cancelCalls: 0,
    getVoices() { return [{lang: 'en-US'}]; },
    cancel() { this.cancelCalls += 1; },
    speak(utterance) { this.utterances.push(utterance); utterance.onstart?.(); },
    resume() {},
  };
  const window = {
    speechSynthesis: synthesis,
    SpeechSynthesisUtterance: Utterance,
    addEventListener() {},
    alert() { throw new Error('Unexpected unsupported speech alert'); },
  };
  vm.runInContext(script, vm.createContext({
    document, window, HTMLAudioElement: Audio,
    SpeechSynthesisUtterance: Utterance, setTimeout, clearTimeout,
  }), {filename: 'app.js'});
  const player = new Element();
  const speak = new Element(['[data-speak]']);
  speak.dataset.speak = 'Please wait near gate five.';
  speak.player = player;
  const stop = new Element(['[data-speech-stop]']);
  stop.hidden = true;
  stop.player = player;
  const status = new Element();
  const rate = new Element();
  rate.value = '1';
  player.nodes = {
    '[data-speech-status]': status, '[data-speech-stop]': stop,
    '[data-speech-rate]': rate,
  };
  async function emit(type, target) {
    await Promise.all((handlers.get(type) || []).map(handler => handler({target})));
  }
  return {document, audios, Audio, Element, synthesis, speak, stop, status, emit};
}

test('stopping speech restores focus from the disappearing Stop control', async () => {
  const context = setup();
  await context.emit('click', context.speak);
  assert.equal(context.speak.disabled, true);
  assert.equal(context.stop.hidden, false);
  context.stop.focus();
  await context.emit('click', context.stop);
  assert.equal(context.stop.hidden, true);
  assert.equal(context.speak.disabled, false);
  assert.equal(context.document.activeElement, context.speak);
  assert.equal(context.speak.focusCalls, 1);
});

test('speech completion restores focus only when Stop currently holds it', async () => {
  const focused = setup();
  await focused.emit('click', focused.speak);
  focused.stop.focus();
  focused.synthesis.utterances[0].onend();
  assert.equal(focused.stop.hidden, true);
  assert.equal(focused.document.activeElement, focused.speak);

  const elsewhere = setup();
  await elsewhere.emit('click', elsewhere.speak);
  const answerInput = new elsewhere.Element();
  answerInput.focus();
  elsewhere.synthesis.utterances[0].onend();
  assert.equal(elsewhere.stop.hidden, true);
  assert.equal(elsewhere.document.activeElement, answerInput);
  assert.equal(elsewhere.speak.focusCalls, 0);
});

test('native audio cancels active speech and pauses other audio only', async () => {
  const context = setup();
  const selected = new context.Audio();
  const other = new context.Audio();
  context.audios.push(selected, other);
  await context.emit('click', context.speak);
  const cancelsBefore = context.synthesis.cancelCalls;
  const selectedPausesBefore = selected.pauseCalls;
  const otherPausesBefore = other.pauseCalls;
  await context.emit('play', selected);
  assert.equal(context.synthesis.cancelCalls, cancelsBefore + 1);
  assert.equal(context.stop.hidden, true);
  assert.equal(context.speak.disabled, false);
  assert.equal(selected.pauseCalls, selectedPausesBefore);
  assert.equal(other.pauseCalls, otherPausesBefore + 1);
});

test('starting device speech pauses every native audio source', async () => {
  const context = setup();
  const first = new context.Audio();
  const second = new context.Audio();
  context.audios.push(first, second);
  await context.emit('click', context.speak);
  assert.equal(first.pauseCalls, 1);
  assert.equal(second.pauseCalls, 1);
  assert.equal(context.synthesis.utterances.length, 1);
});
