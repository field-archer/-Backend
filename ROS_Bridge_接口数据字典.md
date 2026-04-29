# ROS Bridge 接口数据字典（UAV + UGV）

> 适用环境：`/home/th1rt3en/sim_ws/ros2_ws` 当前实现（AirSim + ROS 2 Humble）

## 1. 总体约定

- UAV 默认命名空间：`/uav`（由 launch 参数 `namespace` 决定，默认 `uav`）
- UGV 接口为绝对话题名（固定 `/ugv/...`）
- 坐标系：
  - UAV 本地位姿/速度沿用 AirSim NED（`x` 北，`y` 东，`z` 下）
  - UGV 输出 `odom/imu/scan` 为 ROS 常见 NWU 语义（代码中做了 NED->ROS 转换）
- QoS：均使用节点默认 `Reliable + Volatile`，队列深度见下表

## 2. UAV 对外输入接口（控制）

### 2.1 Topic（订阅）

| Topic | Type | Queue | 说明 |
| --- | --- | --- | --- |
| `/uav/cmd/takeoff` | `std_msgs/msg/Empty` | 10 | 异步起飞 |
| `/uav/cmd/land` | `std_msgs/msg/Empty` | 10 | 异步降落 |
| `/uav/cmd/altitude` | `std_msgs/msg/Float32` | 10 | 相对高度（米，正向上） |
| `/uav/cmd/gps` | `sensor_msgs/msg/NavSatFix` | 10 | 单点 GPS 导航 |
| `/uav/cmd/waypoint_mission` | `airsim_uav_interfaces/msg/GeoWaypointMission` | 10 | 航点序列任务 |

#### `GeoWaypointMission` 数据结构

```text
std_msgs/Header header
string mission_id
bool wait_for_completion
GeoWaypoint[] waypoints
```

#### `GeoWaypoint` 数据结构

```text
float64 latitude
float64 longitude
float64 altitude_m
float32 velocity_mps
float32 timeout_sec
float32 hold_time_sec
bool use_yaw
float32 yaw_deg
```

### 2.2 Service

| Service | Type | 说明 |
| --- | --- | --- |
| `/uav/takeoff` | `airsim_uav_interfaces/srv/Takeoff` | 起飞 |
| `/uav/land` | `airsim_uav_interfaces/srv/Land` | 降落 |
| `/uav/set_altitude` | `airsim_uav_interfaces/srv/SetAltitude` | 定高 |
| `/uav/navigate_to_geo` | `airsim_uav_interfaces/srv/NavigateToGeo` | 单点 GPS 导航 |
| `/uav/execute_waypoint_mission` | `airsim_uav_interfaces/srv/ExecuteGeoWaypointMission` | 航点任务执行 |

#### `ExecuteGeoWaypointMission.srv`

请求：

```text
GeoWaypoint[] waypoints
bool wait
```

响应：

```text
bool success
int32 completed_waypoints
string message
```

## 3. UAV 对外输出接口（状态）

### 3.1 Topic（发布）

| Topic | Type | Queue | 说明 |
| --- | --- | --- | --- |
| `/uav/state/home` | `sensor_msgs/msg/NavSatFix` | 10 | Home 地理点 |
| `/uav/state/global_position` | `sensor_msgs/msg/NavSatFix` | 10 | 当前 GPS |
| `/uav/state/local_pose_ned` | `geometry_msgs/msg/PoseStamped` | 10 | 本地 NED 位姿 |
| `/uav/state/local_twist_ned` | `geometry_msgs/msg/TwistStamped` | 10 | 本地 NED 速度 |
| `/uav/state/relative_altitude` | `std_msgs/msg/Float32` | 10 | 相对高度（米） |
| `/uav/state/landed` | `std_msgs/msg/Bool` | 10 | 是否落地 |
| `/uav/state/battery` | `sensor_msgs/msg/BatteryState` | 10 | 电池数据（可能 NaN） |
| `/uav/state/basic_status` | `diagnostic_msgs/msg/DiagnosticArray` | 10 | 基础状态 + 扩展键值 |
| `/uav/state/camera/downward/image/compressed` | `sensor_msgs/msg/CompressedImage` | 2 | 下视相机图像（PNG 压缩） |

### 3.3 下视相机数据格式

`sensor_msgs/msg/CompressedImage`：

```text
std_msgs/Header header
string format        # 本实现固定为 "png"
uint8[] data         # 压缩后的 PNG 二进制数据
```

桥接参数默认值（可通过 launch 改）：

- `enable_downward_camera=true`
- `downward_camera_name=downward`
- `downward_camera_frame_id=uav_downward_camera_optical_frame`
- `downward_camera_rate_hz=5.0`
- `downward_camera_image_type=0`（Scene）

