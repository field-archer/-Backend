import base64
import os
import uuid

from fastapi import APIRouter, File, UploadFile

from config.config import config
from app.services.model_service import model_service

router = APIRouter()


@router.post("/analyze")
async def analyze_file(file: UploadFile = File(...)):
    """分析图片或视频文件"""
    try:
        raw_name = file.filename or ""
        file_ext = os.path.splitext(raw_name)[1].lower().lstrip(".")
        if file_ext not in config.ALLOWED_EXTENSIONS:
            return {
                "code": 40000,
                "message": f"不支持的文件类型，支持的类型: {', '.join(config.ALLOWED_EXTENSIONS)}",
                "data": None,
            }

        stored_name = f"{uuid.uuid4().hex}.{file_ext}"
        file_path = os.path.join(config.UPLOAD_DIR, stored_name)
        with open(file_path, "wb") as buffer:
            buffer.write(await file.read())
        
        # 根据文件类型进行分析
        if file_ext in {"jpg", "jpeg", "png", "gif"}:
            result = model_service.analyze_image(file_path)
            output_path = result.get("output_image_path")
        else:  # 视频文件
            result = model_service.analyze_video(file_path)
            output_path = result.get("output_video_path")
        
        # 计算火焰数量
        fire_count = len(result.get("detections", []))
        
        # 计算平均置信度
        confidences = [detection.get("confidence", 0) for detection in result.get("detections", [])]
        average_confidence = sum(confidences) / len(confidences) if confidences else 0

        risk_level = result.get("risk_level", "low")

        # 构建文件URL
        if output_path:
            file_name = os.path.basename(output_path)
            file_url = f"/uploads/{file_name}"
        else:
            file_url = None
        
        # 读取输出文件为base64编码
        file_base64 = None
        if output_path and os.path.exists(output_path):
            with open(output_path, "rb") as f:
                file_base64 = base64.b64encode(f.read()).decode("utf-8")
        
        # 确定文件类型
        if file_ext in {"jpg", "jpeg"}:
            file_type = "image/jpeg"
        elif file_ext == "png":
            file_type = "image/png"
        elif file_ext == "gif":
            file_type = "image/gif"
        elif file_ext == "mp4":
            file_type = "video/mp4"
        elif file_ext == "avi":
            file_type = "video/avi"
        elif file_ext == "mov":
            file_type = "video/quicktime"
        else:
            file_type = "application/octet-stream"
        
        # 返回包含分析结果、文件URL和base64编码的响应
        return {
            "code": 20000,
            "message": "成功",
            "data": {
                **result,
                "fire_count": fire_count,
                "average_confidence": average_confidence,
                "risk_level": risk_level,
                "file_url": file_url,
                "file_base64": file_base64,
                "file_type": file_type
            }
        }
    except Exception as e:
        return {
            "code": 50000,
            "message": f"分析失败: {str(e)}",
            "data": None
        }