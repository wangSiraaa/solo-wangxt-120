# 地震定位教学演示

从几个台站的波形到时恢复候选事件位置的教学应用。**仅用于教学, 不构成真实地震预警。**

## 架构

| 层 | 技术 | 说明 |
|---|---|---|
| 前端 | Vue 3 + Plotly.js (Vite) | 波形/到时展示、人工修订拾取、候选解与几何覆盖比较 |
| 后端 | FastAPI + ObsPy + SciPy | MiniSEED 示例数据解析、走时正演、网格搜索 + 稳健最小二乘定位 |
| 数据库 | PostgreSQL/PostGIS (SQLAlchemy + psycopg) | 台站 (geography 生成列)、两阶段拾取、修订历史、绑定版本的定位结果历史 |

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

波形为合成数据 (噪声 + P/S 波列), 以 MiniSEED + StationXML 示例文件交付
(`backend/sample_data/`, 确定性种子生成, 缺失时启动自动重建)。所有波形/台站读取
一律经 `obspy.read` / `obspy.read_inventory` 解析, 与真实数据处理工具链一致;
`/api/scenarios/{id}/waveforms.mseed` 可下载原始文件用标准工具复查。

## 持久化链路

- 设置 `DATABASE_URL` 即接入 SQL 存储 (生产: `postgresql://...` 走 PostGIS;
  测试可用 SQLite); 未设置时退回内存存储, 便于课堂快速启动。API 层不感知差异。
- 启动时幂等迁移 (`schema_migrations` 版本表); PostgreSQL 上自动追加
  PostGIS geography 生成列与 **raw 不可变触发器** (权威 DDL 见 `backend/app/db/schema.sql`)。
- `raw` 拾取只读: 仓库层拒绝修改, PG 触发器数据库级兜底。
- `revised` 每次保存都写入 `pick_revisions` 追加式历史 (含修订人)。
- 每次定位运行的结果写入 `solutions` 历史, 绑定
  `model_version` / `engine_version` / `data_version`。
- **容器重启后**: 同一场景的人工修订与历史定位结果均可从数据库读回
  (docker 使用 `pgdata` 卷; 已由"同库重连"测试覆盖)。

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
# 有可用 PostgreSQL 时跑真实 PG 集成测试:
TEST_DATABASE_URL=postgresql://geo:geo@localhost:5432/geoteach python -m pytest tests/

# 完整部署 (PostGIS + 后端 + 前端)
docker compose up --build
```

说明: 未设 `DATABASE_URL` 时后端使用内存场景存储, 便于课堂直接启动;
docker 部署自动接入 PostGIS (见"持久化链路")。

## API 摘要

- `GET /api/scenarios` / `GET /api/scenarios/{id}` — 场景与两阶段拾取
- `GET /api/scenarios/{id}/waveforms` — JSON 波形 (MiniSEED 经 obspy.read 解析)
- `GET /api/scenarios/{id}/sample-data` — 示例数据解析入口: 波形 + StationXML 台站
- `GET /api/scenarios/{id}/waveforms.mseed` — MiniSEED 原始文件下载
- `PUT /api/scenarios/{id}/picks/revised` — 保存人工修订 (raw 不可改, 留修订历史)
- `GET /api/scenarios/{id}/picks/revisions` — 修订历史
- `POST /api/scenarios/{id}/locate` — raw 与 revised 分别定位并持久化结果
- `GET /api/scenarios/{id}/locate/history` — 历史定位结果 (绑定版本)
- `GET /api/velocity-model` — 当前速度模型及适用范围声明
