'use strict';

const sectionColors = {empty:'#78838e', unverified:'#859fbb', normal:'#80c8a9', review:'#bc9bff', urgent:'#ff8178'};
const sectionName = priority => priorities[priority] || 'Нет наблюдений';

const sectionView = {enabled:false, routeId:null, index:null, showList:false, parts:[]};
const verdictNames = {accepted:'Верно', corrected:'Другой класс', rejected:'Ложное обнаружение'};

function boxVerdict(frame, boxId) {
  return records.boxReviews?.[JSON.stringify([frame?.id, boxId])];
}

function checkedLabel(frame, box) {
  const verdict = boxVerdict(frame, box.id);
  return verdict?.decision === 'corrected' ? verdict.label : box.label;
}

function recordLabel(record) {
  const verdict = record.box && boxVerdict(frameById(record.frame),record.box);
  return verdict?.decision === 'corrected' ? verdict.label : record.type;
}

function reportBoxes(frame) {
  return frame.boxes.filter(box => boxVerdict(frame,box.id)?.decision !== 'rejected')
    .map(box => ({...box, label:checkedLabel(frame,box)}));
}

function reviewSummary(frame) {
  return (frame?.boxes || []).flatMap(box => {
    const verdict = boxVerdict(frame, box.id);
    return verdict ? [verdict.original + ' — ' + verdictNames[verdict.decision] +
      (verdict.decision === 'corrected' ? ' · ' + verdict.label : '')] : [];
  });
}

function boxReviewControls(frame, box) {
  const verdict = boxVerdict(frame, box.id);
  return '<section class="box-decisions"><strong>' + escapeHTML(checkedLabel(frame, box)) + '</strong>' +
    Object.entries(verdictNames).map(([key, title]) =>
      `<button type="button" class="button" data-verdict="${key}" aria-pressed="${verdict?.decision === key}">${title}</button>`
    ).join('') + '</section>';
}

function saveBoxVerdict(frame, box, decision, label) {
  const key = JSON.stringify([frame.id, box.id]);
  const reviews = records.boxReviews ??= {};
  const original = reviews[key]?.original || frame.inference?.find(f => f.id === box.id)?.label || box.label;
  reviews[key] = {decision, original, label:label || original, time:new Date().toISOString()};
  const record = records.objects.find(r => r.frame === frame.id && r.box === box.id) ||
    records.objects.find(r => r.id === state.selected && r.frame === frame.id);
  recordChange(original + ' · ' + verdictNames[decision] + (label ? ' · ' + label : ''), record, frame);
  renderDeck();
  renderSelection();
  persist('Решение по рамке сохранено.');
}

function crewReason(record) {
  const issue = record.issue && record.issue !== record.type ? record.issue : '';
  return record.inspectionReview?.note || retakeReason(record) || record.recommendation || issue || priorities[priorityOf(record)];
}

function sectionPriority(record) {
  const priority = priorityOf(record);
  if (!record.inspectionReview?.note && record.box && boxVerdict(frameById(record.frame), record.box)?.decision === 'rejected') return 'empty';
  if (priority === 'urgent') return priority;
  if (record.inspectionReview?.note || retakeReason(record) || needsFollowup(record)) return 'review';
  return priority;
}

// Split at chainage boundaries, keeping the original road vertices between them.
function routeSections(route) {
  const points = route?.points || [];
  if (points.length < 2 || !(route.distance > 0)) return [];
  const offsets = [0];
  for (let i = 1; i < points.length; i++) {
    const a = points[i-1], b = points[i];
    const scale = Math.cos((a[1]+b[1])*Math.PI/360);
    offsets.push(offsets.at(-1) + Math.hypot((b[0]-a[0])*scale,b[1]-a[1]));
  }
  const length = offsets.at(-1);
  if (!length) return [];
  const chainage = offsets.map(offset => offset / length * route.distance);
  const parts = [];
  let previousEnd = points[0];
  let next = 1;
  for (let start = 0; start < route.distance; start += 100) {
    const end = Math.min(start+100,route.distance);
    const path = [previousEnd];
    while (next < points.length-1 && chainage[next] <= end) {
      if (chainage[next] > start) path.push(points[next]);
      next++;
    }
    const span = chainage[next] - chainage[next-1];
    const t = span > 0 ? (end-chainage[next-1])/span : 1;
    previousEnd = points[next].map((v,k) => points[next-1][k] + t*(v-points[next-1][k]));
    if (path.at(-1)[0] !== previousEnd[0] || path.at(-1)[1] !== previousEnd[1]) path.push(previousEnd);
    parts.push({index:parts.length, start, end, path, members:[], priority:'empty'});
  }
  const levels = Object.keys(sectionColors);
  for (const record of routeRecords(route)) {
    if (!isValidPoint(record.point)) continue;
    const metre = fractionAlongRoute(record.point, points)*route.distance;
    const part = parts[Math.min(parts.length-1,Math.floor(metre/100))];
    const priority = sectionPriority(record);
    if (priority === 'empty') continue;
    part.members.push(record);
    if (levels.indexOf(priority)>levels.indexOf(part.priority)) part.priority = priority;
  }
  return parts;
}

