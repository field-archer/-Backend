from __future__ import annotations

import asyncio
import json
import math
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, TextIO

import websockets


def _now_stamp() -> dict[str, int]:
    t = time.time()
    sec = int(t)
    nanosec = int((t - sec) * 1_000_000_000)
    return {"sec": sec, "nanosec": nanosec}


def _navsat(latitude: float, longitude: float, altitude: float = 0.0) -> dict[str, Any]:
    return {
        "header": {"frame_id": "", "stamp": _now_stamp()},
        "latitude": float(latitude),
        "longitude": float(longitude),
        "altitude": float(altitude),
    }


def _float32(data: float) -> dict[str, Any]:
    return {"data": float(data)}


def _bool_msg(data: bool) -> dict[str, Any]:
    return {"data": bool(data)}


def _twist_stamped(vx: float, vy: float, vz: float = 0.0) -> dict[str, Any]:
    return {
        "header": {"frame_id": "", "stamp": _now_stamp()},
        "twist": {
            "linear": {"x": float(vx), "y": float(vy), "z": float(vz)},
            "angular": {"x": 0.0, "y": 0.0, "z": 0.0},
        },
    }


def _battery_state(percentage_0_1: float) -> dict[str, Any]:
    return {
        "header": {"frame_id": "", "stamp": _now_stamp()},
        "percentage": float(max(0.0, min(1.0, percentage_0_1))),
    }


def _pose_stamped_roll_pitch(roll_deg: float, pitch_deg: float) -> dict[str, Any]:
    r = math.radians(roll_deg)
    p = math.radians(pitch_deg)
    y = 0.0
    cy = math.cos(y * 0.5)
    sy = math.sin(y * 0.5)
    cp = math.cos(p * 0.5)
    sp = math.sin(p * 0.5)
    cr = math.cos(r * 0.5)
    sr = math.sin(r * 0.5)
    qw = cr * cp * cy + sr * sp * sy
    qx = sr * cp * cy - cr * sp * sy
    qy = cr * sp * cy + sr * cp * sy
    qz = cr * cp * sy - sr * sp * cy
    return {
        "header": {"frame_id": "", "stamp": _now_stamp()},
        "pose": {
            "position": {"x": 0.0, "y": 0.0, "z": 0.0},
            "orientation": {"x": qx, "y": qy, "z": qz, "w": qw},
        },
    }


# 航点数 > 5（即至少 6 个点）才发火焰检测；返航等短航线默认不发。
MIN_WAYPOINTS_FOR_FIRE_DETECTION = 6


def _fire_last_leg_midpoint(path: list[tuple[float, float, float]]) -> tuple[float, float]:
    """唯一火点：倒数第二航点 → 最后一航点 线段中点（GCJ-02）。"""
    if len(path) >= 2:
        la0, lo0, _ = path[-2]
        la1, lo1, _ = path[-1]
        return ((la0 + la1) * 0.5, (lo0 + lo1) * 0.5)
    return (float(path[0][0]), float(path[0][1]))


def _fire_detection_at(latitude: float, longitude: float) -> dict[str, Any]:
    """
    仅用于末段中点「几何火点」：必须由 _fire_last_leg_midpoint 算出的坐标传入。
    禁止把无人机当前位姿 self.lat/lng 写入火检，否则会在末航点/扫描悬停处误标点。
    后端 uav.detection 会优先使用本消息中的 latitude/longitude 推给前端，前端再 POST 火点标记。
    flame_count=1、fire_cause=unknown；火灾概率 / 风险等级 / 平均置信度每次随机（机载 float 语义）。
    """
    fp = random.uniform(0.50, 0.98)
    risk = random.uniform(0.10, 0.95)
    c_lo = max(0.12, fp - random.uniform(0.04, 0.20))
    c_hi = min(0.99, fp + random.uniform(0.02, 0.14))
    if c_lo > c_hi:
        c_lo, c_hi = c_hi, c_lo
    ac = random.uniform(c_lo, c_hi)
    return {
        "header": {"frame_id": "", "stamp": _now_stamp()},
        "okok": True,
        "fire_probability": fp,
        "risk_level": risk,
        "flame_count": 1,
        "average_confidence": ac,
        "detected_target_count": 1,
        "fire_cause": "unknown",
        "latitude": float(latitude),
        "longitude": float(longitude),
    }


