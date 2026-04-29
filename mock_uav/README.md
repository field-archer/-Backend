# Mock UAV（伪造无人机，用于前端全链路联调）

目标：在无人机/车队端尚未实现时，提供一个**完全独立进程**，伪造 UAV 的状态与检测，并响应后端下发的飞行路径。  
注意：本 mock **不接数据库**、不依赖后端内部模块；与业务代码解耦。

## 覆盖的前端功能（与既有接口一致）

1) **定时发送无人机状态**  
后端通过 rosbridge 订阅到 UAV topic 后，经 `/ws/uav` 推送 `uav.telemetry`。

2) **前端发送飞行路径后按路径飞行**  
前端 `POST /api/uav/missions` → 后端 publish `/uav/cmd/waypoint_mission` → mock 接收后按航点依次飞行并持续发布状态。

3) **末段中点一次火点检测（坐标随航线推算）**  
mock 默认从 **GCJ-02** 附近 **116.255813, 40.029607** 起飞；航点间沿 **弦线合速度严格 30 m/s**（经纬度用局部米制位移 + 相对高度差构成 3D 段长，段耗时 = 段长/30；单 tick 可跨段），`local_twist_ned` 与位移同向、模长 30；`local_pose_ned` 的 **roll/pitch** 由低频目标角经 **一阶低通**（时间常数飞行约 1s、地面约 2s）平滑输出，**直线段约 ±1°，仅在转弯（临近航点且前后航段有夹角）时明显增大**。**仅当航点个数 > 5（至少 6 个航点）时**才启用火焰检测：唯一火点为 **倒数第二航点 → 最后一航点** 线段 **中点**；优先在 **末段飞过中点**（`seg_u≥0.5`）时发 **1 次** `/uav/state/fire_detection`；否则在 **末点后的扫描悬停** 补发 **1 次**。航点 ≤5（如常见返航短航线）**不发**火检。`fire_cause=unknown`、`flame_count=1`；**`fire_probability` / `risk_level` / `average_confidence` 每次随机**（合理数值范围内）。

4) **车队（UGV）伪造：到达触发 fleet.arrived**  
前端 `POST /api/uav/missions`（mission_type=fleet）→ 后端 publish `/ugv/cmd/waypoint_mission_geo` → mock 接收后按点移动并在结束时发布 `/ugv/state/mission_status`（arrived=true），后端转成 `fleet.arrived` 推给前端。

## 使用方式

1) 启动 mock（默认 `ws://127.0.0.1:9090`）：

```powershell
python mock_uav/server.py
```

若 9090 端口被占用，可指定端口：

```powershell
$env:MOCK_UAV_PORT=9091
python mock_uav/server.py
```

2) 将后端配置指向本机 rosbridge：

`config/config.yaml`：

```yaml
rosbridge_url: "ws://127.0.0.1:9090"
```

3) 启动后端与前端，按正常流程：
- 登录
- 进入 `/uav` 页面
- 规划航线并点击“起飞”
- 观察 `uav.telemetry` 驱动的位置更新；末段中点触发或扫描补发后会收到 **一次** `uav.detection`
- 规划车队目标并点击“出发/派车”（mission_type=fleet）；抵达后收到 `fleet.arrived`

## 前端是否收到火焰检测？

后端 `WebSocket /ws/uav` 在订阅到 rosbridge 的 `/uav/state/fire_detection` 后，会向前端推送 **`{"type":"uav.detection","payload":{...}}`**（经纬度优先用检测消息里的 `latitude`/`longitude`，否则用当前 UAV GPS）。后端还会在 **`logs/ros.log`**（`forestfire.ros`）里打 **info** 级别 `push uav.detection ...` 便于核对。

## 目标效果自检（火点位置与链路）

| 检查项 | 结论 |
|--------|------|
| 火点含义 | **倒数第二航点 → 最后一航点** 航段 **中点**（与末航点本身不同，除非两航点重合）。 |
| 末航点是否有火 | **否**。`fire_detection` 经纬度 **只** 来自上述预计算中点，**从不** 用机体 `global_position`。优先在 **末段 `seg_u≥0.5`** 时发 1 条；否则在 **末点后的扫描悬停** 阶段补发 1 条。 |
| 其它位置是否有火 | **否**。每任务最多 **1 条** `/uav/state/fire_detection`；航点 ≤5 时 **0 条**。 |
| 前端标点链路 | mock → rosbridge → 后端 `uav.detection`（带消息内 lat/lng）→ **前端**收到后再 **POST `/api/fire-markers`**（后端不落火点 HTTP，由前端发起）。 |

任务下发后 mock 控制台会打印 **`fire site ... last_wp=...`**，可对比 `last_wp` 与末段中点火点坐标是否分离。

## 飞行过程记录（给真机复刻）

每次 mock 收到 **`/uav/cmd/waypoint_mission`** 且航点 **≥2** 时，在目录下写 **`uav_<mission_id>_<UTC时间>.jsonl`**（JSON Lines，一行一个 JSON）：

- 默认目录：`mock_uav/flight_logs/`（已加入仓库根 `.gitignore`）
- 自定义目录：环境变量 **`MOCK_UAV_FLIGHT_LOG_DIR`**（绝对路径或相对运行 cwd 的路径）

文件内容：

1. 首行 **`event":"mission"`**：原始 `waypoints`、解析后的 `resolved_path_lat_lng_alt_m`、末段中点火点坐标 `fire_last_leg_mid_lat_lng`、说明字段。  
2. 随后每 0.2s 一行 **`event":"tick"`**：`t_mission_s`、经纬度、相对高度、NED 线速度、roll/pitch、电量、`landed_published`、`scan_phase`、航段索引等。  
3. 每次发布检测一行 **`event":"fire_detection"`**（完整 `msg`）。  
4. 本段任务结束（火检已发且落地）一行 **`event":"mission_end"`**。

真机侧可按 `t_mission_s` 时间轴，把各字段组装为与 mock 相同的 rosbridge `publish` 报文复播。

