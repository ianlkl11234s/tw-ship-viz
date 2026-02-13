/**
 * 軌跡查詢控制模組
 * 支援點選單船和矩形圈選多船。
 */
import { VESSEL_TYPE_NAMES } from '../utils/constants.js';

let map = null;
let onQueryResult = null;
let onQueryShipsLoad = null;
let queryTool = 'click';
let isSelecting = false;
let selectionStart = null;

export function initQueryControls(opts) {
  map = opts.map;
  onQueryResult = opts.onQueryResult;
  onQueryShipsLoad = opts.onQueryShipsLoad;

  setupToolButtons();
}

export function enableQueryMode() {
  const toolbar = document.getElementById('queryToolbar');
  const panel = document.getElementById('queryPanel');
  if (toolbar) toolbar.style.display = 'flex';
  if (panel) panel.style.display = 'block';
  loadQueryShips();
}

export function disableQueryMode() {
  const toolbar = document.getElementById('queryToolbar');
  const panel = document.getElementById('queryPanel');
  if (toolbar) toolbar.style.display = 'none';
  if (panel) panel.style.display = 'none';
}

/**
 * deck.gl picking 回調（從 main.js 呼叫）。
 */
export function handlePick(info) {
  if (queryTool !== 'click' || !info.object) return;
  const { mmsi } = info.object;
  if (mmsi) queryShipTrack(mmsi);
}

// === 工具按鈕 ===
function setupToolButtons() {
  const toolbar = document.getElementById('queryToolbar');
  if (!toolbar) return;

  toolbar.querySelectorAll('.tool-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tool = btn.dataset.tool;

      if (tool === 'clear') {
        clearQueryResults();
        return;
      }

      queryTool = tool;
      toolbar.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      if (tool === 'rect') {
        setupRectSelection();
      } else {
        teardownRectSelection();
      }
    });
  });
}

// === 載入最新船舶位置 ===
async function loadQueryShips() {
  try {
    const res = await fetch('/api/ships/latest');
    if (!res.ok) return;
    const data = await res.json();
    const ships = data.map(s => ({
      position: [s.lon, s.lat],
      mmsi: s.mmsi,
      vesselType: s.vessel_type,
    }));
    if (onQueryShipsLoad) onQueryShipsLoad(ships);
  } catch { /* API 不可用 */ }
}

// === 單船軌跡查詢 ===
async function queryShipTrack(mmsi, days = 7) {
  try {
    const res = await fetch(`/api/ship/${mmsi}/track?days=${days}`);
    if (!res.ok) return;
    const data = await res.json();

    const result = {
      mmsi,
      vesselType: data.vessel_type || 0,
      path: data.track.map(p => [p.lon, p.lat]),
      color: [0, 119, 182],
      trackPoints: data.track.length,
    };

    if (onQueryResult) onQueryResult([result]);
    addResultCard(result);
    fitBounds([result]);
  } catch (err) {
    console.error('[query] 查詢失敗:', err);
  }
}

// === 矩形圈選 ===
let rectDiv = null;

function setupRectSelection() {
  const container = map.getContainer();
  container.style.cursor = 'crosshair';

  container.addEventListener('mousedown', onRectStart);
  document.addEventListener('mousemove', onRectMove);
  document.addEventListener('mouseup', onRectEnd);
}

function teardownRectSelection() {
  const container = map.getContainer();
  container.style.cursor = '';
  container.removeEventListener('mousedown', onRectStart);
  document.removeEventListener('mousemove', onRectMove);
  document.removeEventListener('mouseup', onRectEnd);
  hideSelectionRect();
}

function onRectStart(e) {
  if (queryTool !== 'rect') return;
  isSelecting = true;
  selectionStart = { x: e.clientX, y: e.clientY };
  showSelectionRect(selectionStart.x, selectionStart.y, 0, 0);
}

function onRectMove(e) {
  if (!isSelecting || !selectionStart) return;
  const x = Math.min(selectionStart.x, e.clientX);
  const y = Math.min(selectionStart.y, e.clientY);
  const w = Math.abs(e.clientX - selectionStart.x);
  const h = Math.abs(e.clientY - selectionStart.y);
  showSelectionRect(x, y, w, h);
}

async function onRectEnd(e) {
  if (!isSelecting || !selectionStart) return;
  isSelecting = false;
  hideSelectionRect();

  const x1 = Math.min(selectionStart.x, e.clientX);
  const y1 = Math.min(selectionStart.y, e.clientY);
  const x2 = Math.max(selectionStart.x, e.clientX);
  const y2 = Math.max(selectionStart.y, e.clientY);

  if (x2 - x1 < 10 || y2 - y1 < 10) return;

  const sw = map.unproject([x1, y2]);
  const ne = map.unproject([x2, y1]);

  try {
    const res = await fetch('/api/ships/tracks?days=7', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        min_lon: sw.lng, max_lon: ne.lng,
        min_lat: sw.lat, max_lat: ne.lat,
      }),
    });
    if (!res.ok) return;
    const data = await res.json();

    const results = data.map((ship, i) => {
      const hue = (i * 360 / Math.max(data.length, 1)) % 360;
      const rgb = hslToRgb(hue, 70, 50);
      return {
        mmsi: ship.mmsi,
        vesselType: ship.vessel_type || 0,
        path: ship.track.map(p => [p.lon, p.lat]),
        color: rgb,
        trackPoints: ship.track.length,
      };
    });

    if (onQueryResult) onQueryResult(results);
    clearResultCards();
    results.forEach(addResultCard);
    if (results.length > 0) fitBounds(results);
  } catch (err) {
    console.error('[query] 圈選查詢失敗:', err);
  }
}

// === 選取框 UI ===
function showSelectionRect(x, y, w, h) {
  if (!rectDiv) {
    rectDiv = document.querySelector('.selection-rect');
    if (!rectDiv) {
      rectDiv = document.createElement('div');
      rectDiv.className = 'selection-rect';
      document.body.appendChild(rectDiv);
    }
  }
  rectDiv.style.display = 'block';
  rectDiv.style.left = x + 'px';
  rectDiv.style.top = y + 'px';
  rectDiv.style.width = w + 'px';
  rectDiv.style.height = h + 'px';
}

function hideSelectionRect() {
  if (rectDiv) rectDiv.style.display = 'none';
}

// === 結果卡片 ===
function addResultCard(result) {
  const body = document.getElementById('queryPanelBody');
  if (!body) return;

  const card = document.createElement('div');
  card.style.cssText = 'padding:8px;margin:4px;border-radius:8px;background:rgba(0,0,0,0.04);font-size:12px;';
  card.innerHTML = `
    <div style="font-weight:600;">MMSI: ${result.mmsi}</div>
    <div>船型: ${VESSEL_TYPE_NAMES[result.vesselType] || '不明'}</div>
    <div>軌跡點: ${result.trackPoints}</div>
  `;
  body.appendChild(card);
}

function clearResultCards() {
  const body = document.getElementById('queryPanelBody');
  if (body) body.innerHTML = '';
}

function clearQueryResults() {
  clearResultCards();
  if (onQueryResult) onQueryResult([]);
}

// === 工具函式 ===
function fitBounds(results) {
  if (!map || results.length === 0) return;
  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  for (const r of results) {
    for (const [lon, lat] of r.path) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  }
  map.fitBounds([[minLon, minLat], [maxLon, maxLat]], { padding: 50 });
}

function hslToRgb(h, s, l) {
  s /= 100; l /= 100;
  const a = s * Math.min(l, 1 - l);
  const f = n => {
    const k = (n + h / 30) % 12;
    return l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
  };
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}