def _safe_mission_id(raw: str) -> str:
    s = (raw or "").strip() or "no_mission_id"
    s2 = re.sub(r"[^\w.-]+", "_", s)
    return s2[:100]


def _uav_mission_log_finished(u: "UavSim") -> bool:
    """任务结束：已落地、非扫描；若启用火检则须已发出，否则视为已完成。"""
    if len(u.path) < 2:
        return False
    fire_ok = u.fire_last_leg_reported if u.fire_detection_enabled else True
    return bool(u.landed and not u.scan_phase and not u.active and fire_ok)


def _segment_length_m_ned(
    la0: float, lo0: float, al0: float, la1: float, lo1: float, al1: float
) -> tuple[float, float, float, float]:
    """
    航段在局部切平面上的位移（米）与长度，用于严格 30 m/s 沿航点弦线运动。
    NED：x 北、y 东、z 下；高度 al 为正向上，故 delta_z_ned = -(al1 - al0)。
    """
    dlat = la1 - la0
    dlon = lo1 - lo0
    dalt = al1 - al0
    nx = dlat * 111_320.0
    ny = dlon * 111_320.0 * math.cos(math.radians(la0))
    nz = -dalt
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    return (nx, ny, nz, length)


class UavFlightJsonlWriter:
    """
    每次 UAV 航点任务写一份 JSONL，便于真机/仿真按时间轴复刻 publish 数据。
    目录：环境变量 MOCK_UAV_FLIGHT_LOG_DIR，默认 mock_uav/flight_logs/
    """

    def __init__(self) -> None:
        default_dir = Path(__file__).resolve().parent / "flight_logs"
        self._dir = Path(os.environ.get("MOCK_UAV_FLIGHT_LOG_DIR", str(default_dir)))
        self._fp: Optional[TextIO] = None
        self._t0 = 0.0

    @property
    def active(self) -> bool:
        return self._fp is not None

    def start(self, mission_id: str, mission_body: dict[str, Any], uav: "UavSim") -> None:
        self.close()
        if len(uav.path) < 2:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        mid = _safe_mission_id(mission_id)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = self._dir / f"uav_{mid}_{ts}.jsonl"
        self._fp = open(path, "w", encoding="utf-8")
        self._t0 = time.time()
        print(f"[mock_uav] flight log -> {path}", flush=True)
        wps = mission_body.get("waypoints")
        mission_line = {
            "event": "mission",
            "wall_time_unix": self._t0,
            "wall_time_utc": datetime.now(timezone.utc).isoformat(),
            "mission_id": mission_id,
            "wait_for_completion": mission_body.get("wait_for_completion"),
            "waypoints_ros": wps if isinstance(wps, list) else [],
            "resolved_path_lat_lng_alt_m": [[p[0], p[1], p[2]] for p in uav.path],
            "fire_detection_enabled": uav.fire_detection_enabled,
            "fire_last_leg_mid_lat_lng": (
                [uav.fire_last_leg_lat, uav.fire_last_leg_lng] if uav.fire_detection_enabled else None
            ),
            "tick_rate_hz": 5.0,
            "note": "tick 可按 t_mission_s 复刻；UAV 航点间沿 3D 弦线 30 m/s；relative_altitude_m；twist NED m/s；pose 由 roll_deg/pitch_deg 生成。",
        }
        self._fp.write(json.dumps(mission_line, ensure_ascii=False) + "\n")
        self._fp.flush()

    def tick(
        self,
        uav: "UavSim",
        *,
        roll_deg: float,
        pitch_deg: float,
        landed_pub: bool,
        vx: float,
        vy: float,
        vz: float,
    ) -> None:
        if not self._fp:
            return
        line = {
            "event": "tick",
            "t_mission_s": round(time.time() - self._t0, 3),
            "latitude": uav.lat,
            "longitude": uav.lng,
            "relative_altitude_m": uav.alt,
            "twist_linear_ned_mps": {"x": vx, "y": vy, "z": vz},
            "roll_deg": roll_deg,
            "pitch_deg": pitch_deg,
            "battery_fraction": uav.batt,
            "landed_published": landed_pub,
            "scan_phase": uav.scan_phase,
            "seg_index": uav.seg_i,
            "seg_u": round(uav.seg_u, 4),
        }
        self._fp.write(json.dumps(line, ensure_ascii=False) + "\n")
        self._fp.flush()

    def fire_detection(self, msg: dict[str, Any]) -> None:
        if not self._fp:
            return
        line = {
            "event": "fire_detection",
            "t_mission_s": round(time.time() - self._t0, 3),
            "msg": msg,
        }
        self._fp.write(json.dumps(line, ensure_ascii=False) + "\n")
        self._fp.flush()

    def end(self) -> None:
        if not self._fp:
            return
        line = {"event": "mission_end", "t_mission_s": round(time.time() - self._t0, 3)}
        self._fp.write(json.dumps(line, ensure_ascii=False) + "\n")
        self._fp.flush()
        self.close()

    def close(self) -> None:
        if self._fp:
            try:
                self._fp.close()
            except Exception:
                pass
            self._fp = None


