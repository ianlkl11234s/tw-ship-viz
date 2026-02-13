import { VESSEL_TYPE_NAMES } from '../utils/constants.js';

/**
 * 查詢模式控制器：點選船舶 / 矩形圈選 / 結果面板。
 */

let queryTool = 'click';
let isSelecting = false;
let selectStart = null;
let onQueryResult = null;    // 回調：查詢結果更新
let onQueryShipsLoad = null; // 回調：船舶散點載入

/**
 * 初始化查詢控件。
 * @param {Object} opts
 * @param {Function} opts.onQueryResult - (results) => void
 * @param {Function} opts.onQueryShipsLoad - (ships) => void
 * @param {maplibregl.Map} opts.map
 */
export function initQueryControls(opts) {
  onQueryResult = opts.onQueryResult;
  onQueryShipsLoad = opts.onQueryShipsLoad;

  // 工具按鈕
  const toolbar = document.getElementById('queryToolbar');
  if (!toolbar) return;

  toolbar.querySelectorAll('.tool-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const tool = btn.dataset.tool;
      if (tool === 'clear') {
        clearQuery();
        return;
      }
      queryTool = tool;
      toolbar.querySelectorAll('.tool-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
  });
}

/**
 * 啟用查詢模式。
 */
export async function enableQueryMode() {
  const toolbar = document.getElementById('queryToolbar');
  const panel = document.getElementById('queryPanel');
  if (toolbar) toolbar.style.display = '';
  if (panel) panel.style.display = '';

  // 載入最新船舶位置
  try {
    const res = await fetch('/api/ships/latest');
    if (res.ok) {
      const data = await res.json();
      const ships = data.map(s => ({
        position: [s.lon, s.lat],
        mmsi: s.mmsi,
        vessel_type: s.vessel_type || 0,
        sog: s.sog || 0,
      }));
      if (onQueryShipsLoad) onQueryShipsLoad(ships);
    }
  } catch {
    console.warn('[query] 無法載入最新船舶位置');
  }
}

/**
 * 停用查詢模式。
 */
export function disableQueryMode() {
  const toolbar = document.getElementById('queryToolbar');
  const panel = document.getElementById('queryPanel');
  if (toolbar) toolbar.style.display = 'none';
  if (panel) panel.style.display = 'none';
  clearQuery();
}

/**
 * 處理 deck.gl picking 事件（點選船舶）。
 */
export async function handlePick(info) {
  if (queryTool !== 'click' || !info.object) return;

  const { mmsi } = info.object;
  if (!mmsi) return;

  try {
    const res = await fetch(`/api/ship/${mmsi}/track?days=7`);
    if (!res.ok) return;
    const data = await res.json();

    const result = {
      mmsi,
      vessel_type: data.vessel_type || 0,
      path: data.track.map(p => [p.lon, p.lat]),
      timestamps: data.track.map(p => new Date(p.timestamp).getTime() / 1000),
      speeds: data.track.map(p => p.sog || 0),
      pointCount: data.track.length,
      timeSpan: data.track.length > 1
        ? `${data.track[0].timestamp} ~ ${data.track[data.track.length - 1].timestamp}`
        : '--',
    };

    if (onQueryResult) onQueryResult([result]);
    updatePanel([result]);
  } catch (err) {
    console.error('[query] 單船查詢失敗:', err);
  }
}

/**
 * 處理矩形圈選（需由外部 mousedown/move/up 呼叫）。
 */
export function handleRectSelect(bbox) {
  // bbox: { minLon, maxLon, minLat, maxLat }
  fetch(`/api/ships/tracks?days=7`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(bbox),
  })
    .then(res => res.json())
    .then(data => {
      const results = data.map(ship => ({
        mmsi: ship.mmsi,
        vessel_type: ship.vessel_type || 0,
        path: ship.track.map(p => [p.lon, p.lat]),
        timestamps: ship.track.map(p => new Date(p.timestamp).getTime() / 1000),
        speeds: ship.track.map(p => p.sog || 0),
        pointCount: ship.track.length,
      }));
      if (onQueryResult) onQueryResult(results);
      updatePanel(results);
    })
    .catch(err => console.error('[query] 圈選查詢失敗:', err));
}

function clearQuery() {
  if (onQueryResult) onQueryResult([]);
  const body = document.getElementById('queryPanelBody');
  if (body) body.innerHTML = '<div style="padding:16px;color:#999;text-align:center;">點選船舶或圈選區域來查詢軌跡</div>';
}

function updatePanel(results) {
  const body = document.getElementById('queryPanelBody');
  if (!body) return;

  if (results.length === 0) {
    body.innerHTML = '<div style="padding:16px;color:#999;text-align:center;">無結果</div>';
    return;
  }

  body.innerHTML = results.map(r => `
    <div style="padding:10px;border-bottom:1px solid #eee;">
      <div style="font-weight:600;font-size:13px;">MMSI: ${r.mmsi}</div>
      <div style="font-size:12px;color:#666;">
        類型: ${VESSEL_TYPE_NAMES[r.vessel_type] || '未知'}
        ${r.pointCount ? `| 軌跡點: ${r.pointCount}` : ''}
        ${r.timeSpan ? `<br>時間: ${r.timeSpan}` : ''}
      </div>
    </div>
  `).join('');
}
