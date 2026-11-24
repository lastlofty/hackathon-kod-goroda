const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function playerFixture() {
  const elements = Object.fromEntries(
    ['drive-play', 'drive-restart', 'drive-progress', 'drive-detail', 'drive-panel']
      .map(id => [id, {value: 0, hidden: true, textContent: ''}])
  );
  const calls = {start: 0, end: 0, endOptions: [], update: 0};
  const map = {
    startDrive() { calls.start++; },
    updateDrive() { calls.update++; },
    endDrive(options) { calls.end++; calls.endOptions.push(options); }
  };
  const callbacks = new Map();
  let nextFrame = 0;
  const context = {
    document: {getElementById: id => elements[id]},
    requestAnimationFrame(callback) { callbacks.set(++nextFrame, callback); return nextFrame; },
    cancelAnimationFrame(id) { callbacks.delete(id); },
    Intl, Math, String, Number
  };
  const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'drive.js'), 'utf8');
  vm.runInNewContext(source, context);
  const player = context.createDrivePlayer(map, {
    points: [[37.6, 55.7], [37.61, 55.71]], duration: 60, distance: 1500
  }, () => {});
  function tick(time) {
    const [id, callback] = callbacks.entries().next().value;
    callbacks.delete(id);
    callback(time);
  }
  return {elements, calls, player, tick};
}

test('natural completion restores the overview and allows another drive', () => {
  const {elements, calls, tick} = playerFixture();
  elements['drive-play'].onclick();
  tick(1000);
  for (let time = 1100; time <= 21000; time += 100) tick(time);
  assert.equal(calls.start, 1);
  assert.equal(calls.end, 1);
  assert.equal(calls.endOptions[0], undefined);
  assert.equal(elements['drive-progress'].value, 1000);
  assert.equal(elements['drive-play'].textContent, 'Проезд 3D');
  elements['drive-play'].onclick();
  assert.equal(calls.start, 2);
  assert.equal(elements['drive-progress'].value, 0);
});

test('seeking to the end restores the overview; exit does not repeat it', () => {
  const {elements, calls, player} = playerFixture();
  elements['drive-play'].onclick();
  elements['drive-progress'].value = 1000;
  elements['drive-progress'].oninput();
  assert.equal(calls.end, 1);
  assert.equal(calls.endOptions[0], undefined);
  player.exit();
  assert.equal(calls.end, 1);
});
