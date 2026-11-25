'use strict';

const overviewKm = metres => (metres/1000).toLocaleString('ru-RU',{maximumFractionDigits:2}) + ' км';

const overviewInks = ['#74c6ff','#b0b8ff','#78d1c5'];

function overviewRoutes() {
  return (records.routes || []).map(route => drivingRoutes.find(active=>active.id===route.id) || route);
}

let overviewMap;
let overviewOpening = false;
let overviewRouteLayers = [];
let overviewGeometry;

function showOverviewMapNotice(message, action) {
  const notice = $('overview-map-notice');
  notice.querySelector('span').textContent = message;
  const button = notice.querySelector('button');
  button.hidden = !action;
  button.textContent = action === 'retry' ? 'Повторить' : 'Подключить карту';
  button.onclick = action === 'retry' ? () => updateOverviewMap(overviewRoutes()) : openMapSettings;
  notice.hidden = !message;
}

async function updateOverviewMap(routes) {
  if (overviewOpening) return;
  const container = $('overview-map');
  if (!overviewMap) {
    const key = configuredMapKey();
    if (!key) {
      showOverviewMapNotice('Для просмотра маршрутов нужен ключ карты.', 'settings');
      return;
    }
    overviewOpening = true;
    showOverviewMapNotice('Загрузка карты…');
    try {
      const api = await loadDgisSdk();
      const center = routes.flatMap(route => route.points || []).find(isValidPoint) || [37.61,55.76];
      overviewMap = await createDgisStreetMap(api, container, key, center, 14, {
        disableZoomOnScroll: false, disableDragging: false, enableTwoFingerDragging: true, zoomControl: true
      });
      const routeAt = point => point && overviewRouteLayers.find(layer => layer.line?.contains(point));
      overviewMap.on('mousemove', event => {
        const layer = routeAt(event.point);
        const retake = retakeAt(event.point);
        container.style.cursor = layer || retake ? 'pointer' : '';
        container.title = retake?.reason || layer?.name || '';
      });
      overviewMap.on('click', event => {
        const retake = retakeAt(event.point);
        if (retake) { selectRetakeItem(retake.id); return; }
        const layer = routeAt(event.point);
        if (layer) openOverviewRoute(layer.id);
      });
      showOverviewMapNotice('');
      routes = overviewRoutes();
    } catch (error) {
      showOverviewMapNotice(mapErrorMessages[error.code] || mapErrorMessages.render,
        error.code === 'key' ? 'settings' : 'retry');
      return;
    } finally {
      overviewOpening = false;
    }
  }
  if (container.offsetWidth === 0) return;
  const paths = routes.map(route => (route.points || []).filter(isValidPoint));
  const signature = JSON.stringify(routes.map((route,i) => [route.id,route.name,paths[i]]));
  if (overviewGeometry === signature) { updateRetakeOverlays(); return; }
  for (const layer of overviewRouteLayers) {
    layer.line?.destroy();
    layer.marker.destroy();
  }
  const fit = overviewRouteLayers.length === 0;
  overviewRouteLayers = [];
  routes.forEach((route,i) => {
    const path = paths[i];
    if (!path.length) return;
    const color = overviewInks[i % overviewInks.length];
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'overview-map-number';
    button.style.borderColor = color;
    button.textContent = i + 1;
    button.title = route.name;
    button.setAttribute('aria-label',route.name);
    button.onclick = event => { event.stopPropagation(); openOverviewRoute(route.id); };
    const marker = new window.mapgl.HtmlMarker(overviewMap, {
      coordinates: path.at(-1), html: button, anchor: [11,11], interactive: true, preventMapInteractions: true
    });
    const line = path.length > 1 ? drawRouteLine(overviewMap,path,color) : null;
    overviewRouteLayers.push({id:route.id,name:route.name,marker,line});
  });
  overviewGeometry = signature;
  retakeOverlaySignature = undefined;
  updateRetakeOverlays();
  if (fit) fitDgisPoints(overviewMap,paths.flat(),0);
}

function openOverviewRoute(id, index) {
  const route=overviewRoutes().find(r=>r.id===id);
  if (!route) return;
  selectedClass='';
  state.filter=$('priority-filter').value='all';
  sectionView.enabled=index!==undefined;
  sectionView.index=null;
  sectionView.showList=false;
  switchView('map');
  const choice=drivingRoutes.find(r=>r.id===id);
  if (choice && inspectionMap) activateRoute(choice);
  else {
    $('route-select').value=id;
    renderDeck();
    const first=routeRecords(route)[0];
    if (first) showRecord(first.id,true);
    else renderSelection();
  }
  if (index!==undefined && currentSurveyRoute()?.id===id) selectSection(Number(index));
}

