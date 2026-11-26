"use strict";

const captureSurvey = (() => {
  const el = (id) => document.getElementById(id);
  const apiBase = new URL(
    document.querySelector("[name=mgts-backend-api]").content,
    location.href,
  );
  const url = (path) => new URL(path, apiBase);
  const names = {
    manhole: "Колодец",
    mock_detection: "Демонстрационное обнаружение",
    pole: "Опора",
    cable: "Кабель",
    open: "Открытый люк",
    urgent: "Срочно",
    review: "На проверку",
    normal: "Без замечаний",
    unverified: "Не обследовано",
    confirmed: "Дефект подтверждён",
    rejected: "Дефекта нет",
  };
  const label = (value) =>
    Object.hasOwn(names, value) ? names[value] : value || "—";
  const percent = (n) => (Number.isFinite(n) ? Math.round(n * 100) + "%" : "—");
  const hasPoint = (obj) =>
    Number.isFinite(obj?.lat) && Number.isFinite(obj?.lon);
  const shortName = (name) => name.split("/").at(-1);
  const verdict = (obj) => {
    if (obj.verdict === "ok") return "Дефекта нет";
    if (obj.verdict === "defect") return "Есть дефект";
    if (obj.verdict === "unknown") return "Требует проверки";
    if (obj.defect && !["none", "normal", "ok"].includes(obj.defect))
      return "Есть дефект";
    return obj.status === "normal" ? "Дефекта нет" : "Требует проверки";
  };
  const chosen = new Map();
  let inferenceMode = "disabled";

  function message(text) {
    el("status").hidden = !text;
    el("status").textContent = text;
  }
  async function api(path, options) {
    const res = await fetch(url("/api/v1" + path), {
      cache: "no-store",
      ...options,
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(
        typeof data.detail === "string"
          ? data.detail
          : "Ошибка API · " + res.status,
      );
    }
    return res.json();
  }
  let job,
    selectedFrame,
    pointGroup,
    heldFrame,
    timer,
    revision = 0;
  let observations = new Map();
  let overviewCanvas,
    overviewPending,
    overviewMarkers = [],
    overviewDataset;
  let saving = false;
  const demoReviewsKey = "mgts-demo-defect-reviews-v1";
  const priorityRank = { urgent: 0, review: 1, unverified: 2, normal: 3 };
  const activeId = () => job?.id || "new";
  const pointOf = (value) =>
    hasPoint(value) ? [value.lon, value.lat] : undefined;
  const formatDate = (value) =>
    value ? backendDate.format(new Date(value)) : "";
  const field = (name, value) =>
    "<div><dt>" +
    escapeHTML(name) +
    "</dt><dd>" +
    escapeHTML(value ?? "—") +
    "</dd></div>";
  const reviewed = (record) => record?.inspectionReview?.decision;
  const reviewLabel = (record) =>
    ({ confirmed: "Дефект подтверждён", rejected: "Дефекта нет" })[
      reviewed(record)
    ] || "Ожидает проверки";

  function convert(data) {
    const originals = new Map(
      data.inputs.filter((i) => i.kind === "image").map((i) => [i.id, i]),
    );
    const rawFrames =
      data.status === "completed"
        ? data.result.frames || []
        : [...originals.values()].map((i) => ({
            frame_id: i.name,
            media_id: i.id,
            url: i.url,
          }));
    const lookup = new Map();
    const frames = rawFrames
      .map((f) => {
        const src = originals.get(f.media_id);
        const capturedAt = f.captured_at || src?.captured_at;
        const frame = {
          id: f.frame_id,
          mediaId: f.media_id,
          name: shortName(f.frame_id),
          src: url(f.url).href,
          cameraPoint: pointOf(src) || pointOf(f),
          time: formatDate(capturedAt),
          capturedAt,
          locationSource: src?.location_source,
          boxes: [],
        };
        for (const d of f.detections || []) {
          const [cx, cy, w, h] = d.bbox;
          const box = {
            id: d.det_id,
            label: label(d.class),
            x: cx - w / 2,
            y: cy - h / 2,
            w,
            h,
            owner: d.object_id,
            score: d.score,
            inference: d.inference,
            defect: d.defect,
            defectScore: d.defect_score,
          };
          frame.boxes.push(box);
          lookup.set(box.id, { frame, box });
        }
        return frame;
      })
      .sort(
        (a, b) =>
          (Date.parse(a.capturedAt) || Infinity) -
          (Date.parse(b.capturedAt) || Infinity),
      );
    const objects = (data.result.objects || []).map((o) => {
      const best = lookup.get(o.best_det_id);
      const decision = data.reviews[o.object_id];
      const rawPriority =
        { high: "urgent", medium: "review", low: "normal" }[o.status] ||
        o.status;
      const priority = Object.hasOwn(priorities, rawPriority)
        ? rawPriority
        : "unverified";
      return {
        id: o.object_id,
        type: label(o.class),
        frame: best?.frame.id,
        box: o.best_det_id,
        point: best?.frame.cameraPoint,
        assetPoint: pointOf(o),
        pointKind: "observation",
        priority,
        issue: o.defect ? label(o.defect) : undefined,
        defect: o.defect,
        verdict: verdict(o),
        confidence: Number.isFinite(o.defect_score)
          ? Math.round(o.defect_score * 100)
          : null,
        evidence: o.observations,
        inspectionReview: decision,
      };
    });
    objects.sort(
      (a, b) =>
        priorityRank[a.priority] - priorityRank[b.priority] ||
        (b.confidence ?? -1) - (a.confidence ?? -1) ||
        a.id.localeCompare(b.id),
    );
    return { lookup, frames, objects };
  }

  async function previousData() {
    const response = await fetch(
      document.querySelector("[name=mgts-inspection-data]").content,
    );
    if (!response.ok)
      throw Error("Не удалось загрузить сохранённое обследование");
    const old = mergeInspection(await response.json(), savedInspection());
    let decisions = {};
    try {
      decisions = JSON.parse(localStorage.getItem(demoReviewsKey)) || {};
    } catch {}
    const frames = old.frames.map((f) => ({
      ...f,
      boxes: f.boxes.map((box) => ({ ...box })),
    }));
    const lookup = new Map();
    const objects = old.objects.map((record) => {
      const frame = frames.find((f) => f.id === record.frame);
      const box = frame?.boxes.find((b) => b.id === record.box);
      const id = box && frame.id + "/" + box.id;
      if (box) {
        box.owner = record.id;
        lookup.set(id, { frame, box });
      }
      return {
        ...record,
        point: frame?.cameraPoint,
        assetPoint: record.point,
        pointKind: "observation",
        evidence: id ? [id] : [],
        verdict: record.issue ? record.issue : "Требует проверки",
        inspectionReview: decisions[record.id] || record.inspectionReview,
      };
    });
    return { lookup, frames, objects, changes: old.changes || [] };
  }

  function availableFrames() {
    if (state.filter === "all") return records.frames;
    const ids = new Set(
      visibleObjects().flatMap((o) => [
        o.frame,
        ...o.evidence.map((id) => observations.get(id)?.frame.id),
      ]),
    );
    return records.frames.filter((f) => ids.has(f.id));
  }
  function mapPoints() {
    const groups = new Map();
    for (const frame of availableFrames()) {
      if (!isValidPoint(frame.cameraPoint)) continue;
      const id = frame.cameraPoint.map((n) => n.toFixed(7)).join(",");
      if (!groups.has(id))
        groups.set(id, {
          id,
          point: frame.cameraPoint,
          type: frame.name,
          displayId: frame.name,
          frames: [],
        });
      groups.get(id).frames.push(frame);
    }
    for (const group of groups.values())
      if (group.frames.length > 1)
        group.type = "Кадров в точке: " + group.frames.length;
    return [...groups.values()];
  }
  function markMap() {
    const groups = mapPoints();
    const current = groups.find((g) =>
      g.frames.some((f) => f.id === selectedFrame),
    );
    inspectionMap?.setMarkers(groups, current?.id);
  }
  function fit() {
    inspectionMap?.fitPoints(mapPoints().map((g) => g.point));
  }
  function openPoint(id) {
    const group = mapPoints().find((g) => g.id === id);
    if (!group) return;
    pointGroup = group.frames.length > 1 ? id : null;
    selectFrame(group.frames[0].id, false, true);
  }
  function selectFrame(id, pan = false, fromPoint = false) {
    const frame = frameById(id);
    if (!frame) return;
    if (!fromPoint) pointGroup = null;
    heldFrame = true;
    state.selected = null;
    selectedFrame = id;
    state.overlay = true;
    if (state.view !== "map") switchView("map");
    renderCard();
    if (pan && isValidPoint(frame.cameraPoint))
      inspectionMap?.panTo(frame.cameraPoint);
  }
  function selectObject(id, pan = false) {
    const obj = records.objects.find((o) => o.id === id);
    if (!obj) return;
    heldFrame = false;
    pointGroup = null;
    state.selected = id;
    selectedFrame = obj.frame;
    state.overlay = true;
    if (state.view !== "map") switchView("map");
    renderCard();
    if (pan && isValidPoint(obj.point)) inspectionMap?.panTo(obj.point);
  }
  function step(direction) {
    const objects = visibleObjects();
    if (state.selected && objects.length) {
      const i = objects.findIndex((o) => o.id === state.selected);
      selectObject(
        objects[(i + direction + objects.length) % objects.length].id,
        true,
      );
    } else {
      const frames = availableFrames();
      if (!frames.length) return;
      const i = frames.findIndex((f) => f.id === selectedFrame);
      selectFrame(
        frames[(i + direction + frames.length) % frames.length].id,
        true,
      );
    }
  }
  function renderDeck() {
    const frames = availableFrames();
    el("deck-title").textContent = "Кадры съёмки";
    el("route-count").textContent = frames.length
      ? "Кадров: " + frames.length
      : "";
    el("route-frames").innerHTML =
      frames
        .map(
          (f) =>
            '<button class="film-shot" data-capture="' +
            escapeHTML(f.id) +
            '" aria-pressed="' +
            (f.id === selectedFrame) +
            '" title="' +
            escapeHTML(f.name) +
            '"><img loading="lazy" src="' +
            escapeHTML(f.src) +
            '" alt=""><span>' +
            escapeHTML(f.name) +
            "</span></button>",
        )
        .join("") || '<p class="subtle">Нет загруженных кадров.</p>';
    el("route-report").hidden = !records.objects.length || state.view !== "map";
  }
  function renderCard() {
    const objects = visibleObjects(),
      frames = availableFrames();
    let obj = objects.find((o) => o.id === state.selected);
    if (state.selected && !obj) {
      obj = objects[0];
      state.selected = obj?.id;
      selectedFrame = obj?.frame;
    }
    let frame = frames.find((f) => f.id === selectedFrame);
    if (!obj && !frame) {
      frame = frames[0];
      selectedFrame = frame?.id;
    }
    const index = obj ? objects.indexOf(obj) : frames.indexOf(frame);
    const count = obj ? objects.length : frames.length;
    el("position").textContent = index + 1 + " / " + count;
    document
      .querySelectorAll('[data-action="prev"],[data-action="next"]')
      .forEach((b) => (b.disabled = count < 2));
    for (const item of el("route-frames").children)
      if (item.dataset.capture)
        item.setAttribute(
          "aria-pressed",
          String(item.dataset.capture === selectedFrame),
        );
    markMap();
    const panel = el("inspector-content");
    if (!frame && !obj) {
      panel.innerHTML =
        '<p class="empty">' +
        (state.filter !== "all"
          ? "Нет объектов по выбранному статусу."
          : job && job.status !== "completed"
            ? "Кадры появятся после обработки съёмки."
            : "Выберите съёмку или загрузите файлы.") +
        "</p>";
      return;
    }
    const frameBoxes = frame?.boxes || [];
    const objectsHere = [
      ...new Set(frameBoxes.map((b) => b.owner).filter(Boolean)),
    ];
    const group = pointGroup && mapPoints().find((g) => g.id === pointGroup);
    const options = (items, current) =>
      items
        .map(
          (f) =>
            '<option value="' +
            escapeHTML(f.id) +
            '" ' +
            (f.id === current ? "selected" : "") +
            ">" +
            escapeHTML(f.name) +
            "</option>",
        )
        .join("");
    const evidence = (obj?.evidence || [])
      .map((id) => observations.get(id))
      .filter(Boolean);
    const shots = [
      ...new Map(evidence.map((e) => [e.frame.id, e.frame])).values(),
    ];
    const activeBox =
      evidence.find((e) => e.frame === frame && e.box.id === obj?.box)?.box ||
      evidence.find((e) => e.frame === frame)?.box;
    const frameChoice = group
      ? '<label>Кадры в точке <select id="point-frames">' +
        options(group.frames, selectedFrame) +
        "</select></label>"
      : shots.length > 1
        ? '<label>Кадр <select id="evidence-frames">' +
          options(shots, selectedFrame) +
          "</select></label>"
        : "";
    const figure = frame
      ? '<div class="frame-panel"><figure class="frame"><div class="frame-bounds"><img src="' +
        escapeHTML(frame.src) +
        '" alt="' +
        escapeHTML(frame.name) +
        '">' +
        (state.overlay
          ? frameBoxes.map((b) => boxHTML(b, b === activeBox)).join("")
          : "") +
        '</div></figure><div class="frame-tools"><div class="frame-toggle"><button data-action="original" aria-pressed="' +
        !state.overlay +
        '">Исходник</button><button data-action="overlay" aria-pressed="' +
        state.overlay +
        '">Результат модели</button></div>' +
        frameChoice +
        "</div></div>"
      : "";
    let review = "";
    if (obj) {
      review =
        '<section class="review-controls"><div class="review-heading"><h3>Проверка дефекта</h3><span>' +
        escapeHTML(reviewLabel(obj)) +
        '</span></div><div class="review-buttons"><label class="filter-label">Тип <input id="defect" maxlength="256" value="' +
        escapeHTML(
          reviewed(obj) === "confirmed"
            ? obj.inspectionReview.defect
            : obj.defect || "",
        ) +
        '"></label><button class="button confirm" data-survey-decision="confirmed">Подтвердить</button><button class="button" data-survey-decision="rejected">Дефекта нет</button></div></section>';
    } else if (frame) {
      review =
        '<section class="review-controls"><div class="review-heading"><h3>Результаты на кадре</h3></div><div class="review-buttons">' +
        (objectsHere
          .map((id) => {
            const o = records.objects.find((o) => o.id === id);
            return o
              ? '<button class="button" data-record="' +
                  escapeHTML(id) +
                  '">' +
                  escapeHTML(
                    o.type + " · " + (reviewed(o) ? reviewLabel(o) : o.verdict),
                  ) +
                  "</button>"
              : "";
          })
          .join("") ||
          '<span class="subtle">' +
            (job?.status === "completed"
              ? "Объекты на кадре не обнаружены."
              : "Ожидаем результат обработки.") +
            "</span>") +
        "</div></section>";
    }
    panel.innerHTML =
      '<div class="record-head"><div class="record-id"><span class="mono">' +
      escapeHTML(obj ? displayId(obj) : frame.name) +
      "</span>" +
      (obj ? status(obj) : "") +
      "</div><h2>" +
      escapeHTML(obj ? obj.type : "Кадр съёмки") +
      "</h2></div>" +
      figure +
      review +
      '<div class="record-data"><dl>' +
      (obj
        ? field("Вердикт модели", obj.verdict) +
          field("Тип дефекта модели", obj.issue) +
          field(
            "Уверенность в дефекте",
            obj.confidence == null ? "—" : obj.confidence + "%",
          ) +
          field("Кадров с объектом", shots.length)
        : "") +
      '<div><dt>Адрес точки</dt><dd id="point-address"></dd></div>' +
      field(
        "Место съёмки",
        isValidPoint(frame?.cameraPoint)
          ? formatPoint(frame.cameraPoint)
          : "Без геометки",
      ) +
      (isValidPoint(obj?.assetPoint)
        ? field("Координаты объекта", formatPoint(obj.assetPoint))
        : "") +
      (frame ? field("Съёмка", frame.time || "—") : "") +
      "</dl>" +
      (activeBox
        ? "<details><summary>Сведения о детекции</summary><dl>" +
          (activeBox.inference?.model_name ? field("Модель", [activeBox.inference.model_name, activeBox.inference.model_version].filter(Boolean).join(" · ")) : "") +
          (activeBox.inference?.label ? field("Метка", activeBox.inference.label) : "") +
          (activeBox.inference?.severity != null ? field("Оценка опасности", activeBox.inference.severity) : "") +
          (activeBox.inference?.recommendation ? field("Рекомендация", activeBox.inference.recommendation) : "") +
          field("Уверенность в обнаружении", percent(activeBox.score)) +
          field("Дефект на кадре", label(activeBox.defect)) +
          field(
            "Уверенность в дефекте на кадре",
            percent(activeBox.defectScore),
          ) +
          "</dl></details>"
        : "") +
      '<div class="record-foot">' +
      escapeHTML(frame?.name || "") +
      (frame && obj?.frame === frame.id && job?.status === "completed"
        ? " · Лучший кадр"
        : "") +
      (obj
        ? ' <button class="table-link" data-action="share-record">Скопировать ссылку</button>'
        : "") +
      "</div></div>";
    showPointAddress(
      { point: frame?.cameraPoint, place: obj?.place },
      el("point-address"),
    );
    el("point-frames")?.addEventListener("change", (e) =>
      selectFrame(e.target.value, false, true),
    );
    el("evidence-frames")?.addEventListener("change", (e) => {
      selectedFrame = e.target.value;
      renderCard();
      const p = frameById(selectedFrame)?.cameraPoint;
      if (isValidPoint(p)) inspectionMap?.panTo(p);
    });
  }
  function renderHistory() {
    const decisions = records.objects
      .filter((o) => ["confirmed", "rejected"].includes(reviewed(o)))
      .map(
        (o) =>
          '<tr><td><button class="table-link" data-record="' +
          escapeHTML(o.id) +
          '">' +
          escapeHTML(displayId(o)) +
          "</button></td><td>" +
          escapeHTML(reviewLabel(o)) +
          "</td><td>" +
          escapeHTML(o.inspectionReview.defect || "—") +
          "</td></tr>",
      )
      .join("");
    const decisionsTable = decisions
      ? '<section class="change-log"><h2>Решения оператора</h2><div class="table-shell"><table><thead><tr><th>Объект</th><th>Решение</th><th>Тип дефекта</th></tr></thead><tbody>' +
        decisions +
        "</tbody></table></div></section>"
      : "";
    el("list-view").innerHTML =
      (records.changes?.length ? historyLog() : "") +
      decisionsTable +
      '<h2 class="history-frames">Снимки</h2><div class="table-shell"><table><thead><tr><th>Снимок</th><th>Съёмка</th><th>Обнаружения</th><th>Место съёмки</th><th>Просмотр</th></tr></thead><tbody>' +
      records.frames
        .map(
          (f) =>
            '<tr><td><span class="file-cell"><img src="' +
            escapeHTML(f.src) +
            '" alt="">' +
            escapeHTML(f.name) +
            "</span></td><td>" +
            escapeHTML(f.time || "—") +
            "</td><td>" +
            f.boxes.length +
            "</td><td>" +
            formatPoint(f.cameraPoint) +
            '</td><td><button class="table-link" data-capture="' +
            escapeHTML(f.id) +
            '">Открыть кадр ↗</button></td></tr>',
        )
        .join("") +
      "</tbody></table></div>";
  }
  function report() {
    const filtered = el("problems-only").checked
      ? records.objects.filter(
          (o) =>
            reviewed(o) !== "rejected" &&
            (o.priority === "urgent" ||
              o.priority === "review" ||
              reviewed(o) === "confirmed"),
        )
      : records.objects;
    el("report-body").innerHTML =
      "<h2>" +
      escapeHTML(job?.name || "Обследование") +
      "</h2><p>Кадров: " +
      records.frames.length +
      " · Объектов: " +
      filtered.length +
      "</p>" +
      filtered
        .map((o) => {
          const frame = frameById(o.frame);
          const detection = frame?.boxes.find((b) => b.id === o.box);
          const photo = frame
            ? '<figure class="frame"><div class="frame-bounds"><img src="' +
              escapeHTML(frame.src) +
              '" alt="' +
              escapeHTML(frame.name) +
              '">' +
              (detection ? boxHTML(detection, true) : "") +
              "</div></figure>"
            : "";
          return (
            "<article>" +
            photo +
            "<div><strong>" +
            escapeHTML(o.type + " · " + displayId(o)) +
            "</strong><p>" +
            escapeHTML(
              [o.verdict, o.issue, reviewLabel(o), o.inspectionReview?.defect]
                .filter(Boolean)
                .join(" · "),
            ) +
            "</p><p>" +
            escapeHTML(o.place || formatPoint(o.assetPoint || o.point)) +
            "</p></div></article>"
          );
        })
        .join("");
    if (!el("report-dialog").open) el("report-dialog").showModal();
  }
  function overview() {
    const root = el("overview-content");
    if (!el("capture-overview-map")) {
      root.innerHTML =
        '<div class="overview-head"><h1>Обзор обследований</h1><dl class="overview-metrics"></dl></div><div class="overview-grid"><section class="overview-network"><div class="overview-section-head"><h2>Карта съёмки</h2></div><div class="overview-plot"><div id="capture-overview-map"></div><div id="overview-map-notice" hidden><span></span> <button class="button">Подключить карту</button></div></div></section><div class="overview-side"><section><h2>Состояние объектов</h2><div class="overview-distribution"></div><dl class="overview-statuses"></dl></section><section><div class="overview-section-head"><h2>Следующие объекты для проверки</h2></div><ul class="overview-queue"></ul></section></div></div>';
    }
    const counts = Object.fromEntries(
      Object.keys(priorities).map((k) => [
        k,
        records.objects.filter((o) => o.priority === k).length,
      ]),
    );
    root.querySelector(".overview-metrics").innerHTML = [
      ["Кадры", records.frames.length],
      ["Объекты", records.objects.length],
      ["Срочно", counts.urgent],
    ]
      .map(([k, v]) => "<div><dt>" + k + "</dt><dd>" + v + "</dd></div>")
      .join("");
    root.querySelector(".overview-statuses").innerHTML = Object.keys(counts)
      .map(
        (k) =>
          '<div><i style="background:' +
          sectionColors[k] +
          '"></i><dt>' +
          priorities[k] +
          "</dt><dd>" +
          counts[k] +
          "</dd></div>",
      )
      .join("");
    root.querySelector(".overview-distribution").innerHTML = Object.keys(counts)
      .filter((k) => counts[k])
      .map(
        (k) =>
          '<i style="background:' +
          sectionColors[k] +
          ";flex:" +
          counts[k] +
          '"></i>',
      )
      .join("");
    root.querySelector(".overview-queue").innerHTML =
      records.objects
        .filter((o) => !reviewed(o))
        .slice(0, 5)
        .map(
          (o) =>
            '<li><button data-record="' +
            escapeHTML(o.id) +
            '">' +
            (frameById(o.frame)
              ? '<img src="' + escapeHTML(frameById(o.frame).src) + '" alt="">'
              : "") +
            "<span><strong>" +
            escapeHTML(o.type) +
            "</strong><small>" +
            escapeHTML(displayId(o)) +
            "</small></span>" +
            status(o) +
            "</button></li>",
        )
        .join("") || '<li class="subtle">Очередь пуста.</li>';
    updateOverviewPoints();
  }
  async function updateOverviewPoints() {
    if (overviewPending) return;
    const notice = el("overview-map-notice"),
      key = configuredMapKey();
    if (!key) {
      notice.hidden = false;
      notice.querySelector("span").textContent =
        "Подключите карту, чтобы увидеть места съёмки.";
      notice.querySelector("button").onclick = openMapSettings;
      return;
    }
    if (!overviewCanvas) {
      overviewPending = true;
      try {
        overviewCanvas = await createDgisStreetMap(
          await loadDgisSdk(),
          el("capture-overview-map"),
          key,
          [37.61, 55.76],
          13,
          { zoomControl: true, enableTwoFingerDragging: true },
        );
        notice.hidden = true;
      } catch {
        notice.hidden = false;
        notice.querySelector("span").textContent =
          "Не удалось загрузить карту.";
        notice.querySelector("button").onclick = openMapSettings;
        return;
      } finally {
        overviewPending = false;
      }
    }
    if (state.view !== "overview") return;
    const groups = mapPoints(),
      signature = JSON.stringify([activeId(), groups.map((g) => g.id)]);
    if (signature === overviewDataset) return;
    overviewDataset = signature;
    overviewMarkers.forEach((m) => m.destroy());
    overviewMarkers = groups.map((g) => {
      const button = createMarkerButton(g);
      button.onclick = () => {
        switchView("map");
        openPoint(g.id);
        inspectionMap?.panTo(g.point);
      };
      return new window.mapgl.HtmlMarker(overviewCanvas, {
        coordinates: g.point,
        html: button,
        anchor: [7, 7],
        interactive: true,
        preventMapInteractions: true,
      });
    });
    fitDgisPoints(
      overviewCanvas,
      groups.map((g) => g.point),
      0,
    );
  }

  async function decide(decision) {
    if (saving) return;
    const target = job,
      obj = records.objects.find((o) => o.id === state.selected);
    if (!target || !obj) return;
    const defect = decision === "confirmed" ? el("defect").value.trim() : null;
    if (decision === "confirmed" && !defect) {
      el("defect").focus();
      announce("Укажите тип дефекта.");
      return;
    }
    saving = true;
    try {
      const payload = { object_id: obj.id, decision, defect };
      if (target.id === "demo") {
        let all = {};
        try {
          all = JSON.parse(localStorage.getItem(demoReviewsKey)) || {};
        } catch {}
        all[obj.id] = payload;
        localStorage.setItem(demoReviewsKey, JSON.stringify(all));
      } else {
        await api("/surveys/" + target.id + "/reviews", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
      }
      if (target === job) {
        obj.inspectionReview = payload;
        renderTotals();
        renderCard();
        if (state.view !== "map") renderList();
        announce("Решение сохранено.");
      }
    } catch (e) {
      announce(e.message);
    } finally {
      saving = false;
    }
  }

  function syncProgress() {
    if (!job || job.status === "completed") {
      message(job?.inference_mode === "mock" ? "Демораспознавание · тестовые рамки" : "");
      return;
    }
    message(
      job.status === "failed"
        ? "Ошибка обработки: " + ({
            "CV adapter is not configured": "адаптер модели ещё не настроен",
            "Triton inference failed": "сервер Triton не вернул результат",
            "Invalid image or model output": "некорректное изображение или ответ модели",
          }[job.error] || job.error || "без описания")
        : job.status === "queued"
          ? "Съёмка загружена. Ожидаем запуск обработки."
          : "Идёт обработка" +
            (Number.isFinite(job.progress) ? " · " + job.progress + "%" : "…"),
    );
  }
  function applyData(data, dataset, completedNow = false) {
    const previousFrame = frameById(selectedFrame);
    const previousMedia = previousFrame?.mediaId;
    job = data;
    const { lookup, ...content } = dataset;
    observations = lookup || new Map();
    records = {
      ...content,
      schemaVersion: 1,
      datasetId: activeId(),
      route: [],
      routes: [],
    };
    if (heldFrame && previousMedia)
      selectedFrame =
        records.frames.find((f) => f.mediaId === previousMedia)?.id ||
        selectedFrame;
    if (!heldFrame || !frameById(selectedFrame)) {
      state.selected = records.objects[0]?.id;
      selectedFrame = records.objects[0]?.frame || records.frames[0]?.id;
    }
    if (completedNow && !heldFrame && state.view === "map")
      switchView("registry");
    syncProgress();
    renderTotals();
    renderDeck();
    renderCard();
    setMapStatus();
    if (state.view !== "map") renderList();
    el("survey-export").disabled = !records.objects.length;
  }
  async function poll(id, seq) {
    try {
      const data = await api("/surveys/" + encodeURIComponent(id));
      if (seq !== revision) return;
      if (data.status === "completed") {
        applyData(data, convert(data), true);
        fit();
        return;
      }
      job = data;
      syncProgress();
      if (data.status === "failed") {
        renderCard();
        return;
      }
    } catch (e) {
      if (seq !== revision) return;
      message(e.message);
    }
    timer = setTimeout(() => poll(id, seq), 2200);
  }
  async function selectJob(id, afterUpload = false, remember = true) {
    const seq = ++revision;
    clearTimeout(timer);
    state.selected = null;
    state.filter = el("priority-filter").value = "all";
    selectedClass = "";
    selectedFrame = null;
    heldFrame = false;
    pointGroup = null;
    job = null;
    queueOnly = false;
    applyData(null, { frames: [], objects: [] });
    if (remember) {
      const next = new URL(location.href);
      next.searchParams.set("survey", id);
      next.hash = "";
      history.replaceState(null, "", next);
    }
    el("job-select").value = id;
    try {
      if (id === "new") {
        if (state.view !== "map") switchView("map");
        return;
      }
      if (id === "demo") {
        const dataset = await previousData();
        if (seq !== revision) return;
        applyData(
          { id, name: "Сохранённая съёмка", status: "completed" },
          dataset,
        );
      } else {
        const data = await api("/surveys/" + encodeURIComponent(id));
        if (seq !== revision) return;
        applyData(data, convert(data), afterUpload);
        if (!["completed", "failed"].includes(data.status)) {
          if (state.view !== "map") switchView("map");
          timer = setTimeout(() => poll(id, seq), 2200);
        }
      }
      fit();
    } catch (e) {
      if (seq === revision) message(e.message);
    }
  }
  async function listJobs(preferred, afterUpload = false) {
    let jobs = [];
    let error;
    try {
      jobs = await api("/surveys");
    } catch (e) {
      error = e;
    }
    const picker = el("job-select");
    picker.replaceChildren(
      new Option("Новое обследование", "new"),
      ...jobs.map(
        (j) => new Option((j.inference_mode === "mock" ? "Демо · " : "") + j.name + " · " + formatDate(j.created_at), j.id),
      ),
      new Option("Демосъёмка · Москва", "demo"),
    );
    const requested =
      preferred || new URL(location.href).searchParams.get("survey");
    const selected =
      requested ||
      jobs[0]?.id ||
      (savedInspection() || location.hash.includes("point=") ? "demo" : "new");
    if (![...picker.options].some((o) => o.value === selected)) {
      await selectJob("new", false, false);
      message("Обследование по этой ссылке недоступно.");
      return;
    }
    await selectJob(selected, afterUpload, afterUpload);
    if (error) message("Список обследований недоступен · " + error.message);
  }

  async function start() {
    el("upload").disabled = false;
    el("report-title").textContent = el("route-report").textContent =
      "Отчёт по обследованию";
    el("problems-only").onchange = report;
    for (const id of [
      "route-picker",
      "section-toggle",
      "retake-toggle",
      "live-toggle",
      "pin-button",
    ])
      el(id).hidden = true;
    document.querySelector('[data-action="route-atlas"]').hidden = true;
    document.querySelector('[data-action="route-geojson"]').hidden = true;
    el("priority-filter").querySelector('[value="retake"]').remove();
    el("job-select").onchange = (e) => selectJob(e.target.value);
    document.addEventListener("click", (e) => {
      const control = e.target.closest("button");
      if (!control) return;
      if (control.dataset.capture) {
        if (
          state.filter !== "all" &&
          !availableFrames().some((f) => f.id === control.dataset.capture)
        )
          state.filter = el("priority-filter").value = "all";
        selectFrame(control.dataset.capture, true);
      }
      if (control.dataset.surveyDecision)
        decide(control.dataset.surveyDecision);
    });
    api("/surveys/inference-config")
      .then(({mode}) => {
        inferenceMode = mode;
        updateInferenceOption();
      })
      .catch(() => {});
    const keyReady = configuredMapKey()
      ? Promise.resolve()
      : api("/surveys/map-config", { signal: AbortSignal.timeout(4000) })
          .then((c) => {
            if (c.browser_key)
              document.querySelector("[name=mgts-dgis-api-key]").content =
                c.browser_key;
          })
          .catch(() => {});
    const loading = listJobs();
    await keyReady;
    startMap();
    await loading;
    const params = new URL(location.href).searchParams;
    if (params.get("view") === "overview") switchView("overview");
    if (location.hash.includes("point=")) openRecordLink();
  }
  function updateInferenceOption() {
    const paths = [...chosen.keys()];
    const eligible = paths.some(path => /\.(jpe?g|png|webp)$/i.test(path)) &&
      paths.every(path => /\.(jpe?g|png|webp|gpx)$/i.test(path) || /(?:^|\/)coordinates\.json$/i.test(path));
    const available = ["mock", "triton"].includes(inferenceMode) && eligible;
    const option = el("inference-option");
    if (available && option.hidden) el("run-detection").checked = inferenceMode === "triton";
    option.hidden = !available;
    if (!available) el("run-detection").checked = false;
    el("inference-label").textContent = inferenceMode === "mock"
      ? "Демораспознавание фото (тестовые рамки)"
      : "Распознать фотографии через Triton";
  }
  function selectFiles(input) {
    for (const f of input.files) {
      const path = f.webkitRelativePath || f.name;
      if (/\.(jpe?g|png|webp|mp4|mov|webm|gpx|yaml|yml|json|txt)$/i.test(path))
        chosen.set(path, f);
    }
    input.value = "";
    updateInferenceOption();
    el("chosen").textContent = "Выбрано файлов: " + chosen.size;
    el("submit").disabled = !chosen.size;
  }
  function openUpload() {
    chosen.clear();
    updateInferenceOption();
    el("chosen").textContent = "";
    el("submit").disabled = true;
    el("import-error").textContent = "";
    el("import").showModal();
  }
  for (const [button, input] of [
    ["pick-files", "files"],
    ["pick-folder", "folder"],
  ]) {
    el(button).onclick = () => el(input).click();
    el(input).onchange = () => selectFiles(el(input));
  }
  el("cancel").onclick = () => el("import").close();
  el("submit").onclick = async () => {
    const form = new FormData(),
      first = chosen.keys().next().value;
    if (!first) return;
    form.set("name", first.split("/")[0]);
    if (el("run-detection").checked) form.set("inference_mode", inferenceMode);
    for (const [path, file] of chosen) form.append("files", file, path);
    const controls = ["submit", "pick-files", "pick-folder", "cancel", "run-detection"];
    controls.forEach((k) => (el(k).disabled = true));
    const progress = el("upload-progress");
    progress.hidden = false;
    progress.max = 100;
    progress.value = 0;
    el("import-error").textContent = "";
    try {
      const data = await new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", url("/api/v1/surveys"));
        xhr.responseType = "json";
        xhr.upload.onprogress = (e) => {
          if (e.lengthComputable) progress.value = (100 * e.loaded) / e.total;
        };
        xhr.upload.onload = () => {
          progress.removeAttribute("value");
          el("chosen").textContent = "Сервер принимает пакет…";
        };
        xhr.onerror = () => reject(new Error("Соединение с API прервано"));
        xhr.onload = () =>
          xhr.status === 201
            ? resolve(xhr.response)
            : reject(
                new Error(
                  typeof xhr.response?.detail === "string"
                    ? xhr.response.detail
                    : "Ошибка загрузки · " + xhr.status,
                ),
              );
        xhr.send(form);
      });
      el("import").close();
      await listJobs(data.id, true);
    } catch (e) {
      el("import-error").textContent = e.message;
      message(e.message);
    } finally {
      controls.forEach((k) => (el(k).disabled = false));
      progress.hidden = true;
    }
  };
  el("import").oncancel = (e) => {
    if (el("cancel").disabled) e.preventDefault();
  };
  return {
    start,
    selectObject,
    selectFrame,
    openPoint,
    markMap,
    mapPoints,
    fit,
    renderCard,
    renderDeck,
    renderHistory,
    overview,
    report,
    step,
    openUpload,
  };
})();
