/**
 * Twitter Curated Portal - 本地微抖动自动化捕获雷达 (Dev Probe)
 * 仅在 localhost / 127.0.0.1 激活，严密监测累计布局偏移 (CLS)
 */
if (typeof window !== 'undefined' && (location.hostname === 'localhost' || location.hostname === '127.0.0.1')) {
  try {
    new PerformanceObserver((entryList) => {
      for (var entry of entryList.getEntries()) {
        if (!entry.hadRecentInput && entry.value > 0.0001) {
          console.groupCollapsed(
            `%c[Layout Shift 抖动捕获]%c 偏移: ${entry.value.toFixed(4)} | 耗时: ${entry.startTime.toFixed(1)}ms`,
            'background: #e11d48; color: #fff; font-weight: bold; padding: 2px 6px; border-radius: 4px;',
            'color: #f43f5e; font-weight: bold;'
          );
          console.warn('偏移发生时的视口高度:', window.innerHeight, '滚动位置:', window.scrollY);
          console.dir(entry.sources);
          console.groupEnd();
        }
      }
    }).observe({ type: 'layout-shift', buffered: true });
    console.info('%c[抗抖动防线激活]%c Direct Sticky Invariant 雷达巡航中，严密监控 0 抖动。', 'color: #0d9488; font-weight: bold;', 'color: inherit;');
  } catch (e) {
    /* 浏览器不支持 PerformanceObserver 或 layout-shift 时静默降级 */
  }
}
