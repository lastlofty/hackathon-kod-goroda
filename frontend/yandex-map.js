'use strict';

class YandexMapError extends Error {
  constructor(code, cause) {
    super(code, {cause});
    this.code = code;
  }
}

async function loadYandexMaps(key) {
  const url = new URL('https://api-maps.yandex.ru/v3/');
  url.searchParams.set('apikey', key);
  url.searchParams.set('lang', 'ru_RU');

  const script = document.createElement('script');
  script.src = url.href;
  script.referrerPolicy = 'origin';
  try {
    return await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new YandexMapError('sdk-timeout')), 12000);
      const fail = code => {
        clearTimeout(timer);
        reject(new YandexMapError(code));
      };
      script.onerror = () => fail('sdk-request');
      script.onload = async () => {
        try {
          if (!window.ymaps3?.ready) return fail('sdk-request');
          await window.ymaps3.ready;
          clearTimeout(timer);
          resolve(window.ymaps3);
        } catch {
          fail('sdk-request');
        }
      };
      document.head.append(script);
    });
  } finally {
    script.remove();
  }
}

const inspectionBasemap = {
  'render-3d': 'off',
  style: [{
    tags: {none: ['address']},
    elements: 'label.icon',
    stylers: [{visibility: 'off'}]
  }, {
    tags: {any: ['poi', 'transit_location', 'traffic_light', 'entrance'], none: ['address']},
    elements: 'label',
    stylers: [{visibility: 'off'}]
  }, {
    tags: {any: ['transit_schema', 'transit_line']},
    stylers: [{visibility: 'off'}]
  }]
};

async function initYandexMap({container, key, route, routeColor, markerButton, onSelect, onPoint}) {
  const api = await loadYandexMaps(key);
  const {YMap, YMapDefaultSchemeLayer, YMapDefaultFeaturesLayer, YMapListener, YMapFeature, YMapMarker} = api;
  const routeLngs = route.map(([lng]) => lng);
  const routeLats = route.map(([,lat]) => lat);
  const routeBounds = [
    [Math.min(...routeLngs), Math.min(...routeLats)],
    [Math.max(...routeLngs), Math.max(...routeLats)]
  ];
  const margins = [58, 33, 69, 33];
  const zoomRange = {min: 0, max: 19};

  const createLine = (coordinates, color, width, zIndex) => new YMapFeature({
    geometry: {type: 'LineString', coordinates},
    style: {stroke: [{color, width}], zIndex}
  });

  let yandex;
  try {
    yandex = new YMap(container, {
      location: {bounds: routeBounds},
      zoomRange,
      margin: margins,
      mode: 'vector',
      theme: 'light',
      hotspotsStrategy: 'forPointerPosition'
    });

    const groundLayer = YMapDefaultSchemeLayer.defaultProps.source + ':ground';
    let tileListener;
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new YandexMapError('tiles-timeout')), 18000);
      try {
        tileListener = new YMapListener({
          onStateChanged: state => {
            if (state.getLayerState(groundLayer, 'tile', 'vector')?.tilesReady > 0) {
              clearTimeout(timer);
              resolve();
            }
          }
        });
        yandex.addChild(tileListener);
        yandex.addChild(new YMapDefaultSchemeLayer({customization: inspectionBasemap}));
        yandex.addChild(new YMapDefaultFeaturesLayer());
      } catch (error) {
        clearTimeout(timer);
        reject(error);
      }
    });
    yandex.removeChild(tileListener);
    yandex.addChild(new YMapListener({
      onClick: (entity, event) => {
        if (entity?.type !== 'marker' && event.coordinates) onPoint(event.coordinates);
      }
    }));

    yandex.addChild(createLine(route, '#ffffff', 6, 1));
    route.slice(1).forEach((point, index) => {
      yandex.addChild(createLine([route[index], point], routeColor(index), 3.5, 2));
    });
  } catch (error) {
    yandex?.destroy();
    throw error instanceof YandexMapError ? error : new YandexMapError('render', error);
  }

  const markers = new Map();
  return {
    fitRoute: (animate = true) => yandex.setLocation({bounds: routeBounds, duration: animate ? 250 : 0}),
    panTo: center => yandex.setLocation({center, zoom: yandex.zoom, duration: 250}),
    zoom: direction => yandex.setLocation({
      center: yandex.center,
      zoom: Math.min(zoomRange.max, Math.max(zoomRange.min, yandex.zoom + direction)),
      duration: 200
    }),
    setMarkers(records, selected) {
      const visible = new Set(records.map(record => record.id));
      for (const [id, entry] of markers) {
        if (!visible.has(id) && entry.shown) {
          yandex.removeChild(entry.marker);
          entry.shown = false;
        }
      }
      for (const record of records) {
        let entry = markers.get(record.id);
        if (!entry) {
          const button = markerButton(record);
          button.classList.add('yandex-marker');
          button.addEventListener('click', event => {
            event.stopPropagation();
            onSelect(record.id);
          });
          const marker = new YMapMarker({coordinates: record.point, blockEvents: true}, button);
          entry = {marker, button, shown: false, selected: null};
          markers.set(record.id, entry);
        }
        const isSelected = selected === record.id;
        if (entry.selected !== isSelected) {
          entry.button.setAttribute('aria-pressed', String(isSelected));
          entry.marker.update({zIndex: isSelected ? 10 : 0});
          entry.selected = isSelected;
        }
        if (!entry.shown) {
          yandex.addChild(entry.marker);
          entry.shown = true;
        }
      }
    }
  };
}
