<template>
  <div>
    <div class="toolbar">
      <span class="hint">修订模式:</span>
      <button :class="{ active: editPhase === 'P' }" @click="editPhase = 'P'">标记 P</button>
      <button :class="{ active: editPhase === 'S' }" @click="editPhase = 'S'">标记 S</button>
      <button :class="{ active: editPhase === null }" @click="editPhase = null">仅查看</button>
      <button class="danger" @click="$emit('resetRevised')">恢复修订为原始拾取</button>
      <span class="hint">虚线=原始自动拾取, 实线=人工修订; 点击波形写入修订到时</span>
    </div>
    <div ref="plotEl" class="waveform-plot"></div>
  </div>
</template>

<script setup>
import { onMounted, ref, watch } from 'vue'
import Plotly from 'plotly.js-dist-min'

const props = defineProps({
  waveforms: { type: Array, required: true },      // [{station_id, t, y}]
  rawPicks: { type: Array, required: true },       // [{station_id, phase, time_s}]
  revisedPicks: { type: Array, required: true },
})
const emit = defineEmits(['updatePick', 'resetRevised'])

const plotEl = ref(null)
const editPhase = ref(null)

function pickShapes(picks, dash, color, width) {
  const shapes = []
  props.waveforms.forEach((wf, i) => {
    const yref = i === 0 ? 'y' : `y${i + 1}`
    for (const p of picks) {
      if (p.station_id !== wf.station_id) continue
      shapes.push({
        type: 'line', x0: p.time_s, x1: p.time_s, y0: 0, y1: 1,
        xref: 'x', yref: `${yref} domain`,
        line: { color: p.phase === 'P' ? color : '#d62728', width, dash },
      })
    }
  })
  return shapes
}

function annotations() {
  // 每台左侧标注台站名
  return props.waveforms.map((wf, i) => ({
    text: wf.station_id, xref: 'paper', yref: 'paper',
    x: -0.04, y: 1 - (i + 0.5) / props.waveforms.length,
    showarrow: false, font: { size: 11 },
  }))
}

function render() {
  const n = props.waveforms.length
  if (!n || !plotEl.value) return
  const traces = props.waveforms.map((wf, i) => ({
    x: wf.t, y: wf.y, type: 'scatter', mode: 'lines',
    line: { color: '#1f77b4', width: 0.7 },
    xaxis: 'x', yaxis: i === 0 ? 'y' : `y${i + 1}`,
    name: wf.station_id, showlegend: false, hoverinfo: 'x+y',
  }))
  const layout = {
    grid: { rows: n, columns: 1, pattern: 'coupled' },  // 各行共享时间轴
    margin: { l: 70, r: 20, t: 10, b: 40 },
    height: Math.max(320, n * 90),
    xaxis: { title: '时间 (s, 相对场景参考时刻)' },
    shapes: [
      ...pickShapes(props.rawPicks, 'dot', '#888888', 1),
      ...pickShapes(props.revisedPicks, 'solid', '#1f77b4', 2),
    ],
    annotations: annotations(),
    showlegend: false,
  }
  for (let i = 1; i <= n; i++) {
    layout[`yaxis${i}`] = { showticklabels: false, fixedrange: true }
  }
  Plotly.react(plotEl.value, traces, layout, { displayModeBar: false, responsive: true })

  plotEl.value.removeAllListeners?.('plotly_click')
  plotEl.value.on('plotly_click', (ev) => {
    if (!editPhase.value || !ev.points?.length) return
    const pt = ev.points[0]
    const staIdx = pt.data.yaxis === 'y' ? 0 : Number(pt.data.yaxis.replace('y', '')) - 1
    const stationId = props.waveforms[staIdx]?.station_id
    if (stationId) emit('updatePick', stationId, editPhase.value, Math.round(pt.x * 1000) / 1000)
  })
}

onMounted(render)
watch(() => [props.waveforms, props.rawPicks, props.revisedPicks], render, { deep: true })
</script>