function overviewRouteRow(route,index,parts) {
  const id=escapeHTML(route.id);
  const members=routeRecords(route);
  const reviewed=members.filter(record=>reviewState(record)!=='pending').length;
  const bar=parts.map(part=>{
    const label=sectionRange(part)+' · '+sectionName(part.priority);
    return `<button data-over-route="${id}" data-over-section="${part.index}" title="${label}" aria-label="${escapeHTML(route.name)} · ${label}"
      style="--segment:${sectionColors[part.priority]};flex-grow:${part.end-part.start}"></button>`;
  }).join('');
  return `<li><div class="overview-route-heading"><button data-over-route="${id}"><span class="overview-number" style="color:${overviewInks[index%overviewInks.length]};border-color:currentColor">${index+1}</span>${escapeHTML(route.name)}</button>
    <span>${Number.isFinite(route.distance) ? overviewKm(route.distance) : 'Длина неизвестна'}</span></div>
    <div class="overview-band">${bar}</div><small>Проверено точек · ${reviewed} из ${members.length}</small></li>`;
}

function renderOverview() {
  const routes=overviewRoutes();
  const parts=routes.map(routeSections);
  const counts=Object.fromEntries(Object.keys(sectionColors).map(key=>[key,0]));
  for (const group of parts) for (const part of group) counts[part.priority]++;
  const total=Object.values(counts).reduce((a,b)=>a+b,0);
  const orderedKeys=['urgent','review','normal','unverified','empty'];
  const statuses=orderedKeys.map(key=>`<div><i style="background:${sectionColors[key]}"></i><dt>${sectionName(key)}</dt><dd>${counts[key]}</dd></div>`).join('');
  const bar=orderedKeys.filter(key=>counts[key]).map(key=>`<i style="background:${sectionColors[key]};flex:${counts[key]}"></i>`).join('');
  const ranked=records.objects.map(record=>({record,level:sectionPriority(record)}))
    .filter(({record,level})=>level!=='empty' && (['urgent','review'].includes(level) || reviewState(record)==='pending'))
    .sort((a,b)=>orderedKeys.indexOf(a.level)-orderedKeys.indexOf(b.level));
  const queue=ranked.slice(0,5).map(({record,level})=>{
    const frame=frameById(record.frame);
    return `<li><button data-record="${escapeHTML(record.id)}">
      ${frame ? `<img src="${escapeHTML(frame.src)}" alt="" loading="lazy">` : '<span class="overview-no-photo">Без фото</span>'}
      <span><strong>${escapeHTML(recordLabel(record))}</strong><small>${escapeHTML(displayId(record))}${record.place || isValidPoint(record.point) ? ' · ' + escapeHTML(record.place || formatPoint(record.point)) : ''}</small></span>
      <span class="overview-priority" style="--segment:${sectionColors[level]}">${sectionName(level)}</span></button></li>`;
  }).join('');
  const root=$('overview-content');
  if (!$('overview-map')) {
    root.innerHTML=`<div class="overview-head"><h1>Обзор обследований</h1><dl class="overview-metrics"></dl></div>
      <div class="overview-grid"><section class="overview-network"><div class="overview-section-head"><h2>Карта маршрутов</h2><button type="button" class="button" id="retake-layer" aria-pressed="false">Где переснять</button></div>
      <div class="overview-plot"><div id="overview-map" aria-label="Карта маршрутов обследования"></div>
      <div id="overview-map-notice" role="status" hidden><span></span> <button class="button" type="button" hidden></button></div></div>
      <div id="retake-task-panel" hidden><small>Пунктир — интервал без кадров от 100 м или весь неснятый маршрут. Знак «!» — точка для пересъёмки.</small>
      <select id="retake-item-select" aria-label="Место для пересъёмки"></select><span id="retake-item-reason" role="status"></span>
      <div><button type="button" class="button" id="retake-task-add">В задание бригаде</button>
      <button type="button" class="button" id="retake-download">Скачать задание</button></div></div><ul class="overview-routes"></ul></section>
      <div class="overview-side"><section><h2>Состояние участков</h2><p class="overview-caption"></p>
      <div class="overview-distribution" aria-hidden="true"></div><dl class="overview-statuses"></dl></section>
      <section><div class="overview-section-head"><h2>Следующие точки для проверки</h2><button class="button" type="button" id="open-finding-queue">Проверка рамок</button></div><ul class="overview-queue"></ul></section></div></div>`;
    bindRetakePanel();
    $('open-finding-queue').onclick = openFindingQueue;
  }
  root.querySelector('.overview-metrics').innerHTML=`<div><dt>Маршруты</dt><dd>${routes.length}</dd></div><div><dt>Объекты</dt><dd>${records.objects.length}</dd></div>
    <div><dt>Кадры</dt><dd>${records.frames.length}</dd></div>`;
  root.querySelector('.overview-routes').innerHTML=routes.map((r,i)=>overviewRouteRow(r,i,parts[i])).join('');
  root.querySelector('.overview-caption').textContent='По отрезкам до 100 м · всего '+total;
  root.querySelector('.overview-distribution').innerHTML=bar;
  root.querySelector('.overview-statuses').innerHTML=statuses;
  root.querySelector('.overview-queue').innerHTML=queue || '<li class="overview-empty">Очередь пуста.</li>';
  updateRetakePanel(routes);
  updateOverviewMap(routes);
}

document.getElementById('overview-content').addEventListener('click',event=>{
  const target=event.target.closest('[data-over-route]');
  if (target) openOverviewRoute(target.dataset.overRoute,target.dataset.overSection);
});
