<template>
  <div class="app">
    <header>
      <h1>地震定位教学演示</h1>
      <p class="disclaimer">
        ⚠️ 本系统仅用于教学: 使用简化均匀半空间速度模型 ({{ model?.version }}),
        合成波形与已知真值, <b>不构成真实地震预警</b>。
      </p>
    </header>

    <section class="scenario-bar">
      <button
        v-for="s in scenarios" :key="s.id"
        :class="{ active: s.id === currentId }"
        @click="selectScenario(s.id)"
      >{{ s.title }}</button>
    </section>

    <section v-if="scenario" class="scenario-info">
      <p>{{ scenario.description }}</p>
      <ul>
        <li v-for="(tp, i) in scenario.teaching_points" :key="i">{{ tp }}</li>
      </ul>
      <p class="meta">
        台站数 {{ scenario.n_stations }} · 数据版本 {{ scenario.data_version }} ·
        模型 {{ model?.version }} (Vp={{ model?.vp_km_s }} km/s, Vs={{ model?.vs_km_s?.toFixed(2) }} km/s,
        固定深度 {{ model?.fixed_depth_km }} km)
      </p>
    </section>

    <main v-if="scenario">
      <section class="panel">
        <h2>波形与到时拾取</h2>
        <WaveformPanel
          v-if="waveforms.length"
          :waveforms="waveforms"
          :raw-picks="scenario.raw_picks"
          :revised-picks="revisedPicks"
          @updatePick="onUpdatePick"
          @resetRevised="resetRevised"
        />
        <div class="actions">
          <button class="primary" :disabled="locating" @click="runLocate">
            {{ locating ? '定位中…' : '运行定位 (raw 与 revised 分别计算)' }}
          </button>
          <span v-if="saveMsg" class="save-msg">{{ saveMsg }}</span>
        </div>
      </section>

      <template v-if="locateResponse">
        <section class="panel">
          <h2>候选解比较</h2>
          <div class="status-row">
            <div
              v-for="(res, stage) in locateResponse.results" :key="stage"
              class="status-card" :class="res.status.toLowerCase()"
            >
              <h3>{{ stage === 'raw' ? '原始拾取解' : '人工修订解' }}
                <span class="badge">{{ res.status }}</span>
              </h3>
              <p v-if="res.lat != null">
                震中 ({{ res.lat.toFixed(3) }}°, {{ res.lon.toFixed(3) }}°) ·
                深度 {{ res.depth_km }} km (固定) ·
                发震时刻 {{ res.origin_time_s?.toFixed(2) }} s
              </p>
              <p v-else>无可信坐标解</p>
              <p>
                RMS 残差 {{ res.rms_residual_s?.toFixed(3) ?? '—' }} s ·
                方位角空隙 {{ res.azimuthal_gap_deg?.toFixed(0) ?? '—' }}° ·
                {{ res.n_stations }} 台 / {{ res.n_p_picks }} P / {{ res.n_s_picks }} S
              </p>
              <p v-if="res.ellipse_68">
                68% 置信椭圆: 长轴 {{ res.ellipse_68.semi_major_km.toFixed(1) }} km ×
                短轴 {{ res.ellipse_68.semi_minor_km.toFixed(1) }} km,
                方位 {{ res.ellipse_68.major_axis_azimuth_deg.toFixed(0) }}°
              </p>
              <ul class="reasons">
                <li v-for="(r, i) in res.status_reasons" :key="i">{{ r }}</li>
              </ul>
              <p class="meta">
                模型 {{ res.model_version }} · 引擎 {{ res.engine_version }} ·
                数据指纹 {{ res.data_version }}
              </p>
              <p class="meta">{{ res.disclaimer }}</p>
            </div>
          </div>
          <p class="meta">
            真值 (教学对照): ({{ scenario.true_source.lat.toFixed(3) }}°,
            {{ scenario.true_source.lon.toFixed(3) }}°),
            发震时刻 {{ scenario.true_source.origin_time_s.toFixed(1) }} s
          </p>
        </section>

        <section class="panel">
          <h2>几何覆盖与候选解分布</h2>
          <StationMap
            :stations="scenario.stations"
            :true-source="scenario.true_source"
            :results="locateResponse.results"
          />
        </section>

        <section class="panel">
          <h2>逐台残差 (缺测/错误拾取在此暴露)</h2>
          <ResidualChart :results="locateResponse.results" />
        </section>
      </template>
    </main>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { api } from './api/client'
import WaveformPanel from './components/WaveformPanel.vue'
import StationMap from './components/StationMap.vue'
import ResidualChart from './components/ResidualChart.vue'

const scenarios = ref([])
const currentId = ref(null)
const scenario = ref(null)
const waveforms = ref([])
const revisedPicks = ref([])
const model = ref(null)
const locateResponse = ref(null)
const locating = ref(false)
const saveMsg = ref('')

async function selectScenario(id) {
  currentId.value = id
  locateResponse.value = null
  saveMsg.value = ''
  scenario.value = await api.getScenario(id)
  revisedPicks.value = scenario.value.revised_picks.map((p) => ({ ...p }))
  waveforms.value = await api.getWaveforms(id)
}

async function persistRevised() {
  const picks = revisedPicks.value.map(({ station_id, phase, time_s, weight }) => ({
    station_id, phase, time_s, weight: weight ?? 1.0,
  }))
  await api.saveRevisedPicks(currentId.value, picks)
  saveMsg.value = `已保存 ${picks.length} 条修订到时 (raw 保持不变)`
}

async function onUpdatePick(stationId, phase, timeS) {
  const idx = revisedPicks.value.findIndex(
    (p) => p.station_id === stationId && p.phase === phase)
  if (idx >= 0) revisedPicks.value[idx].time_s = timeS
  else revisedPicks.value.push({ station_id: stationId, phase, time_s: timeS, weight: 1.0 })
  await persistRevised()
}

async function resetRevised() {
  revisedPicks.value = scenario.value.raw_picks.map((p) => ({ ...p }))
  await persistRevised()
}

async function runLocate() {
  locating.value = true
  try {
    locateResponse.value = await api.locate(currentId.value)
  } finally {
    locating.value = false
  }
}

onMounted(async () => {
  model.value = await api.getVelocityModel()
  scenarios.value = await api.listScenarios()
  if (scenarios.value.length) await selectScenario(scenarios.value[0].id)
})
</script>
