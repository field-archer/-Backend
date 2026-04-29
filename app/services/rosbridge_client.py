from __future__ import annotations

import asyncio
import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from config.config import config

ros_logger = logging.getLogger("forestfire.ros")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _quat_to_roll_pitch_deg(q: dict[str, Any]) -> tuple[Optional[float], Optional[float]]:
    """
    ROS Pose orientation quaternion -> roll/pitch degrees.
    Returns (roll, pitch); if missing/invalid returns (None, None).
    """
    try:
        x = float(q.get("x"))
        y = float(q.get("y"))
        z = float(q.get("z"))
        w = float(q.get("w"))
    except Exception:
        return None, None

    # Standard conversion
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    if abs(sinp) >= 1:
        pitch = math.copysign(math.pi / 2.0, sinp)
    else:
        pitch = math.asin(sinp)

    return math.degrees(roll), math.degrees(pitch)


def _diag_kv(diag: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    status = diag.get("status")
    if not isinstance(status, list) or not status:
        return out
    values = status[0].get("values") if isinstance(status[0], dict) else None
    if not isinstance(values, list):
        return out
    for item in values:
        if not isinstance(item, dict):
            continue
        k = str(item.get("key") or "").strip()
        v = str(item.get("value") or "").strip()
        if k:
            out[k] = v
    return out


@dataclass
class TelemetryState:
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    battery_pct: Optional[float] = None
    speed_mps: Optional[float] = None
    altitude_m: Optional[float] = None
    roll_deg: Optional[float] = None
    pitch_deg: Optional[float] = None
    status: Optional[str] = None


class RosbridgeClient:
    """
    Minimal rosbridge websocket client.
    Uses config.ROSBRIDGE_URL by default.
    """

    def __init__(self, url: Optional[str] = None) -> None:
        self.url = (url or config.ROSBRIDGE_URL).strip()
        self._ws = None
        self._recv_task: Optional[asyncio.Task] = None
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._recv_topic_counts: dict[str, int] = {}
        self._send_target_counts: dict[str, int] = {}

    def _bump(self, m: dict[str, int], key: str) -> int:
        n = int(m.get(key, 0)) + 1
        m[key] = n
        return n

    def _should_sample(self, n: int) -> bool:
        # log details on 1st message, then every 50th
        return n == 1 or (n % 50 == 0)

    def _summarize_msg(self, msg: Any) -> dict[str, Any]:
        if not isinstance(msg, dict):
            return {"_type": type(msg).__name__}
        keys = sorted([k for k in msg.keys() if isinstance(k, str)])
        sample: dict[str, Any] = {"_keys": keys[:20]}
        for k in (
            "mission_id",
            "wait_for_completion",
            "latitude",
            "longitude",
            "altitude_m",
            "data",
            "percentage",
            "fire_probability",
            "risk_level",
            "flame_count",
            "average_confidence",
            "detected_target_count",
            "fire_cause",
        ):
            if k in msg:
                sample[k] = msg.get(k)
        # common nested: msg.header.stamp
        header = msg.get("header")
        if isinstance(header, dict):
            stamp = header.get("stamp")
            if isinstance(stamp, dict):
                sample["_stamp"] = {
                    "sec": stamp.get("sec"),
                    "nanosec": stamp.get("nanosec"),
                }

        # helpful for mission messages
        wps = msg.get("waypoints")
        if isinstance(wps, list):
            sample["waypoints_len"] = len(wps)
            # Full waypoint logging for strict end-to-end verification.
            sample["waypoints_full"] = wps
        return sample

    async def connect(self) -> None:
        if not self.url:
            raise RuntimeError("ROSBRIDGE_URL is empty")
        try:
            import websockets  # type: ignore
        except Exception as e:
            raise RuntimeError("missing dependency: websockets") from e

        ros_logger.info("rosbridge connecting url=%s", self.url)
        self._ws = await websockets.connect(self.url, ping_interval=20, ping_timeout=20)
        ros_logger.info("rosbridge connected url=%s", self.url)
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
            self._recv_task = None
        if self._ws:
            try:
                await self._ws.close()
            finally:
                self._ws = None
        ros_logger.info("rosbridge closed url=%s", self.url)

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if isinstance(msg, dict):
                    op = msg.get("op")
                    if op == "publish":
                        topic = str(msg.get("topic") or "")
                        n = self._bump(self._recv_topic_counts, topic or "<empty-topic>")
                        if self._should_sample(n):
                            ros_logger.info(
                                "rosbridge recv publish topic=%s count=%d summary=%s",
                                topic,
                                n,
                                self._summarize_msg(msg.get("msg")),
                            )
                    await self._queue.put(msg)
        except asyncio.CancelledError:
            return
        except Exception:
            # let consumer detect via timeout/reconnect policy
            ros_logger.exception("rosbridge recv loop error url=%s", self.url)
            return

    async def recv(self) -> dict[str, Any]:
        return await self._queue.get()

    async def send(self, payload: dict[str, Any]) -> None:
        if not self._ws:
            raise RuntimeError("rosbridge not connected")
        op = payload.get("op")
        if op in ("publish", "subscribe", "call_service"):
            target = str(payload.get("topic") or payload.get("service") or "")
            n = self._bump(self._send_target_counts, f"{op}:{target}")
            if self._should_sample(n):
                ros_logger.info(
                    "rosbridge send op=%s target=%s count=%d summary=%s",
                    op,
                    target,
                    n,
                    self._summarize_msg(payload.get("msg") or payload.get("args")),
                )
        await self._ws.send(json.dumps(payload, ensure_ascii=False))

    async def subscribe(self, topic: str, type_: str, *, queue_length: int = 1) -> None:
        await self.send(
            {
                "op": "subscribe",
                "topic": topic,
                "type": type_,
                "throttle_rate": 0,
                "queue_length": queue_length,
            }
        )

    async def publish(self, topic: str, msg: dict[str, Any]) -> None:
        await self.send({"op": "publish", "topic": topic, "msg": msg})

    async def call_service(self, service: str, args: dict[str, Any], *, call_id: str) -> None:
        await self.send({"op": "call_service", "service": service, "args": args, "id": call_id})


def build_geo_waypoint_mission_msg(
    *,
    mission_id: str,
    waypoints: list[dict[str, Any]],
    wait_for_completion: bool = False,
) -> dict[str, Any]:
    return {
        "header": {"frame_id": "", "stamp": {"sec": 0, "nanosec": 0}},
        "mission_id": mission_id,
        "wait_for_completion": wait_for_completion,
        "waypoints": waypoints,
    }


def normalize_uav_waypoints_for_ros(
    items: list[dict[str, Any]],
    *,
    default_velocity_mps: float = 4.0,
    default_timeout_sec: float = 300.0,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for w in items:
        alt = w.get("altitude_m")
        if alt is None:
            alt = w.get("altitude")
        out.append(
            {
                "latitude": float(w["latitude"]),
                "longitude": float(w["longitude"]),
                "altitude_m": float(alt or 0.0),
                "velocity_mps": float(w.get("velocity_mps", default_velocity_mps)),
                "timeout_sec": float(w.get("timeout_sec", default_timeout_sec)),
                "hold_time_sec": float(w.get("hold_time_sec", 0.0)),
                "use_yaw": bool(w.get("use_yaw", False)),
                "yaw_deg": float(w.get("yaw_deg", 0.0)),
            }
        )
    return out


def message_to_uav_telemetry(
    state: TelemetryState,
    *,
    include_ts: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "longitude": state.longitude,
        "latitude": state.latitude,
        "battery": state.battery_pct,
        "speed": state.speed_mps,
        "altitude": state.altitude_m,
        "roll": state.roll_deg,
        "pitch": state.pitch_deg,
        "status": state.status,
    }
    if include_ts:
        payload["ts"] = _now_iso()
    return payload


def update_state_from_navsat(state: TelemetryState, msg: dict[str, Any]) -> None:
    try:
        state.latitude = float(msg.get("latitude"))
        state.longitude = float(msg.get("longitude"))
    except Exception:
        return


def update_state_from_altitude(state: TelemetryState, msg: dict[str, Any]) -> None:
    try:
        state.altitude_m = float(msg.get("data"))
    except Exception:
        return


def update_state_from_twist(state: TelemetryState, msg: dict[str, Any]) -> None:
    twist = msg.get("twist") if isinstance(msg.get("twist"), dict) else None
    linear = twist.get("linear") if isinstance(twist, dict) and isinstance(twist.get("linear"), dict) else None
    if not isinstance(linear, dict):
        return
    try:
        vx = float(linear.get("x", 0.0))
        vy = float(linear.get("y", 0.0))
        vz = float(linear.get("z", 0.0))
    except Exception:
        return
    state.speed_mps = math.sqrt(vx * vx + vy * vy + vz * vz)


def update_state_from_battery(state: TelemetryState, msg: dict[str, Any]) -> None:
    # sensor_msgs/BatteryState.percentage is 0..1; may be NaN
    try:
        pct = float(msg.get("percentage"))
    except Exception:
        return
    if math.isnan(pct):
        return
    if pct <= 1.0:
        state.battery_pct = max(0.0, min(100.0, pct * 100.0))
    else:
        state.battery_pct = max(0.0, min(100.0, pct))


def update_state_from_basic_status(state: TelemetryState, diag: dict[str, Any]) -> None:
    kv = _diag_kv(diag)
    bp = kv.get("battery_percentage")
    if bp:
        try:
            state.battery_pct = max(0.0, min(100.0, float(bp)))
        except Exception:
            pass
    sp = kv.get("speed_mps")
    if sp:
        try:
            state.speed_mps = float(sp)
        except Exception:
            pass
    landed = kv.get("landed")
    if landed is not None and landed != "":
        state.status = "landed" if landed.lower() in ("1", "true", "yes") else "flying"


def update_state_from_pose(state: TelemetryState, msg: dict[str, Any]) -> None:
    pose = msg.get("pose") if isinstance(msg.get("pose"), dict) else None
    ori = pose.get("orientation") if isinstance(pose, dict) and isinstance(pose.get("orientation"), dict) else None
    if not isinstance(ori, dict):
        return
    roll, pitch = _quat_to_roll_pitch_deg(ori)
    state.roll_deg = roll
    state.pitch_deg = pitch

