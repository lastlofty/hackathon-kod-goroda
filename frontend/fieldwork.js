'use strict';

function retakeReason(record) {
  if (!frameById(record.frame)) return 'Нет снимка';
  return record.inspectionReview?.decision === 'unseen' ? 'Объект не виден на кадре' : '';
}

function orderedStops(route) {
  const path = route?.points || [];
  return routeRecords(route).map(record => ({
    record, position:isValidPoint(record.point) ? fractionAlongRoute(record.point, path) : Infinity
  })).sort((a,b) => a.position - b.position).map(stop => stop.record);
}

function retakeStops() {
  return [...orderedStops(currentSurveyRoute()), ...records.objects.filter(r => !r.routeId)].filter(retakeReason);
}

function renderRetakes() {
  const active = state.filter === 'retake';
  $('retake-toggle').setAttribute('aria-pressed', String(active));
  $('retake-list').hidden = !active;
  $('retake-list').parentElement.classList.toggle('retakes-active', active);
  if (!active) return;
  const stops = retakeStops().filter(matchesClass);
  $('retake-list').innerHTML = '<h2>Что переснять</h2>' + (stops.length ? '<ol>' + stops.map(record =>
    `<li><button data-retake="${escapeHTML(record.id)}" aria-pressed="${record.id === state.selected}"><strong>${escapeHTML(record.place || formatPoint(record.point))}</strong><span>${escapeHTML(displayId(record))} · ${retakeReason(record)}${record.routeId ? '' : ' · вне маршрута'}</span></button></li>`
  ).join('') + '</ol>' : '<p class="subtle">На выбранном маршруте нет точек для пересъёмки.</p>');
  $('retake-list').querySelectorAll('strong').forEach((field,index) => {
    const record = stops[index];
    if (!record.place && isValidPoint(record.point)) showPointAddress(record, field, formatPoint(record.point));
  });
}

function changePointFilter(value) {
  if (value === 'retake' && liveSurvey.active) setLiveMode(false);
  drivePlayer?.pause();
  state.filter = $('priority-filter').value = value;
  renderDeck();
  renderSelection();
}

function cropHTML(frame, box) {
  return `<survey-crop role="img" aria-label="${escapeHTML(box.label || 'Фрагмент снимка')}" data-src="${escapeHTML(frame.src)}" data-path="${isPathType(box.type) ? escapeHTML(JSON.stringify({type:box.type,points:box.points})) : ''}" data-rect="${[box.x,box.y,box.w,box.h].map(Number).join(',')}"></survey-crop>`;
}

// Draw in source pixels so the box stays registered on portrait and landscape photos.
customElements.define('survey-crop', class extends HTMLElement {
  connectedCallback() {
    const image = new Image();
    image.onload = () => {
      if (!this.isConnected) return;
      const [x,y,w,h] = this.dataset.rect.split(',').map(Number);
      const width = image.naturalWidth, height = image.naturalHeight;
      const padding = Math.max(8, Math.max(w * width, h * height) * .18);
      const left = Math.max(0, x * width - padding), top = Math.max(0, y * height - padding);
      const right = Math.min(width, (x+w)*width + padding), bottom = Math.min(height, (y+h)*height + padding);
      const cw = right-left, ch = bottom-top;
      if (!(cw > 0 && ch > 0)) { this.replaceChildren(image); return; }
      const canvas = document.createElement('canvas');
      const scale = Math.min(1100 / Math.max(cw,ch), 3);
      canvas.width = Math.max(1,Math.round(cw*scale)); canvas.height = Math.max(1,Math.round(ch*scale));
      const ctx = canvas.getContext('2d');
      ctx.scale(canvas.width/cw, canvas.height/ch);
      ctx.drawImage(image,left,top,cw,ch,0,0,cw,ch);
      ctx.lineWidth = 2/scale; ctx.strokeStyle = '#69bdff';
      ctx.translate(-left,-top);
      strokeAnnotation(ctx,this.dataset.path ? JSON.parse(this.dataset.path) : {x,y,w,h},width,height);
      this.replaceChildren(canvas);
    };
    image.onerror = () => { this.textContent = 'Снимок недоступен'; };
    image.src = this.dataset.src;
    this.ready = image.decode().catch(() => {});
  }
});