### 3.2 `basic_status` 关键字段

`status[0].values` 中固定常见键：

- `vehicle_name`
- `landed`
- `can_arm`
- `ready`
- `battery_percentage`
- `battery_voltage`
- `battery_current`

可扩展键：

- `extra.<key>`（从 AirSim state 动态透传）

## 4. UGV 对外输入接口（控制 / 在线 SLAM）

### 4.1 Topic（订阅）

| Topic | Type | Queue | 说明 |
| --- | --- | --- | --- |
| `/ugv/cmd_vel` | `geometry_msgs/msg/Twist` | 20 | 底盘速度控制 |
| `/ugv/navigation/relative_goal` | `geometry_msgs/msg/Pose2D` | 10 | 在线相对目标（平面） |
| `/ugv/cmd/waypoint_mission_geo` | `airsim_uav_interfaces/msg/GeoWaypointMission` | 10 | 车队 GPS 航点序列任务（经纬度） |

`/ugv/navigation/relative_goal` 语义：

- `x`：车体坐标系前向相对位移（米）
- `y`：车体坐标系左向相对位移（米）
- `theta`：相对偏航（弧度，可选）

`/ugv/cmd/waypoint_mission_geo` 语义：

- 使用与 UAV 相同的 `GeoWaypointMission` / `GeoWaypoint` 结构（见 2.1），但在 UGV 侧：
  - `altitude_m` 可忽略或作为参考值（推荐填 0）
  - `velocity_mps` 可选（若 UGV 控制器支持则用）
- 由 UGV 端负责：经纬度 -> 本地导航坐标系投影、路径规划与跟踪控制。

### 4.2 Service

| Service | Type | 说明 |
| --- | --- | --- |
| `/ugv/navigation/go_relative_xy` | `ugv_bringup_interfaces/srv/GoRelativeXY` | 相对位移目标 |
| `/ugv/navigation/go_to_pose` | `ugv_bringup_interfaces/srv/GoToPose` | 绝对平面位姿目标 |
| `/ugv/execute_waypoint_mission_geo` | `airsim_uav_interfaces/srv/ExecuteGeoWaypointMission` | 车队 GPS 航点任务执行（经纬度） |

#### `ExecuteGeoWaypointMission`（UGV 版本）说明

- Service 结构与 UAV 相同（见 2.2），仅表示服务端执行的是 UGV 的 GPS 航点任务。

#### `GoRelativeXY.srv`

请求：

```text
float32 x
float32 y
```

响应：

```text
bool success
string message
string goal_frame_id
float32 goal_x
float32 goal_y
float32 goal_yaw
```

#### `GoToPose.srv`

请求：

```text
float32 x
float32 y
float32 yaw
```

响应：

```text
bool success
string message
string goal_frame_id
float32 goal_x
float32 goal_y
float32 goal_yaw
```

## 5. UGV 对外输出接口（状态）

| Topic | Type | Queue | 说明 |
| --- | --- | --- | --- |
| `/ugv/odom` | `nav_msgs/msg/Odometry` | 30 | 里程计 |
| `/ugv/imu` | `sensor_msgs/msg/Imu` | 30 | IMU |
| `/ugv/scan` | `sensor_msgs/msg/LaserScan` | 10 | 激光 |
| `/ugv/state/global_position` | `sensor_msgs/msg/NavSatFix` | 10 | 当前 GPS（建议统一为 GCJ-02 供高德地图展示） |
| `/ugv/state/battery` | `sensor_msgs/msg/BatteryState` | 10 | 电池数据（可能 NaN） |
| `/ugv/state/basic_status` | `diagnostic_msgs/msg/DiagnosticArray` | 10 | 基础状态 + 扩展键值 |
| `/ugv/state/mission_status` | `diagnostic_msgs/msg/DiagnosticArray` | 10 | 车队任务状态（到达/进度/失败原因） |

`/ugv/state/basic_status` 固定常见键：

- `vehicle_name`
- `speed_mps`
- `gear`
- `rpm`
- `maxrpm`
- `handbrake`
- `battery_percentage`
- `battery_voltage`
- `battery_current`

可扩展键：

- `extra.<key>`（从 AirSim car state 动态透传）

`/ugv/state/mission_status` 约定键（`status[0].values`）：

- `mission_id`：当前任务 ID（与下发任务一致；空表示无任务）
- `state`：`idle` / `running` / `arrived` / `failed` / `cancelled`
- `arrived`：`true/false`（state=arrived 时为 true）
- `completed_waypoints`：已完成航点数（可选）
- `message`：可读说明/失败原因（可选）
- `ts`：时间戳（可选，ISO8601 字符串或数值秒）

## 6. 给 rosbridge 的 JSON 示例

