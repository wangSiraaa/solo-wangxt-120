<template>
  <div ref="plotEl" class="residual-plot"></div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import Plotly from 'plotly.js-dist-min'

const props = defineProps({
  results: { type: Object, default: () => ({}) },  // {raw: result, revised: result}
})
const plotEl = ref(null)

const STAGE_COLOR = { raw: '#d62728', revised: '#2ca02c' }

function render() {
  if (!plotEl.value) return
  const traces = []
  for (const [stage, res] of Object.entries(props.results)) {
    if (!res.residuals?.length) continue
    const labels = res.residuals.map((r) => `${r.station_id} ${r.phase}`)
    traces.push({
      type: 'bar',
      x: labels,
      y: res.residuals.map((r) => r.residual_s),
      name: stage,
      marker: {
        color: res.residuals.map((r) =>
          r.is_outlier ? '#ff0000' : STAGE_COLOR[stage] || '#9467bd'),
        opacity: res.residuals.map((r) => (r.phase === 'S' ? 0.55 : 0.9)),
      },
      hovertemplate: res.residuals.map(
        (r) => `${r.station_id} ${r.phase}<br>残差 ${r.residual_s.toFixed(3)} s` +
          `<br>观测 ${r.observed_s.toFixed(2)} / 预测 ${r.predicted_s.toFixed(2)} s` +
          (r.is_outlier ? '<br><b>离群!</b>' : ''),
      ),
    })
  }
  const layout = {
    barmode: 'group',
    margin: { l: 55, r: 10, t: 10, b: 90 },
    height: 300,
    yaxis: { title: '残差 (s)', zeroline: true },
    xaxis: { tickangle: -45 },
    legend: { orientation: 'h', y: 1.15 },
    annotations: [{
      text: '红色 = 离群到时; 深色 = P, 浅色 = S',
      xref: 'paper', yref: 'paper', x: 0, y: 1.08, showarrow: false,
      font: { size: 11, color: '#666' },
    }],
  }
  Plotly.react(plotEl.value, traces, layout, { displayModeBar: false, responsive: true })
}

onMounted(render)
watch(() => props.results, render, { deep: true })
</script>