const sectionRange = part => Math.round(part.start) + '–' + Math.round(part.end) + ' м';

function updateSections(route) {
  if (sectionView.routeId !== route?.id) {
    sectionView.routeId = route?.id;
    sectionView.index = null;
    sectionView.showList = false;
  }
  const enabled = sectionView.enabled && !liveSurvey.active && route;
  const parts = sectionView.parts = enabled ? routeSections(route) : [];
  $('section-toggle').setAttribute('aria-pressed',String(Boolean(enabled)));
  $('section-strip').hidden = !parts.length;
  $('section-strip').innerHTML = parts.map(p =>
    `<button type="button" data-section="${p.index}" style="--section-color:${sectionColors[p.priority]}" aria-pressed="${sectionView.index === p.index}" title="${sectionRange(p)} · ${sectionName(p.priority)}">${sectionRange(p)} · ${sectionName(p.priority)}</button>`
  ).join('');
  inspectionMap?.setSections?.(parts,selectSection);
}

function selectSection(index) {
  const part = sectionView.parts[index];
  if (!part) return;
  sectionView.index = index;
  sectionView.showList = true;
  drivePlayer?.exit();
  inspectionMap?.fitPoints(part.path);
  renderDeck();
  renderSelection();
}

function renderSectionCard(part) {
  const ordered = [...part.members].sort((a,b) => Object.keys(sectionColors).indexOf(sectionPriority(b))-Object.keys(sectionColors).indexOf(sectionPriority(a)));
  $('inspector-content').innerHTML = `<section class="crew-card"><h2>Участок ${sectionRange(part)}</h2>
    <p class="section-state" style="--section-color:${sectionColors[part.priority]}">${sectionName(part.priority)} · Точек: ${ordered.length}</p>
    <button type="button" class="button primary" data-crew-zip>Скачать задание</button>
    <ul>${ordered.map(r => {
      const frame = frameById(r.frame);
      return `<li><button type="button" data-section-record="${escapeHTML(r.id)}">${frame ? `<img src="${escapeHTML(frame.src)}" alt="">` : ''}
        <span><b>${escapeHTML(recordLabel(r))}</b><span class="crew-address">${escapeHTML(r.place || formatPoint(r.point))}</span><span>${escapeHTML(crewReason(r))}</span></span></button></li>`;
    }).join('')}</ul></section>`;
  $('inspector-content').querySelectorAll('.crew-address').forEach((field,index) => {
    const record = ordered[index];
    if (!record.place) showPointAddress(record,field,formatPoint(record.point));
  });
}

