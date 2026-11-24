'use strict';

function createDrivePlayer(map, route, onEnter) {
  const points = route.points;
  const distances = [0];
  const degrees = Math.PI / 180;
  const [toggle, restart, progress, detail, panel] = ['drive-play', 'drive-restart', 'drive-progress', 'drive-detail', 'drive-panel']
    .map(id => document.getElementById(id));
  for (let i = 1; i < points.length; i++) {
    const [lng, lat] = points[i - 1];
    const [nextLng, nextLat] = points[i];
    const x = (nextLng - lng) * Math.cos((lat + nextLat) * degrees / 2);
    distances.push(distances[i - 1] + Math.hypot(x, nextLat - lat) * 111195);
  }
  const length = distances.at(-1);
  const playTime = Math.max(20000, Math.min(42000, (route.duration || 300) * 1000 / 12));
  let elapsed = 0;
  let frame = null;
  let last = 0;
  let inDrive = false;

  const minutes = Math.floor(route.duration / 60);
  const seconds = String(route.duration % 60).padStart(2, '0');
  detail.textContent = `${new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 1}).format(route.distance / 1000)} км · ${minutes}:${seconds}`;
  detail.title = 'Оценка времени в пути от 2ГИС';
  panel.hidden = false;

  function poseAt(distance) {
    let end = 1;
    while (end < distances.length - 1 && distances[end] <= distance) end++;
    const start = end - 1;
    const t = Math.min(1, (distance - distances[start]) / (distances[end] - distances[start] || 1));
    const point = points[start].map((value, i) => value + t * (points[end][i] - value));
    const dx = (points[end][0] - points[start][0]) * Math.cos(point[1] * degrees);
    const dy = points[end][1] - points[start][1];
    return {point, heading: Math.atan2(dx, dy) / degrees};
  }

  function render(deltaMs) {
    const distance = length * elapsed / playTime;
    const {point, heading} = poseAt(distance);
    map.updateDrive(point, heading, deltaMs);
    progress.value = Math.round(elapsed / playTime * 1000);
  }

  function enter() {
    if (inDrive) return;
    onEnter();
    map.startDrive(poseAt(length * elapsed / playTime).point);
    inDrive = true;
  }

  function pause() {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    last = 0;
    toggle.textContent = 'Проезд 3D';
  }

  function finish() {
    pause();
    if (!inDrive) return;
    map.endDrive();
    inDrive = false;
  }

  function tick(time) {
    const deltaMs = last ? Math.min(100, time - last) : 0;
    last = time;
    elapsed = Math.min(playTime, elapsed + deltaMs);
    render(deltaMs);
    if (elapsed < playTime) frame = requestAnimationFrame(tick);
    else finish();
  }

  function start() {
    const snap = !inDrive || elapsed === 0;
    enter();
    if (snap) render();
    toggle.textContent = 'Пауза';
    frame = requestAnimationFrame(tick);
  }

  toggle.onclick = () => {
    if (frame !== null) {
      pause();
      return;
    }
    if (elapsed === playTime) elapsed = 0;
    start();
  };
  restart.onclick = () => {
    pause();
    elapsed = 0;
    start();
  };
  progress.oninput = () => {
    pause();
    elapsed = Number(progress.value) / 1000 * playTime;
    if (elapsed === playTime && !inDrive) return;
    enter();
    render();
    if (elapsed === playTime) finish();
  };

  return {
    exit() {
      pause();
      elapsed = 0;
      progress.value = 0;
      if (!inDrive) return;
      map.endDrive();
      inDrive = false;
    }
  };
}