### 6.1 发布 UAV 航点任务（`op=publish`）

```json
{
  "op": "publish",
  "topic": "/uav/cmd/waypoint_mission",
  "msg": {
    "header": {"frame_id": "", "stamp": {"sec": 0, "nanosec": 0}},
    "mission_id": "mission_demo_001",
    "wait_for_completion": false,
    "waypoints": [
      {
        "latitude": 40.002920,
        "longitude": 116.338360,
        "altitude_m": 80.0,
        "velocity_mps": 4.0,
        "timeout_sec": 120.0,
        "hold_time_sec": 2.0,
        "use_yaw": true,
        "yaw_deg": 90.0
      }
    ]
  }
}
```

### 6.2 调用 UAV 航点任务服务（`op=call_service`）

```json
{
  "op": "call_service",
  "service": "/uav/execute_waypoint_mission",
  "args": {
    "wait": true,
    "waypoints": [
      {
        "latitude": 40.002920,
        "longitude": 116.338360,
        "altitude_m": 80.0,
        "velocity_mps": 4.0,
        "timeout_sec": 120.0,
        "hold_time_sec": 2.0,
        "use_yaw": true,
        "yaw_deg": 90.0
      }
    ]
  },
  "id": "uav_waypoint_1"
}
```

### 6.3 发布 UGV 在线相对目标（`op=publish`）

```json
{
  "op": "publish",
  "topic": "/ugv/navigation/relative_goal",
  "msg": {
    "x": 1.0,
    "y": 0.5,
    "theta": 0.2
  }
}
```

### 6.3b 发布 UGV GPS 航点任务（`op=publish`）

```json
{
  "op": "publish",
  "topic": "/ugv/cmd/waypoint_mission_geo",
  "msg": {
    "header": {"frame_id": "", "stamp": {"sec": 0, "nanosec": 0}},
    "waypoints": [
      {
        "latitude": 40.002920,
        "longitude": 116.338360,
        "altitude_m": 0.0,
        "velocity_mps": 2.0,
        "timeout_sec": 300.0,
        "hold_time_sec": 0.0,
        "use_yaw": false,
        "yaw_deg": 0.0
      }
    ]
  }
}
```

### 6.3c 调用 UGV GPS 航点任务服务（`op=call_service`）

```json
{
  "op": "call_service",
  "service": "/ugv/execute_waypoint_mission_geo",
  "args": {
    "wait": false,
    "waypoints": [
      {
        "latitude": 40.002920,
        "longitude": 116.338360,
        "altitude_m": 0.0,
        "velocity_mps": 2.0,
        "timeout_sec": 300.0,
        "hold_time_sec": 0.0,
        "use_yaw": false,
        "yaw_deg": 0.0
      }
    ]
  },
  "id": "ugv_waypoint_1"
}
```

### 6.3d 订阅 UGV 任务状态（`op=subscribe`）

```json
{
  "op": "subscribe",
  "topic": "/ugv/state/mission_status",
  "type": "diagnostic_msgs/DiagnosticArray",
  "throttle_rate": 0,
  "queue_length": 1
}
```

### 6.4 订阅 UAV 下视相机（`op=subscribe`）

```json
{
  "op": "subscribe",
  "topic": "/uav/state/camera/downward/image/compressed",
  "type": "sensor_msgs/CompressedImage",
  "throttle_rate": 0,
  "queue_length": 1
}
```

说明：

- `msg.format` 固定为 `png`。
- `msg.data` 在 rosbridge JSON 传输中通常为 base64 字符串（客户端收到后按 PNG 解码即可）。

### 6.5 订阅 UAV 火灾检测结果（`op=subscribe`）
订阅请求：
```json
{
  "op": "subscribe",
  "topic": "/uav/state/fire_detection",
  "type": "airsim_uav_interfaces/FireDetectionResult",
  "throttle_rate": 0,
  "queue_length": 1
}
```

`airsim_uav_interfaces/FireDetectionResult` 数据结构：
okok表示本次检测结果是否有效

```text
std_msgs/Header header
bool okok
float64 fire_probability
float64 risk_level
int32 flame_count
float64 average_confidence
int32 detected_target_count
```

## 7. 构建与检查命令

```bash
source /opt/ros/humble/setup.bash
cd /home/th1rt3en/sim_ws/ros2_ws
colcon build --packages-select airsim_uav_interfaces airsim_uav_control ugv_airsim_bridge ugv_bringup --symlink-install
source install/setup.bash

ros2 interface show airsim_uav_interfaces/msg/GeoWaypoint
ros2 interface show airsim_uav_interfaces/msg/GeoWaypointMission
ros2 interface show airsim_uav_interfaces/srv/ExecuteGeoWaypointMission
```