def _diagnostic_array(values: dict[str, str]) -> dict[str, Any]:
    return {
        "header": {"frame_id": "", "stamp": _now_stamp()},
        "status": [
            {
                "name": "",
                "level": 0,
                "message": "",
                "hardware_id": "",
                "values": [{"key": k, "value": v} for k, v in values.items()],
            }
        ],
    }


@dataclass
class ClientSubs:
    topics: set[str] = field(default_factory=set)


@dataclass
class UavSim:
    # 初始位置（GCJ-02）：经度 116.255813, 纬度 40.029607
    lat: float = 40.029607
    lng: float = 116.255813
    alt: float = 80.0
    batt: float = 0.85
    landed: bool = True

    path: list[tuple[float, float, float]] = field(default_factory=list)
    seg_i: int = 0
    seg_u: float = 0.0
    active: bool = False
    scan_phase: bool = False
    scan_total: int = 0
    scan_left: int = 0
    scan_last_t: float = 0.0
    scan_center_lat: float = 0.0
    scan_center_lng: float = 0.0
    scan_orbit: float = 0.0
    scan_done_for_mission: bool = False
    fire_last_leg_lat: float = 0.0
    fire_last_leg_lng: float = 0.0
    fire_last_leg_reported: bool = False
    fire_detection_enabled: bool = False
    pending_scan_fires: list[tuple[float, float]] = field(default_factory=list)

    mission_id: str = ""

    def set_mission(self, waypoints: list[dict[str, Any]], mission_id: str = "") -> None:
        path: list[tuple[float, float, float]] = []
        for wp in waypoints:
            if not isinstance(wp, dict):
                continue
            try:
                path.append(
                    (
                        float(wp["latitude"]),
                        float(wp["longitude"]),
                        float(wp.get("altitude_m", self.alt)),
                    )
                )
            except Exception:
                continue
        if not path:
            return
        self.mission_id = str(mission_id or "")
        self.path = path
        self.seg_i = 0
        self.seg_u = 0.0
        self.active = True
        self.scan_phase = False
        self.scan_total = 0
        self.scan_left = 0
        self.scan_last_t = 0.0
        self.scan_orbit = 0.0
        self.pending_scan_fires = []
        self.landed = False
        self.lat, self.lng, self.alt = path[0]

        self.fire_detection_enabled = len(path) >= MIN_WAYPOINTS_FOR_FIRE_DETECTION
        if self.fire_detection_enabled:
            self.fire_last_leg_lat, self.fire_last_leg_lng = _fire_last_leg_midpoint(path)
            self.fire_last_leg_reported = False
            self.scan_done_for_mission = False
            print(
                "[mock_uav] fire site (detection only, not UAV pose): "
                f"last_leg_mid=({self.fire_last_leg_lat:.6f},{self.fire_last_leg_lng:.6f}) "
                f"last_wp=({path[-1][0]:.6f},{path[-1][1]:.6f}) waypoints={len(path)}",
                flush=True,
            )
        else:
            self.fire_last_leg_lat, self.fire_last_leg_lng = 0.0, 0.0
            self.fire_last_leg_reported = True
            self.scan_done_for_mission = True
            print(
                f"[mock_uav] fire_detection disabled (need >5 waypoints, got {len(path)})",
                flush=True,
            )

    def try_emit_inflight_fires(self, old_seg_i: int, old_seg_u: float) -> list[dict[str, Any]]:
        """航迹途中：末段（倒数第二→末点）飞过中点时发唯一火检。"""
        out: list[dict[str, Any]] = []
        if not self.fire_detection_enabled or self.scan_phase or len(self.path) < 2:
            return out

        last_leg_i = len(self.path) - 2
        if not self.fire_last_leg_reported and old_seg_i == last_leg_i:
            crossed_mid = old_seg_u < 0.5 and (self.seg_u >= 0.5 or self.seg_i > last_leg_i)
            if crossed_mid:
                self.fire_last_leg_reported = True
                out.append(_fire_detection_at(self.fire_last_leg_lat, self.fire_last_leg_lng))

        return out

    def turn_intensity(self) -> float:
        """
        估计当前是否处于转弯过程，返回 0~1。
        - 直线巡航：接近 0（roll/pitch 控制在小范围）
        - 临近航点且下一段方向变化明显：升高到接近 1
        """
        if (not self.active) or self.scan_phase or len(self.path) < 3:
            return 0.0
        i = self.seg_i
        if i < 0 or i >= len(self.path) - 1:
            return 0.0

        def _dir2(a: tuple[float, float, float], b: tuple[float, float, float]) -> tuple[float, float]:
            nx, ny, _, seg_len = _segment_length_m_ned(a[0], a[1], a[2], b[0], b[1], b[2])
            if seg_len < 1e-6:
                return (0.0, 0.0)
            return (nx / seg_len, ny / seg_len)

        # approach current->next turn
        near_end = 0.0
        if i + 2 < len(self.path):
            d1 = _dir2(self.path[i], self.path[i + 1])
            d2 = _dir2(self.path[i + 1], self.path[i + 2])
            dot = max(-1.0, min(1.0, d1[0] * d2[0] + d1[1] * d2[1]))
            angle_factor = math.acos(dot) / math.pi  # 0..1
            gate_end = max(0.0, min(1.0, (self.seg_u - 0.78) / 0.22))
            near_end = angle_factor * gate_end

        # just-exited previous turn
        near_start = 0.0
        if i - 1 >= 0:
            d0 = _dir2(self.path[i - 1], self.path[i])
            d1 = _dir2(self.path[i], self.path[i + 1])
            dot = max(-1.0, min(1.0, d0[0] * d1[0] + d0[1] * d1[1]))
            angle_factor = math.acos(dot) / math.pi
            gate_start = max(0.0, min(1.0, (0.25 - self.seg_u) / 0.25))
            near_start = angle_factor * gate_start

        return max(near_end, near_start)

    def step(self, dt: float) -> tuple[float, float, float]:
        # Returns approximate NED velocity for TwistStamped
        if self.scan_phase:
            # 悬停扫描：小半径绕圈，速度接近 0（Twist 近似静止）
            self.scan_orbit += dt
            r = 0.00008
            self.lat = self.scan_center_lat + r * math.sin(self.scan_orbit * 0.8)
            self.lng = self.scan_center_lng + r * math.cos(self.scan_orbit * 0.8)
            return (0.0, 0.0, 0.0)

        if not self.active or len(self.path) < 2:
            return (0.0, 0.0, 0.0)
        if self.seg_i >= len(self.path) - 1:
            self.active = False
            self.landed = True
            return (0.0, 0.0, 0.0)

        speed_mps = 30.0
        dist_remaining = speed_mps * dt
        nx = ny = nz = 0.0
        seg_len = 1.0
        la0 = lo0 = al0 = la1 = lo1 = al1 = 0.0

        while dist_remaining > 1e-12:
            if self.seg_i >= len(self.path) - 1:
                self.lat, self.lng, self.alt = self.path[-1]
                self.active = False
                self.landed = True
                return (0.0, 0.0, 0.0)

            la0, lo0, al0 = self.path[self.seg_i]
            la1, lo1, al1 = self.path[self.seg_i + 1]
            nx, ny, nz, seg_len = _segment_length_m_ned(la0, lo0, al0, la1, lo1, al1)
            if seg_len < 0.05:
                self.seg_i += 1
                self.seg_u = 0.0
                continue

            along_m = self.seg_u * seg_len + dist_remaining
            if along_m < seg_len - 1e-9:
                self.seg_u = along_m / seg_len
                dist_remaining = 0.0
                break

            dist_remaining = along_m - seg_len
            self.seg_i += 1
            self.seg_u = 0.0
            if self.seg_i >= len(self.path) - 1:
                self.lat, self.lng, self.alt = self.path[-1]
                self.active = False
                self.landed = True
                return (0.0, 0.0, 0.0)

        u = self.seg_u
        self.lat = la0 + (la1 - la0) * u
        self.lng = lo0 + (lo1 - lo0) * u
        self.alt = al0 + (al1 - al0) * u

        inv = 1.0 / seg_len
        vx = speed_mps * nx * inv
        vy = speed_mps * ny * inv
        vz = speed_mps * nz * inv
        return (vx, vy, vz)

    def begin_scan_if_needed(self) -> None:
        if self.scan_phase or self.scan_done_for_mission:
            return
        if not self.fire_detection_enabled:
            return
        if not self.landed or not self.path:
            return
        if len(self.path) < 2:
            return
        pending: list[tuple[float, float]] = []
        if not self.fire_last_leg_reported:
            pending.append((self.fire_last_leg_lat, self.fire_last_leg_lng))
        if not pending:
            self.scan_done_for_mission = True
            return
        self.scan_center_lat = float(self.lat)
        self.scan_center_lng = float(self.lng)
        self.landed = False
        self.scan_phase = True
        self.pending_scan_fires = pending
        self.scan_total = len(pending)
        self.scan_left = self.scan_total
        self.scan_last_t = 0.0
        self.scan_orbit = 0.0
        self.scan_done_for_mission = True

    def maybe_emit_detection(self, now: float) -> dict[str, Any] | None:
        # 仅补发航迹上未触发的火检；坐标仍来自预计算点，不用机体位姿。
        if not self.scan_phase or self.scan_left <= 0 or not self.pending_scan_fires:
            return None
        if self.scan_last_t == 0.0:
            self.scan_last_t = now
            return None
        if now - self.scan_last_t < 0.45:
            return None
        self.scan_last_t = now
        self.scan_left -= 1
        site_i = self.scan_total - self.scan_left - 1
        site_i = max(0, min(site_i, len(self.pending_scan_fires) - 1))
        lat0, lng0 = self.pending_scan_fires[site_i]
        self.fire_last_leg_reported = True
        msg = _fire_detection_at(lat0, lng0)
        if self.scan_left <= 0:
            self.scan_phase = False
            self.landed = True
            self.pending_scan_fires = []
        return msg


