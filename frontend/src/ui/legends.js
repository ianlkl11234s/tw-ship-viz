import { THEMES } from '../utils/constants.js';

/**
 * 更新圖例顯示。
 * @param {string} mode - 當前模式
 * @param {string} theme - 'day' | 'night'
 */
export function updateLegend(mode, theme) {
  const legend = document.getElementById('legend');
  if (!legend) return;

  const config = getLegendConfig(mode, theme);
  if (!config) {
    legend.style.display = 'none';
    return;
  }

  legend.style.display = '';
  legend.innerHTML = `
    <div class="legend-title">${config.title}</div>
    ${config.items.map(item => `
      <div class="legend-item">
        <div class="legend-color" style="background:${item.color};"></div>
        <span>${item.label}</span>
      </div>
    `).join('')}
  `;
}

function getLegendConfig(mode, theme) {
  const t = THEMES[theme];

  switch (mode) {
    case 'trajectory':
      return {
        title: '航行速度',
        items: [
          { color: t.speed[3], label: '> 15 節' },
          { color: t.speed[2], label: '10-15 節' },
          { color: t.speed[1], label: '5-10 節' },
          { color: t.speed[0], label: '< 5 節' },
        ],
      };
    case 'density':
    case 'hexbin':
      return {
        title: '船舶密度',
        items: [
          { color: t.density[6] || t.density[5], label: '> 50 艘' },
          { color: t.density[5] || t.density[4], label: '21-50 艘' },
          { color: t.density[4] || t.density[3], label: '11-20 艘' },
          { color: t.density[3] || t.density[2], label: '6-10 艘' },
          { color: t.density[2] || t.density[1], label: '3-5 艘' },
          { color: t.density[1], label: '1-2 艘' },
        ],
      };
    case 'heatmap':
      return {
        title: '航線密度',
        items: [
          { color: Object.values(t.heatGradient)[5], label: '高密度' },
          { color: Object.values(t.heatGradient)[3], label: '中密度' },
          { color: Object.values(t.heatGradient)[1], label: '低密度' },
        ],
      };
    default:
      return null;
  }
}
