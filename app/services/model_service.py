import os

import cv2
from ultralytics import YOLO


def _output_path(src_path: str) -> str:
    root, ext = os.path.splitext(src_path)
    return f"{root}_output{ext}"


class ModelService:
    def __init__(self):
        self._model: YOLO | None = None

    def _get_model(self) -> YOLO:
        if self._model is not None:
            return self._model

        model_path = os.getenv("MODEL_PATH") or "yolo10n_fire.pt"
        if not os.path.exists(model_path):
            raise FileNotFoundError(
                f"缺少模型文件: {model_path}。请将权重文件放到后端工作目录，"
                f"或在环境变量 MODEL_PATH 中指定其路径。"
            )

        self._model = YOLO(model_path)
        return self._model
    
    def analyze_image(self, image_path: str) -> dict:
        """分析图片"""
        try:
            # 读取图片
            img = cv2.imread(image_path)
            height, width, channels = img.shape
            
            # 使用模型进行检测
            results = self._get_model()(image_path)
            
            # 处理检测结果
            detections = []
            fire_probability = 0.0
            
            # 绘制检测结果
            for result in results:
                for box in result.boxes:
                    class_id = int(box.cls[0])
                    confidence = float(box.conf[0])
                    bbox = box.xyxy[0].tolist()
                    
                    # 假设模型输出的0类是火焰
                    if class_id == 0:
                        detections.append({
                            "class": "fire",
                            "confidence": confidence,
                            "bbox": [int(coord) for coord in bbox]
                        })
                        if confidence > fire_probability:
                            fire_probability = confidence
                        
                        # 绘制边界框
                        x1, y1, x2, y2 = [int(coord) for coord in bbox]
                        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
                        cv2.putText(img, f"fire: {confidence:.2f}", (x1, y1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            
            output_image_path = _output_path(image_path)
            cv2.imwrite(output_image_path, img)
            
            # 确定风险等级
            risk_level = "low"
            if fire_probability > 0.8:
                risk_level = "high"
            elif fire_probability > 0.5:
                risk_level = "medium"
            
            result = {
                "image_info": {
                    "width": width,
                    "height": height,
                    "channels": channels
                },
                "detections": detections,
                "fire_probability": fire_probability,
                "risk_level": risk_level,
                "output_image_path": output_image_path
            }
            
            return result
        except Exception as e:
            raise Exception(f"图片分析失败: {str(e)}")
    
    def analyze_video(self, video_path: str) -> dict:
        """分析视频"""
        try:
            # 获取视频文件信息
            file_size = os.path.getsize(video_path)
            
            # 打开视频
            cap = cv2.VideoCapture(video_path)
            fps = cap.get(cv2.CAP_PROP_FPS)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            duration = total_frames / fps if fps > 0 else 0
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            
            output_video_path = _output_path(video_path)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))
            
            # 处理视频帧
            detections = []
            frame_count = 0
            fire_probability = 0.0
            
            while frame_count < 100:  # 处理前100帧，避免处理时间过长
                ret, frame = cap.read()
                if not ret:
                    break
                
                # 使用模型检测
                results = self._get_model()(frame)
                
                # 处理检测结果
                for result in results:
                    for box in result.boxes:
                        class_id = int(box.cls[0])
                        confidence = float(box.conf[0])
                        bbox = box.xyxy[0].tolist()
                        
                        # 假设模型输出的0类是火焰
                        if class_id == 0:
                            time_str = f"{int(frame_count/fps)//3600:02d}:{int(frame_count/fps)%3600//60:02d}:{int(frame_count/fps)%60:02d}"
                            detections.append({
                                "time": time_str,
                                "class": "fire",
                                "confidence": confidence,
                                "bbox": [int(coord) for coord in bbox]
                            })
                            if confidence > fire_probability:
                                fire_probability = confidence
                            
                            # 绘制边界框
                            x1, y1, x2, y2 = [int(coord) for coord in bbox]
                            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 0, 255), 2)
                            cv2.putText(frame, f"fire: {confidence:.2f}", (x1, y1 - 10),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
                
                # 写入处理后的帧
                out.write(frame)
                frame_count += 1
            
            # 释放视频
            cap.release()
            out.release()
            
            # 确定风险等级
            risk_level = "low"
            if fire_probability > 0.8:
                risk_level = "high"
            elif fire_probability > 0.5:
                risk_level = "medium"
            
            result = {
                "video_info": {
                    "file_size": file_size,
                    "duration": duration,
                    "fps": fps,
                    "total_frames": total_frames,
                    "width": width,
                    "height": height
                },
                "detections": detections,
                "fire_probability": fire_probability,
                "risk_level": risk_level,
                "output_video_path": output_video_path
            }
            
            return result
        except Exception as e:
            raise Exception(f"视频分析失败: {str(e)}")

model_service = ModelService()