@dataclass
class UgvSim:
    lat: float = 40.029607
    lng: float = 116.255813
    batt: float = 0.75

    mission_id: str = ""
    path: list[tuple[float, float]] = field(default_factory=list)
    seg_i: int = 0
    seg_u: float = 0.0
    active: bool = False
    arrived_sent: bool = False

    def set_mission(self, mission_id: str, waypoints: list[dict[str, Any]]) -> None:
        path: list[tuple[float, float]] = []
        for wp in waypoints:
            if not isinstance(wp, dict):
                continue
            try:
                path.append((float(wp["latitude"]), float(wp["longitude"])))
            except Exception:
                continue
        if not path:
            return
        self.mission_id = mission_id
        self.path = path
        self.seg_i = 0
        self.seg_u = 0.0
        self.active = True
        self.arrived_sent = False
        self.lat, self.lng = path[0]

    def step(self, dt: float) -> None:
        if not self.active or len(self.path) < 2:
            return
        if self.seg_i >= len(self.path) - 1:
            self.active = False
            return
        la0, lo0 = self.path[self.seg_i]
        la1, lo1 = self.path[self.seg_i + 1]
        seg_seconds = 2.0
        self.seg_u = min(1.0, self.seg_u + dt / seg_seconds)
        u = self.seg_u
        self.lat = la0 + (la1 - la0) * u
        self.lng = lo0 + (lo1 - lo0) * u
        if self.seg_u >= 1.0 - 1e-9:
            self.seg_u = 0.0
            self.seg_i += 1
            if self.seg_i >= len(self.path) - 1:
                self.lat, self.lng = self.path[-1]
                self.active = False


