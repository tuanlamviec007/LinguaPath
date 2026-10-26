const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '..', 'static', 'js', 'listening-workspace.js'), 'utf8');

class FakeElement {
  constructor({value = '', disabled = false, hidden = false} = {}) {
    this.value = value;
    this.disabled = disabled;
    this.hidden = hidden;
    this.textContent = '';
    this.listeners = new Map();
    this.nodes = {};
  }
  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }
  emit(type, event = {}) {
    for (const listener of this.listeners.get(type) || []) listener(event);
  }
  async emitAsync(type, event = {}) {
    return Promise.all((this.listeners.get(type) || []).map((listener) => listener(event)));
  }
  querySelector(selector) { return this.nodes[selector] || null; }
}

class FakeAudio extends FakeElement {
  constructor({duration = Number.NaN, currentTime = 0, readyState = 0, playbackRate = 1, playResult = 'resolve'} = {}) {
    super();
    this.duration = duration;
    this.currentTime = currentTime;
    this.readyState = readyState;
    this.playbackRate = playbackRate;
    this.controls = true;
    this.playResult = playResult;
    this.playCalls = 0;
    this.pauseCalls = 0;
    this.ended = false;
  }
  play() {
    this.playCalls += 1;
    return this.playResult === 'reject' ? Promise.reject(new Error('NotAllowedError')) : Promise.resolve();
  }
  pause() { this.pauseCalls += 1; }
}

function makePlayer(audio, {rate = '1'} = {}) {
  const player = new FakeElement();
  const replay = new FakeElement({disabled: true});
  const back = new FakeElement({disabled: true});
  const speed = new FakeElement({value: rate});
  const status = new FakeElement();
  const error = new FakeElement({hidden: true});
  Object.assign(player.nodes, {
    audio, '[data-audio-replay]': replay, '[data-audio-back]': back,
    '[data-audio-rate]': speed, '[data-audio-status]': status,
    '[data-audio-error]': error,
  });
  return {player, audio, replay, back, speed, status, error};
}

function setup(players, otherAudios = []) {
  const pagehideListeners = [];
  const document = {
    querySelectorAll(selector) {
      if (selector === '[data-listening-player]') return players.map(({player}) => player);
      if (selector === 'audio') return [...players.map(({audio}) => audio).filter(Boolean), ...otherAudios];
      return [];
    },
  };
  const window = {addEventListener: (type, listener) => { if (type === 'pagehide') pagehideListeners.push(listener); }};
  vm.runInContext(script, vm.createContext({document, window}), {filename: 'listening-workspace.js'});
  return {pagehideListeners};
}

test('back 10 seconds clamps at zero and never starts or pauses playback', () => {
  const card = makePlayer(new FakeAudio({duration: 30, currentTime: 6, readyState: 1}));
  setup([card]);
  assert.equal(card.back.disabled, false);
  card.back.emit('click');
  assert.equal(card.audio.currentTime, 0);
  assert.equal(card.audio.playCalls, 0);
  assert.equal(card.audio.pauseCalls, 0);
  assert.match(card.status.textContent, /tối đa 10 giây/);
  card.audio.currentTime = 24;
  card.back.emit('click');
  assert.equal(card.audio.currentTime, 14);
  assert.equal(card.audio.playCalls, 0);
  assert.equal(card.audio.pauseCalls, 0);
});

test('replay resets to the start, requests play, and reports a rejected play request', async () => {
  const card = makePlayer(new FakeAudio({duration: 25, currentTime: 20, readyState: 1, playResult: 'resolve'}));
  setup([card]);
  await card.replay.emitAsync('click');
  assert.equal(card.audio.currentTime, 0);
  assert.equal(card.audio.playCalls, 1);

  const blocked = makePlayer(new FakeAudio({duration: 25, currentTime: 9, readyState: 1, playResult: 'reject'}));
  setup([blocked]);
  await blocked.replay.emitAsync('click');
  assert.equal(blocked.audio.currentTime, 0);
  assert.equal(blocked.audio.playCalls, 1);
  assert.match(blocked.status.textContent, /bấm nút phát trên thanh âm thanh/);
});

test('only the supported playback rates change the native audio rate', () => {
  const card = makePlayer(new FakeAudio({duration: 30, readyState: 1}));
  setup([card]);
  for (const value of ['0.75', '1', '1.25']) {
    card.speed.value = value;
    card.speed.emit('change');
    assert.equal(card.audio.playbackRate, Number(value));
    assert.match(card.status.textContent, /công cụ hỗ trợ luyện nghe/);
  }
  const statusBeforeInvalid = card.status.textContent;
  card.speed.value = '2';
  card.speed.emit('change');
  assert.equal(card.audio.playbackRate, 1.25);
  assert.equal(card.status.textContent, statusBeforeInvalid);
});

test('native controls remain available; custom controls follow metadata and audio errors', () => {
  const audio = new FakeAudio({duration: Number.NaN, readyState: 0});
  const card = makePlayer(audio);
  setup([card]);
  assert.equal(audio.controls, true);
  assert.equal(card.back.disabled, true);
  assert.equal(card.replay.disabled, true);

  audio.duration = 16;
  audio.emit('loadedmetadata');
  assert.equal(card.back.disabled, false);
  assert.equal(card.replay.disabled, false);
  assert.match(card.status.textContent, /đã sẵn sàng/);

  audio.emit('error');
  assert.equal(audio.controls, true);
  assert.equal(card.error.hidden, false);
  assert.equal(card.back.disabled, true);
  assert.equal(card.replay.disabled, true);
  assert.match(card.status.textContent, /Các lựa chọn trả lời vẫn được giữ/);
});

test('TTS-only controls are not treated as audio players and pagehide pauses native audio', () => {
  const card = makePlayer(new FakeAudio({duration: 12, readyState: 1}));
  const ttsOnly = makePlayer(null);
  const unrelatedNativeAudio = new FakeAudio({duration: 5});
  const {pagehideListeners} = setup([card, ttsOnly], [unrelatedNativeAudio]);
  assert.equal(ttsOnly.replay.listeners.size, 0);
  assert.equal(card.audio.pauseCalls, 0);
  for (const listener of pagehideListeners) listener();
  assert.equal(card.audio.pauseCalls, 1);
  assert.equal(unrelatedNativeAudio.pauseCalls, 1);
});

test('a cached loading failure is shown immediately and successful recovery restores controls', () => {
  const audio = new FakeAudio({duration: 30, readyState: 1});
  audio.error = {code: 4};
  const card = makePlayer(audio);
  setup([card]);
  assert.equal(card.error.hidden, false);
  assert.equal(card.replay.disabled, true);
  assert.equal(card.back.disabled, true);
  assert.match(card.status.textContent, /Chưa phát được âm thanh/);
  audio.error = null;
  audio.emit('canplay');
  assert.equal(card.error.hidden, true);
  assert.equal(card.replay.disabled, false);
  assert.equal(card.back.disabled, false);
});