function bindCrewTools() {
  $('section-back').onclick = () => selectSection(sectionView.index);
  $('section-toggle').onclick = () => {
    if (liveSurvey.active) setLiveMode(false);
    sectionView.enabled = !sectionView.enabled;
    sectionView.index = null;
    sectionView.showList = false;
    drivePlayer?.exit();
    renderDeck();
    if (sectionView.enabled && sectionView.parts.length) {
      const ranked = [...sectionView.parts].filter(p=>p.members.length).sort((a,b)=>
        Object.keys(sectionColors).indexOf(b.priority)-Object.keys(sectionColors).indexOf(a.priority));
      selectSection(ranked[0]?.index ?? 0);
    } else renderSelection();
  };
  document.addEventListener('click',event => {
    const target = event.target.closest('[data-section],[data-section-record],[data-crew-zip],[data-verdict]');
    if (!target) return;
    if (target.hasAttribute('data-section')) return selectSection(Number(target.dataset.section));
    if (target.dataset.sectionRecord) {
      sectionView.showList = false;
      const item = records.objects.find(r=>r.id===target.dataset.sectionRecord);
      if (item) openSurveyRecord(item);
    } else if (target.hasAttribute('data-crew-zip')) {
      exportCrewTask(currentSurveyRoute(),sectionView.parts[sectionView.index],target);
    } else if (target.dataset.verdict) {
      const frame = frameById(records.objects.find(r=>r.id===state.selected)?.frame);
      const box = frame?.boxes.find(b=>b.id===state.focusBox);
      if (!box) return;
      if (target.dataset.verdict === 'corrected') {
        const form = $('correct-class-form');
        form.dataset.frame = frame.id;
        form.dataset.box = box.id;
        $('correct-class-input').value = checkedLabel(frame,box);
        $('correct-class-dialog').showModal();
        $('correct-class-input').select();
      } else saveBoxVerdict(frame,box,target.dataset.verdict);
    }
  });
  $('correct-class-form').onsubmit = event => {
    event.preventDefault();
    const label = $('correct-class-input').value.trim();
    if (!label) return;
    const frame = frameById(event.currentTarget.dataset.frame);
    const box = frame?.boxes.find(b=>b.id===event.currentTarget.dataset.box);
    if (box) saveBoxVerdict(frame,box,'corrected',label);
    $('correct-class-dialog').close();
  };
  $('correct-class-cancel').onclick = () => $('correct-class-dialog').close();
  $('live-event').onclick = markLiveEvent;
}

let photoDatabase;
function storedEventPhoto(id, blob) {
  photoDatabase ??= new Promise((resolve,reject) => {
    const open = indexedDB.open(savedKey + '-event-photos',1);
    open.onupgradeneeded = () => open.result.createObjectStore('photos');
    open.onsuccess = () => resolve(open.result);
    open.onerror = () => reject(open.error);
  }).catch(error => { photoDatabase = null; throw error; });
  return photoDatabase.then(db => new Promise((resolve,reject) => {
    const tx = db.transaction('photos',blob ? 'readwrite' : 'readonly');
    const store = tx.objectStore('photos');
    const req = blob ? store.put(blob,id) : store.get(id);
    tx.oncomplete = () => resolve(req.result);
    tx.onabort = () => reject(tx.error);
  }));
}

async function restoreEventPhotos() {
  await Promise.all(records.frames.filter(f => f.eventPhoto).map(async frame => {
    frame.src = frame.originalSrc;
    try {
      const blob = await storedEventPhoto(frame.id);
      if (blob) frame.src = URL.createObjectURL(blob);
    } catch { /* The original URL is still available when storage is disabled. */ }
  }));
}

async function markLiveEvent() {
  const record = records.objects.find(r=>r.id===state.selected);
  const frame = frameById(record?.frame);
  if (!liveSurvey.active || !isLiveFrame(frame) || $('live-event').disabled) return;
  const id = newId();
  const now = new Date();
  const point = frame.cameraPoint || (record.pointKind === 'observation' ? record.point : null);
  const event = {id, displayId:'Событие ' + now.toLocaleTimeString('ru-RU'), origin:'manual', type:'Событие проезда',
    priority:'review', issue:'Отмечено оператором', routeId:frame.routeId || record.routeId,
    frame:'event-' + id, point, pointKind:'observation', place:record.pointKind === 'observation' ? record.place : '',
    markedAt:now.toISOString(), sourceFrame:frame.id};
  $('live-event').disabled = true;
  try {
    const response = await fetch(frame.src,{signal:AbortSignal.timeout(15000)});
    if (!response.ok) throw new Error();
    const blob = await response.blob();
    await storedEventPhoto(event.frame,blob);
    records.frames.push({id:event.frame, name:frame.name, src:URL.createObjectURL(blob), originalSrc:frame.src, eventPhoto:true,
      time:frame.time, capturedMs:frame.capturedMs, capturedOn:frame.capturedOn, cameraPoint:point, boxes:[]});
    records.objects.push(event);
    recordChange('Отмечено событие проезда',event);
    renderDeck();
    renderTotals();
    persist('Событие сохранено в истории. Проезд продолжается.');
  } catch {
    announce('Не удалось сохранить снимок события. Проверьте доступ к фото и хранилищу браузера.');
  } finally {
    $('live-event').disabled = false;
    renderLiveStatus();
  }
}

