/**
 * 圖例模組
 */
import { THEMES } from '../utils/constants.js';

const LEGEND_CONFIGS = {
  trajectory: {
    title: '速度 (節)',
    items: (theme) => {
      const s = THEMES[theme].speed;
      return [
        { color: s[3], label: '> 15' },
        { color: s[2], label: '10 - 15' },
        { color: s[1], label: '5 - 10' },
        { color: s[0], label: '< 5' },
      ];
    },
  },
  density: {
    title: '船舶密度',
    items: (theme) => {
      const d = THEMES[theme].density;
      return [
        { color: d[6], label: '> 50' },
        { color: d[5], label: '21 - 50' },
        { color: d[4], label: '11 - 20' },
        { color: d[3], label: '6 - 10' },
        { color: d[2], label: '3 - 5' },
        { color: d[1], label: '1 - 2' },
      ];
    },
  },
  hexbin: {
    title: '六角網格密度',
    items: (theme) => LEGEND_CONFIGS.density.items(theme),
  },
  heatmap: {
    title: '熱力圖強度',
    gradient: true,
    items: (theme) => {
      return [{ gradient: THEMES[theme].heatGradientCSS, label: '低 → 高' }];
    },
  },
};

export function updateLegend(mode, theme) {
  const legend = document.getElementById('legend');
  if (!legend) return;

  const config = LEGEND_CONFIGS[mode];
  if (!config) {
    legend.style.display = 'none';
    return;
  }

  legend.style.display = 'block';
  const items = config.items(theme);

  let html = `<div class="legend-title">${config.title}</div>`;
  for (const item of items) {
    if (item.gradient) {
      html += `<div class="legend-item"><div class="legend-color" style="width:14px;height:60px;background:${item.gradient};border-radius:3px;"></div><span>${item.label}</span></div>`;
    } else {
      html += `<div class="legend-item"><div class="legend-color" style="background:${item.color};"></div><span>${item.label}</span></div>`;
    }
  }
  legend.innerHTML = html;
}
