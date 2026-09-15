# 地震定位教学演示

从几个台站的波形到时恢复候选事件位置的教学应用。**仅用于教学, 不构成真实地震预警。**

## 架构

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | Vue 3 + Plotly.js (Vite) | 波形/到时展示、人工修订拾取、候选解与几何覆盖比较 |
| 后端 | FastAPI + ObsPy + SciPy | 合成波形解析、走时正演、网格搜索 + 稳健最小二乘定位 |
| 数据库 | PostgreSQL/PostGIS | 台站 (geography)、两阶段拾取、绑定版本的定位结果 (见 `backend/app/db/schema.sql`) |

## 核心教学原则 (已实现)

- **简化速度模型显式声明**: 均匀半空间、平直地球、直射线, Vp=5.8 km/s, Vs=Vp/1.73,
  深度固定 10 km 不参与反演。模型版本 `homogeneous-halfspace-v1` 绑定到每个结果。
- **P/S 严格分离**: 每条拾取必须带 `P` 或 `S` 震相, 走时按各自速度计算;
  未知震相 (如 `Pg`) 直接拒绝, 不混用速度。
- **不只报精确坐标**: 每个候选解同时给出 RMS 残差、逐台残差 (含离群标记)、
  68% 置信椭圆、方位角空隙、法方程条件数。
- **缺测/错误拾取可见**: 逐台残差图中离群到时红色高亮; 残差基于 MAD 的稳健检测。
- **可定位性判定**: 有效台站 < 3 或到时 < 3 → `UNLOCATABLE (台站不足)`;
  方位角空隙 > 180° → `UNLOCATABLE (几何覆盖不足)`; 条件数过大 → `POORLY_CONSTRAINED`。
- **镜像模糊解诊断**: 网格搜索发现 RSS 接近的独立极小时明确报告 (共线台阵的典型陷阱),
  而不是只给线性化椭圆。
- **原始与修订分离**: `raw` (自动拾取) 只读, `revised` (人工修订) 可写;
  定位接口对两阶段分别计算, 前端并排比较。
- **结果可重算、可解释**: 每个解绑定 `model_version` / `engine_version` / `data_version`
  (拾取+台站+模型的 SHA-256 指纹), 输入任何变化都会改变指纹。

## 三个合成教学案例 (真值已知)

1. **good-geometry** — 8 台包围震源, 干净到时: 标准流程、残差分布、置信椭圆。
2. **outlier-picks** — 自动拾取混入 2 条严重错误到时: raw 解被拉偏且残差暴露离群;
   revised (人工修订) 解恢复正常, 演示两阶段分离的价值。
3. **collinear-stations** — 6 台几乎共线: 方位角空隙 ~202°, 存在镜像双极小,
   引擎报告 `UNLOCATABLE` 而非假精确解。

波形为合成数据 (噪声 + P/S 波列), 可通过 `/api/scenarios/{id}/waveforms.mseed`
下载 MiniSEED 用标准工具复查。

## 运行

```bash
# 后端 (开发)
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# 前端 (开发, 代理 /api 到 8000)
cd frontend
npm install
npm run dev   # http://localhost:5173

# 测试
cd backend && python -m pytest tests/

# 完整部署 (PostGIS + 后端 + 前端)
docker compose up --build
```

说明: 后端默认使用内存场景存储, 便于课堂直接启动; `docker-compose.yml` 提供
PostGIS 持久化 (schema 见 `backend/app/db/schema.sql`), 将 `app/store.py`
替换为 SQLAlchemy 实现即可接入, API 层不变。

## API 摘要

- `GET /api/scenarios` / `GET /api/scenarios/{id}` — 场景与两阶段拾取
- `GET /api/scenarios/{id}/waveforms` — JSON 波形; `.mseed` 下载 MiniSEED
- `PUT /api/scenarios/{id}/picks/revised` — 保存人工修订 (raw 不可改)
- `POST /api/scenarios/{id}/locate` — raw 与 revised 分别定位, 返回候选解比较
- `GET /api/velocity-model` — 当前速度模型及适用范围声明