async function annotatedCrewPhoto(frame) {
  const image = new Image();
  image.crossOrigin = 'anonymous';
  image.src = frame.src;
  await image.decode();
  const canvas = document.createElement('canvas');
  canvas.width = image.naturalWidth;
  canvas.height = image.naturalHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(image,0,0);
  const size = Math.max(14,Math.round(canvas.width/66));
  ctx.font = 'bold ' + size + 'px sans-serif';
  ctx.lineWidth = Math.max(2,Math.round(size/5));
  for (const box of frame.boxes) {
    const verdict = boxVerdict(frame,box.id);
    if (verdict?.decision === 'rejected') continue;
    const x=box.x*canvas.width, y=box.y*canvas.height;
    ctx.strokeStyle = '#64bfff';
    strokeAnnotation(ctx,box,canvas.width,canvas.height);
    const label = checkedLabel(frame,box);
    const w = Math.min(canvas.width,ctx.measureText(label).width+10);
    const left = Math.min(x,canvas.width-w), top = Math.max(0,y-size-8);
    ctx.fillStyle='#102536'; ctx.fillRect(left,top,w,size+7);
    ctx.fillStyle='#fff'; ctx.fillText(label,left+4,top+size+1,w-6);
  }
  const blob = await new Promise((resolve,reject)=>canvas.toBlob(b=>b ? resolve(b) : reject(new Error()),'image/jpeg',.92));
  return new Uint8Array(await blob.arrayBuffer());
}

let crewExportBusy = false;
async function exportCrewTask(route, part, button) {
  if (!part || !route || button.disabled || crewExportBusy) return;
  crewExportBusy = true;
  button.disabled = true;
  button.textContent = 'Собираем задание…';
  try {
    const features = [{type:'Feature',geometry:{type:'LineString',coordinates:part.path},
      properties:{route:route.name,from_m:part.start,to_m:part.end,priority:sectionName(part.priority)}}];
    const files = {};
    const photos = new Map();
    const rows = [];
    for (const record of part.members) {
      const frame = frameById(record.frame);
      let photo = frame && photos.get(frame.id);
      if (frame && !photo) {
        photo = 'photos/' + (photos.size+1) + '.jpg';
        files[photo] = await annotatedCrewPhoto(frame);
        photos.set(frame.id,photo);
      }
      const decisions = reviewSummary(frame);
      let address = record.place;
      if (!address && isValidPoint(record.point)) {
        try { address = await lookupPointAddress(record.point); } catch { /* GPS remains available offline. */ }
      }
      const properties = {id:record.id, object:recordLabel(record), address:address || '', reason:crewReason(record),
        priority:sectionName(sectionPriority(record)), photo:photo || null, boxReviews:decisions, eventTime:record.markedAt};
      features.push({type:'Feature',geometry:{type:'Point',coordinates:record.point},properties});
      rows.push(`<tr><td>${escapeHTML(properties.object)}</td><td>${escapeHTML(address || 'Адрес не определён')}<br>${escapeHTML(formatPoint(record.point))}</td>
        <td>${escapeHTML(properties.priority)}<br>${escapeHTML(properties.reason)}</td>
        <td>${photo ? `<a href="${photo}"><img src="${photo}" width="160" alt="Открыть фото"></a>` : 'Кадр отсутствует'}<br>${decisions.map(escapeHTML).join('<br>')}</td></tr>`);
    }
    const title = escapeHTML(route.name + ' · ' + sectionRange(part));
    files['task.html'] = fflate.strToU8(`<!doctype html><html lang="ru"><meta charset="utf-8"><title>${title}</title>
      <style>body{font:16px system-ui;margin:2rem;color:#172630}table{border-collapse:collapse}td,th{padding:10px;border:1px solid #b2c0cc;text-align:left}img{max-width:100%}</style>
      <h1>Задание бригаде</h1><h2>${title}</h2><p>${sectionName(part.priority)} · Точек: ${rows.length}</p>
      <table><thead><tr><th>Объект</th><th>Адрес и координаты</th><th>Причина выезда</th><th>Фото и проверка рамок</th></tr></thead><tbody>${rows.join('')}</tbody></table></html>`);
    files['section.geojson'] = fflate.strToU8(JSON.stringify({type:'FeatureCollection',features},null,2));
    download(fflate.zipSync(files,{level:0}),'application/zip','Задание-' + route.id + '-' + part.start + 'м.zip');
    announce('Задание готово. Откройте task.html в распакованном архиве.');
  } catch {
    announce('Не удалось собрать задание полностью. Проверьте доступность фотографий и повторите.');
  } finally {
    crewExportBusy = false;
    button.disabled = false;
    button.textContent = 'Скачать задание';
  }
}
