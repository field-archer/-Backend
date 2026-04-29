from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.core.errors import ApiError
from app.core.security import decode_token_sub
from app.database import get_db
from app.models.user import User
from app.schemas.uav import UavMissionCreateBody, UavMissionCreateOut
from app.services.rosbridge_client import (
    RosbridgeClient,
    TelemetryState,
    ros_logger,
    build_geo_waypoint_mission_msg,
    message_to_uav_telemetry,
    normalize_uav_waypoints_for_ros,
    update_state_from_altitude,
    update_state_from_basic_status,
    update_state_from_battery,
    update_state_from_navsat,
    update_state_from_pose,
    update_state_from_twist,
)

router = APIRouter(prefix="/uav", tags=["uav"])
ws_router = APIRouter(tags=["uav-ws"])
logger = logging.getLogger(__name__)


def _ws_fire_cause_normalized(raw: Any) -> str:
    if not isinstance(raw, str):
        return "unknown"
    s = raw.strip().lower()
    if s in ("human", "lightning", "farming", "unknown"):
        return s
    return "unknown"


def _ws_fire_count_from_detection(ros_msg: dict[str, Any]) -> int:
    for key in ("flame_count", "detected_target_count"):
        v = ros_msg.get(key)
        try:
            n = int(v)
            if n >= 1:
                return n
        except (TypeError, ValueError):
            continue
    return 1


def _ws_level_from_risk(risk: Any) -> str:
    """ROS risk_level 多为 0～1 浮点；与 POST /api/fire-markers 的 level 枚举对齐。"""
    if isinstance(risk, str):
        s = risk.strip().lower()
        if s in ("low", "medium", "high"):
            return s
    try:
        x = float(risk)
    except (TypeError, ValueError):
        return "low"
    if x >= 0.67:
        return "high"
    if x >= 0.34:
        return "medium"
    return "low"