class MockRosbridgeUavServer:
    def __init__(self) -> None:
        self.clients: dict[Any, ClientSubs] = {}
        self.uav = UavSim()
        self.ugv = UgvSim()
        self._flight_log = UavFlightJsonlWriter()
        self._smooth_roll_deg = 0.0
        self._smooth_pitch_deg = 0.0

    async def handler(self, ws: Any) -> None:
        self.clients[ws] = ClientSubs()
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if not isinstance(msg, dict):
                    continue
                op = msg.get("op")
                if op == "subscribe":
                    topic = str(msg.get("topic") or "")
                    if topic:
                        self.clients[ws].topics.add(topic)
                elif op == "unsubscribe":
                    topic = str(msg.get("topic") or "")
                    self.clients[ws].topics.discard(topic)
                elif op == "publish":
                    await self._on_publish(msg)
                elif op == "call_service":
                    await self._on_call_service(ws, msg)
        finally:
            self.clients.pop(ws, None)

    async def _on_call_service(self, ws: Any, msg: dict[str, Any]) -> None:
        call_id = str(msg.get("id") or "")
        await ws.send(
            json.dumps(
                {
                    "op": "service_response",
                    "service": msg.get("service"),
                    "values": {"success": True, "completed_waypoints": 0, "message": "mock ok"},
                    "result": True,
                    "id": call_id,
                },
                ensure_ascii=False,
            )
        )

    async def _on_publish(self, msg: dict[str, Any]) -> None:
        topic = str(msg.get("topic") or "")
        body = msg.get("msg")
        if topic == "/uav/cmd/waypoint_mission" and isinstance(body, dict):
            wps = body.get("waypoints")
            mid = str(body.get("mission_id") or "")
            if isinstance(wps, list) and wps:
                self.uav.set_mission(wps, mid)
                self._smooth_roll_deg = 0.0
                self._smooth_pitch_deg = 0.0
                if len(self.uav.path) >= 2:
                    self._flight_log.start(mid, body, self.uav)
        if topic == "/ugv/cmd/waypoint_mission_geo" and isinstance(body, dict):
            mission_id = str(body.get("mission_id") or "")
            wps = body.get("waypoints")
            if isinstance(wps, list) and wps:
                self.ugv.set_mission(mission_id, wps)

    async def _broadcast_publish(self, topic: str, ros_msg: dict[str, Any]) -> None:
        raw = json.dumps({"op": "publish", "topic": topic, "msg": ros_msg}, ensure_ascii=False)
        dead: list[Any] = []
        for ws, subs in self.clients.items():
            if topic not in subs.topics:
                continue
            try:
                await ws.send(raw)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.pop(ws, None)

    async def tick_loop(self) -> None:
        dt = 0.2  # 5Hz
        t0 = time.time()
        while True:
            await asyncio.sleep(dt)
            u = self.uav
            old_seg_i, old_seg_u = u.seg_i, u.seg_u
            vx, vy, vz = u.step(dt)
            for inf in u.try_emit_inflight_fires(old_seg_i, old_seg_u):
                await self._broadcast_publish("/uav/state/fire_detection", inf)
                if self._flight_log.active:
                    self._flight_log.fire_detection(inf)
            u.begin_scan_if_needed()

            # battery drain
            airborne = (not u.landed) or u.scan_phase
            u.batt = max(0.2, u.batt - (0.0003 if airborne else 0.00005))

            tt = time.time() - t0
            if u.scan_phase or (not u.landed):
                turn = u.turn_intensity()
                # 直线巡航：控制在约 ±1 度；转弯时按 turn 放大波动
                base_roll = 0.9 * math.sin(tt * 0.75)
                base_pitch = 0.9 * math.cos(tt * 0.72)
                burst_roll = turn * (10.0 * math.sin(tt * 2.2) + 4.0 * math.sin(tt * 3.8))
                burst_pitch = turn * (9.0 * math.cos(tt * 2.0) + 4.0 * math.sin(tt * 3.5))
                raw_roll = base_roll + burst_roll
                raw_pitch = base_pitch + burst_pitch
                tau = 1.0
            else:
                raw_roll = 0.15 * math.sin(tt * 0.4)
                raw_pitch = 0.15 * math.cos(tt * 0.38)
                tau = 2.0
            alpha = 1.0 - math.exp(-dt / tau)
            self._smooth_roll_deg += alpha * (raw_roll - self._smooth_roll_deg)
            self._smooth_pitch_deg += alpha * (raw_pitch - self._smooth_pitch_deg)
            roll = self._smooth_roll_deg
            pitch = self._smooth_pitch_deg

            landed_msg = u.landed and not u.scan_phase
            await self._broadcast_publish("/uav/state/landed", _bool_msg(landed_msg))
            await self._broadcast_publish("/uav/state/global_position", _navsat(u.lat, u.lng, 0.0))
            await self._broadcast_publish("/uav/state/relative_altitude", _float32(u.alt))
            await self._broadcast_publish("/uav/state/local_twist_ned", _twist_stamped(vx, vy, vz))
            await self._broadcast_publish("/uav/state/battery", _battery_state(u.batt))
            await self._broadcast_publish("/uav/state/local_pose_ned", _pose_stamped_roll_pitch(roll, pitch))

            if self._flight_log.active:
                self._flight_log.tick(
                    u,
                    roll_deg=roll,
                    pitch_deg=pitch,
                    landed_pub=landed_msg,
                    vx=vx,
                    vy=vy,
                    vz=vz,
                )

            now = time.time()
            det = u.maybe_emit_detection(now)
            if det is not None:
                await self._broadcast_publish("/uav/state/fire_detection", det)
                if self._flight_log.active:
                    self._flight_log.fire_detection(det)

            if self._flight_log.active and _uav_mission_log_finished(u):
                self._flight_log.end()

            # ---- UGV simulation (fleet) ----
            g = self.ugv
            g.step(dt)
            g.batt = max(0.2, g.batt - (0.00015 if g.active else 0.00005))

            await self._broadcast_publish("/ugv/state/global_position", _navsat(g.lat, g.lng, 0.0))
            await self._broadcast_publish("/ugv/state/battery", _battery_state(g.batt))
            await self._broadcast_publish(
                "/ugv/state/basic_status",
                _diagnostic_array(
                    {
                        "vehicle_name": "ugv",
                        "speed_mps": "1.2" if g.active else "0.0",
                        "battery_percentage": f"{g.batt*100:.1f}",
                    }
                ),
            )
            if (not g.active) and g.path and (not g.arrived_sent):
                g.arrived_sent = True
                await self._broadcast_publish(
                    "/ugv/state/mission_status",
                    _diagnostic_array(
                        {
                            "mission_id": g.mission_id,
                            "state": "arrived",
                            "arrived": "true",
                            "completed_waypoints": str(max(1, len(g.path))),
                            "message": "mock arrived",
                            "ts": str(time.time()),
                        }
                    ),
                )


async def main() -> None:
    host = "127.0.0.1"
    port = int(os.getenv("MOCK_UAV_PORT", "9090"))
    server = MockRosbridgeUavServer()
    async with websockets.serve(server.handler, host, port, ping_interval=20, ping_timeout=20):
        print(f"[mock_uav] rosbridge listening on ws://{host}:{port}", flush=True)
        await server.tick_loop()


if __name__ == "__main__":
    asyncio.run(main())

