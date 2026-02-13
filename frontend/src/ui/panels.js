/**
 * 狀態面板管理。
 */

/**
 * 更新狀態面板的統計資訊。
 * @param {Object} stats
 * @param {number} stats.shipCount - 船舶數
 * @param {number} [stats.maxDensity] - 最高密度（密度模式）
 */
export function updateStatsPanel(stats) {
  const statShips = document.getElementById('statShips');
  if (statShips) {
    statShips.textContent = stats.shipCount != null
      ? stats.shipCount.toLocaleString()
      : '--';
  }
}

/**
 * 顯示/隱藏 loading 遮罩。
 */
export function setLoading(visible, text) {
  const loading = document.getElementById('loading');
  if (!loading) return;

  loading.style.display = visible ? 'flex' : 'none';
  if (text) {
    const textEl = loading.querySelector('.loading-text');
    if (textEl) textEl.textContent = text;
  }
}
