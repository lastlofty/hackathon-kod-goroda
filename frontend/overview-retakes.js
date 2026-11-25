'use strict';

let retakeLayerEnabled = false;
let retakeItems = [];
let retakeSelection = '';
let retakeOverlays = [];
let retakeOverlaySignature;

function overviewRetakeItems(routes) {
  const items = [];
  const routeNames = new Map(routes.map(route => [route.id,route.name]));
  for (const route of routes) {
    if (!(route.distance > 0) || route.points?.length < 2) continue;
    const {captures} = routeCapturePositions(route);
    const ends = [...new Set(captures.map(shot => shot.fraction).concat(1))].sort((a,b)=>a-b);
    for (const part of splitRouteAt(route, ends.map(value=>value*route.distance))) {
      if (captures.length && Math.round(part.end-part.start) < 100) continue;
      items.push({
        id:JSON.stringify(['gap',route.id,Math.round(part.start),Math.round(part.end)]),
        route:route.name, label:sectionRange(part), reason:'Нет привязанных кадров',
        geometry:{type:'LineString',coordinates:part.path}
      });
    }
  }
  for (const record of records.objects) {
    const reason = retakeReason(record);
    if (!reason || !isValidPoint(record.point)) continue;
    items.push({
      id:JSON.stringify(['point',record.id]), route:routeNames.get(record.routeId) || 'Вне маршрута',
      label:displayId(record) + ' · ' + (record.place || formatPoint(record.point)), reason,
      geometry:{type:'Point',coordinates:record.point}
    });
  }
  return items;
}

function selectRetakeItem(id) {
  retakeSelection = id;
  $('retake-item-select').value = id;
  renderRetakeTask();
}

function renderRetakeTask() {
  const item = retakeItems.find(item=>item.id === retakeSelection);
  const selected = new Set(records.retakeTask || []);
  const count = retakeItems.filter(item=>selected.has(item.id)).length;
  $('retake-item-reason').textContent = item?.reason || 'На маршрутах нет мест для пересъёмки.';
  $('retake-task-add').hidden = !item;
  $('retake-task-add').textContent = selected.has(item?.id) ? 'Убрать из задания' : 'В задание бригаде';
  $('retake-download').textContent = 'Скачать задание · ' + count;
  $('retake-download').disabled = !count;
}

function updateRetakePanel(routes) {
  $('retake-layer').setAttribute('aria-pressed',String(retakeLayerEnabled));
  $('retake-task-panel').hidden = !retakeLayerEnabled;
  retakeItems = retakeLayerEnabled ? overviewRetakeItems(routes) : [];
  if (!retakeLayerEnabled) return;
  if (!retakeItems.some(item=>item.id === retakeSelection)) retakeSelection = retakeItems[0]?.id || '';
  const picker = $('retake-item-select');
  picker.replaceChildren(...retakeItems.map(item=>new Option(item.route + ' · ' + item.label,item.id)));
  picker.value = retakeSelection;
  picker.hidden = !retakeItems.length;
  renderRetakeTask();
}

function updateRetakeOverlays() {
  const signature = JSON.stringify(retakeItems);
  if (signature === retakeOverlaySignature) return;
  for (const overlay of retakeOverlays) overlay.shape.destroy();
  retakeOverlays = retakeItems.map(item=>{
    const coords = item.geometry.coordinates;
    if (item.geometry.type === 'LineString') {
      return {item,shape:drawRouteLine(overviewMap,coords,'#ffab81',true)};
    }
    const button = document.createElement('button');
    button.className = 'retake-pin';
    button.type = 'button';
    button.textContent = '!';
    button.title = item.label + ' · ' + item.reason;
    button.setAttribute('aria-label',button.title);
    button.onclick = event => {event.stopPropagation(); selectRetakeItem(item.id);};
    const marker = new window.mapgl.HtmlMarker(overviewMap,{coordinates:coords,html:button,anchor:[10,10],
      zIndex:5,interactive:true,preventMapInteractions:true});
    return {item,shape:marker};
  });
  retakeOverlaySignature = signature;
}

function retakeAt(point) {
  return point && retakeOverlays.find(overlay=>overlay.shape.contains?.(point))?.item;
}

function downloadRetakeTask() {
  const selected = new Set(records.retakeTask || []);
  const items = retakeItems.filter(item=>selected.has(item.id));
  if (!items.length) return;
  const features = items.map(item=>({type:'Feature',geometry:item.geometry,
    properties:{route:item.route,place:item.label,reason:item.reason}}));
  const sections = items.map(item=>{
    const path = item.geometry.type === 'LineString' ? item.geometry.coordinates : [item.geometry.coordinates];
    const location = path.length > 1 ? [path[0],path.at(-1)] : path;
    return '<li><b>' + escapeHTML(item.route + ' · ' + item.label) + '</b><br>' +
      escapeHTML(item.reason) + '<br>' + location.map(formatPoint).map(escapeHTML).join(' → ') + '</li>';
  });
  const html = '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Задание на пересъёмку</title>' +
    '<style>body{font:16px system-ui;margin:2rem}li{margin:1rem 0}</style><h1>Задание на пересъёмку</h1><ol>' +
    sections.join('') + '</ol></html>';
  download(fflate.zipSync({'task.html':fflate.strToU8(html),
    'retakes.geojson':fflate.strToU8(JSON.stringify({type:'FeatureCollection',features},null,2))}),
    'application/zip','Задание-на-пересъёмку.zip');
}

function bindRetakePanel() {
  $('retake-layer').onclick = () => {retakeLayerEnabled = !retakeLayerEnabled; renderOverview();};
  $('retake-item-select').onchange = event => {
    selectRetakeItem(event.target.value);
    const geometry = retakeItems.find(item=>item.id === retakeSelection)?.geometry;
    if (overviewMap && geometry) fitDgisPoints(overviewMap,geometry.type === 'Point' ? [geometry.coordinates] : geometry.coordinates);
  };
  $('retake-task-add').onclick = () => {
    const selected = new Set(records.retakeTask || []);
    if (selected.has(retakeSelection)) selected.delete(retakeSelection);
    else selected.add(retakeSelection);
    records.retakeTask = [...selected];
    persist('Задание на пересъёмку обновлено.');
    renderRetakeTask();
  };
  $('retake-download').onclick = downloadRetakeTask;
}