let compareRecordId;
function captureDay(frame) {
  if (frame.capturedOn) return frame.capturedOn;
  const match = !frame.backend && /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(frame.time);
  return match ? `${match[3]}-${match[2]}-${match[1]}` : '';
}

function comparisonPhotos(record) {
  const frameIds = new Set([record.frame, ...(record.captureFrames || [])]);
  const linked = records.frames.filter(f => frameIds.has(f.id) || f.assetId === record.id)
    .map(f => ({id:f.id, day:captureDay(f), src:f.src, name:f.name}));
  return linked.concat((records.comparisonPhotos || []).filter(f => f.assetId === record.id))
    .filter(photo => photo.day && photo.src).sort((a,b) => a.day.localeCompare(b.day));
}

function updateComparison(changed) {
  const record = records.objects.find(r => r.id === compareRecordId);
  if (!record) return;
  const photos = comparisonPhotos(record);
  const left = $('compare-before'), right = $('compare-after');
  const ready = photos.length > 1 && photos[0].day !== photos.at(-1).day;
  $('compare-pair').hidden = !ready;
  $('compare-empty').hidden = ready;
  if (!ready) {
    $('compare-empty').textContent = photos.length ? 'Есть снимок за ' + photos[0].day.split('-').reverse().join('.') +
      '. Добавьте снимок этой точки за другую дату.' : 'Добавьте два снимка этой точки за разные даты.';
    return;
  }
  const options = items => items.map(p => new Option(p.day.split('-').reverse().join('.') + ' · ' + p.name,p.id));
  const before = changed ? photos.find(p => p.id === left.value) || photos[0] : photos[0];
  left.replaceChildren(...options(photos.filter(p => p.day < photos.at(-1).day)));
  left.value = before.id;
  const later = photos.filter(p => p.day > before.day);
  const after = changed ? later.find(p => p.id === right.value) || later.at(-1) : later.at(-1);
  right.replaceChildren(...options(later)); right.value = after.id;
  $('before-image').src = before.src; $('after-image').src = after.src;
  if (!changed) $('compare-range').value = 50;
  $('compare-stage').style.setProperty('--split', $('compare-range').value + '%');
}

function openComparison() {
  const record = records.objects.find(r => r.id === state.selected);
  if (!record) return;
  drivePlayer?.pause();
  compareRecordId = record.id;
  $('compare-title').textContent = 'До / после · ' + displayId(record);
  $('compare-form').reset(); $('compare-message').textContent = '';
  updateComparison(); $('compare-dialog').showModal();
}

function bindFieldwork() {
  $('problems-only').onchange = updateRouteReport;
  $('compare-form').addEventListener('submit', async event => {
    event.preventDefault();
    const form = event.currentTarget, file = $('repeat-image').files[0], day = $('repeat-date').value;
    if (!file || !day) return;
    const assetId = compareRecordId;
    const submit = form.querySelector('button[type="submit"]');
    if (submit.disabled) return;
    submit.disabled = true;
    try {
      if (file.size > 25*1024*1024) throw new Error('Выберите файл до 25 МБ.');
      const src = await imagePreview(file);
      const photo = {id:newId(), local:true, assetId, day, src, name:file.name};
      const photos = (records.comparisonPhotos ??= []);
      photos.push(photo);
      try { localStorage.setItem(savedKey,JSON.stringify(records)); }
      catch { photos.pop(); throw new Error('Не хватило места для снимка в этом браузере.'); }
      if (compareRecordId === assetId) { form.reset(); updateComparison(); $('compare-message').textContent = 'Снимок сохранён для этой точки.'; }
    } catch (error) { $('compare-message').textContent = error instanceof Error ? error.message : 'Не удалось прочитать снимок.'; }
    finally { submit.disabled = false; }
  });
  $('compare-before').onchange = $('compare-after').onchange = () => updateComparison(true);
  $('compare-range').oninput = event => $('compare-stage').style.setProperty('--split', event.target.value + '%');
}