@router.post("/missions")
async def create_uav_mission(
    body: UavMissionCreateBody,
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    mission_id = uuid.uuid4().hex

    speed_map = {"low": 2.0, "medium": 4.0, "high": 6.0}
    default_v = speed_map.get(body.speed_level or "medium", 4.0)
    ros_waypoints = normalize_uav_waypoints_for_ros(
        [w.model_dump() for w in body.waypoints],
        default_velocity_mps=default_v,
    )
    msg = build_geo_waypoint_mission_msg(mission_id=mission_id, waypoints=ros_waypoints, wait_for_completion=False)

    client = RosbridgeClient()
    try:
        ros_logger.info("mission dispatch start type=%s mission_id=%s waypoints=%d", body.mission_type, mission_id, len(ros_waypoints))
        await client.connect()
        if body.mission_type == "uav":
            await client.publish("/uav/cmd/waypoint_mission", msg)
        else:
            # fleet
            await client.publish("/ugv/cmd/waypoint_mission_geo", msg)
        ros_logger.info("mission dispatch ok type=%s mission_id=%s", body.mission_type, mission_id)
    except Exception as e:
        ros_logger.exception("mission dispatch failed type=%s mission_id=%s", body.mission_type, mission_id)
        raise ApiError(50002, f"rosbridge 任务下发失败: {e!s}", http_status=200) from None
    finally:
        await client.close()

    data = UavMissionCreateOut(mission_id=mission_id)
    return {"code": 20000, "message": "成功", "data": data.model_dump()}


def _ws_auth_user(token: str, db: Session) -> User:
    if not token:
        raise ApiError(40100, "未授权或令牌无效", http_status=401)
    try:
        user_id = decode_token_sub(token)
    except ValueError:
        raise ApiError(40100, "未授权或令牌无效", http_status=401) from None
    user = db.get(User, user_id)
    if user is None:
        raise ApiError(40100, "未授权或令牌无效", http_status=401)
    return user


async def _ws_send(websocket: WebSocket, type_: str, payload: dict[str, Any]) -> None:
    await websocket.send_json({"type": type_, "payload": payload})


@ws_router.websocket("/ws/uav")
async def ws_uav(
    websocket: WebSocket,
    token: str = Query("", description="access_token（JWT）"),
    db: Session = Depends(get_db),
) -> None:
    # Auth before accept? FastAPI requires accept before send; we can accept then close with code.
    await websocket.accept()
    try:
        _ws_auth_user(token, db)
    except ApiError as e:
        await websocket.send_json({"type": "error", "payload": {"code": e.code, "message": e.message}})
        await websocket.close(code=1008)
        return

    client = RosbridgeClient()
    try:
        await client.connect()
    except Exception as e:
        await websocket.send_json(
            {
                "type": "error",
                "payload": {"code": 50002, "message": f"rosbridge 连接失败: {e!s}"},
            }
        )
        await websocket.close(code=1011)
        return

    ros_logger.info("ws/uav connected")

    # Subscriptions (minimal set)
    subs = [
        ("/uav/state/global_position", "sensor_msgs/NavSatFix"),
        ("/uav/state/relative_altitude", "std_msgs/Float32"),
        ("/uav/state/local_twist_ned", "geometry_msgs/TwistStamped"),
        ("/uav/state/local_pose_ned", "geometry_msgs/PoseStamped"),
        ("/uav/state/battery", "sensor_msgs/BatteryState"),
        ("/uav/state/basic_status", "diagnostic_msgs/DiagnosticArray"),
        ("/uav/state/landed", "std_msgs/Bool"),
        ("/uav/state/fire_detection", "airsim_uav_interfaces/FireDetectionResult"),
        ("/ugv/state/global_position", "sensor_msgs/NavSatFix"),
        ("/ugv/state/battery", "sensor_msgs/BatteryState"),
        ("/ugv/state/basic_status", "diagnostic_msgs/DiagnosticArray"),
        ("/ugv/state/mission_status", "diagnostic_msgs/DiagnosticArray"),
    ]
    for topic, t in subs:
        try:
            await client.subscribe(topic, t, queue_length=1)
        except Exception:
            # ignore single subscribe failure; still keep connection
            ros_logger.warning("subscribe failed topic=%s type=%s", topic, t)
            pass

    uav_state = TelemetryState()
    ugv_state = TelemetryState()
    last_uav_push = 0.0
    last_ugv_push = 0.0

    async def _heartbeat() -> None:
        while True:
            await asyncio.sleep(20.0)
            try:
                await websocket.send_json({"type": "ping", "payload": {"ts": None}})
            except Exception:
                return

    hb_task = asyncio.create_task(_heartbeat())

    try:
        while True:
            # Frontend messages are ignored (server push only)
            try:
                # Non-blocking check if frontend disconnected
                await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break
            except Exception:
                # ignore other recv errors
                pass

            msg = await client.recv()
            if msg.get("op") != "publish":
                continue
            topic = str(msg.get("topic") or "")
            ros_msg = msg.get("msg")
            if not isinstance(ros_msg, dict):
                continue

            now = asyncio.get_event_loop().time()

            # UAV
            if topic == "/uav/state/global_position":
                update_state_from_navsat(uav_state, ros_msg)
            elif topic == "/uav/state/relative_altitude":
                update_state_from_altitude(uav_state, ros_msg)
            elif topic == "/uav/state/local_twist_ned":
                update_state_from_twist(uav_state, ros_msg)
            elif topic == "/uav/state/local_pose_ned":
                update_state_from_pose(uav_state, ros_msg)
            elif topic == "/uav/state/battery":
                update_state_from_battery(uav_state, ros_msg)
            elif topic == "/uav/state/basic_status":
                update_state_from_basic_status(uav_state, ros_msg)
            elif topic == "/uav/state/landed":
                try:
                    uav_state.status = "landed" if bool(ros_msg.get("data")) else (uav_state.status or "flying")
                except Exception:
                    pass
            elif topic == "/uav/state/fire_detection":
                # map to uav.detection + GPS（消息内带经纬度时优先，便于 mock/机载解算火点）
                lat_out, lng_out = uav_state.latitude, uav_state.longitude
                try:
                    mlat = ros_msg.get("latitude")
                    mlng = ros_msg.get("longitude")
                    if mlat is not None and mlng is not None:
                        lat_out = float(mlat)
                        lng_out = float(mlng)
                except Exception:
                    pass
                if lat_out is None or lng_out is None:
                    ros_logger.warning(
                        "skip uav.detection: missing coordinates ros_lat=%s ros_lng=%s state_lat=%s state_lng=%s",
                        ros_msg.get("latitude"),
                        ros_msg.get("longitude"),
                        uav_state.latitude,
                        uav_state.longitude,
                    )
                else:
                    fc_raw = ros_msg.get("fire_cause")
                    fc = _ws_fire_cause_normalized(fc_raw)
                    risk = ros_msg.get("risk_level")
                    fcount = _ws_fire_count_from_detection(ros_msg)
                    level = _ws_level_from_risk(risk)
                    payload = {
                        "fire_probability": ros_msg.get("fire_probability"),
                        "risk_level": risk,
                        "flame_count": ros_msg.get("flame_count"),
                        "average_confidence": ros_msg.get("average_confidence"),
                        "detected_target_count": ros_msg.get("detected_target_count"),
                        "longitude": lng_out,
                        "latitude": lat_out,
                        "fire_cause": fc,
                        "ts": datetime.now(timezone.utc).isoformat(),
                        # 与 POST /api/fire-markers（FireMarkerCreate）字段对齐，减少前端映射错误
                        "fire_count": fcount,
                        "level": level,
                        "cause": fc,
                    }
                    await _ws_send(websocket, "uav.detection", payload)
                    ros_logger.info(
                        "push uav.detection lat=%s lng=%s fire_count=%s level=%s cause=%s",
                        payload.get("latitude"),
                        payload.get("longitude"),
                        payload.get("fire_count"),
                        payload.get("level"),
                        payload.get("cause"),
                    )

            # UGV
            if topic == "/ugv/state/global_position":
                update_state_from_navsat(ugv_state, ros_msg)
            elif topic == "/ugv/state/battery":
                update_state_from_battery(ugv_state, ros_msg)
            elif topic == "/ugv/state/basic_status":
                update_state_from_basic_status(ugv_state, ros_msg)
                ugv_state.status = ugv_state.status or "moving"
            elif topic == "/ugv/state/mission_status":
                kv = {}
                try:
                    from app.services.rosbridge_client import _diag_kv  # local import to reuse parser

                    kv = _diag_kv(ros_msg)
                except Exception:
                    kv = {}
                arrived = kv.get("arrived")
                state = kv.get("state") or ""
                if (arrived and arrived.lower() in ("1", "true", "yes")) or state == "arrived":
                    await _ws_send(
                        websocket,
                        "fleet.arrived",
                        {
                            "arrived": True,
                            "mission_id": kv.get("mission_id") or "",
                            "ts": kv.get("ts") or None,
                        },
                    )
                    ros_logger.info("push fleet.arrived mission_id=%s", kv.get("mission_id") or "")

            # Throttle telemetry pushes to 5Hz
            if now - last_uav_push >= 0.2 and uav_state.longitude is not None and uav_state.latitude is not None:
                await _ws_send(websocket, "uav.telemetry", message_to_uav_telemetry(uav_state))
                last_uav_push = now
            if now - last_ugv_push >= 0.2 and ugv_state.longitude is not None and ugv_state.latitude is not None:
                await _ws_send(websocket, "fleet.telemetry", message_to_uav_telemetry(ugv_state))
                last_ugv_push = now
    finally:
        ros_logger.info("ws/uav disconnected")
        hb_task.cancel()
        await client.close()

