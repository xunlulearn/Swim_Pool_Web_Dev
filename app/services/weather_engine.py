import requests
import math
from datetime import datetime, timezone
from enum import Enum

class PoolStatus(Enum):
    """游泳池开放状态枚举"""
    GREEN = "Open"       # 开放
    AMBER = "Warning"    # 警告
    RED = "Closed"       # 关闭

class WeatherEngine:
    """
    天气引擎服务 - 基于NEA闪电数据判断游泳池开放状态
    
    状态逻辑（有限状态机）:
    - RED (关闭): 闪电距离 ≤ 8km
    - AMBER (警告): 闪电距离 8km - 15km
    - GREEN (开放): 无闪电或闪电距离 > 15km
    """
    
    # NTU 体育与娱乐中心坐标
    SRC_LAT = 1.349383588
    SRC_LON = 103.6877553
    
    # 距离阈值 (单位: km)
    LIGHTNING_CLOSE_THRESHOLD = 8.0   # 红色警报
    LIGHTNING_WARN_THRESHOLD = 15.0   # 黄色警告
    
    # NEA API 端点
    LIGHTNING_API_URL = "https://api-open.data.gov.sg/v2/real-time/api/weather?api=lightning"
    
    def __init__(self):
        # 延迟导入或直接获取配置，避免循环依赖
        pass

    @staticmethod
    def haversine(lat1, lon1, lat2, lon2):
        """
        计算两个地理坐标之间的大圆距离 (Haversine公式)
        
        Args:
            lat1, lon1: 第一个点的纬度和经度 (十进制度数)
            lat2, lon2: 第二个点的纬度和经度 (十进制度数)
        
        Returns:
            float: 距离 (单位: 千米)
        """
        R = 6371  # 地球半径 (km)
        
        # 转换为弧度
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        
        # Haversine公式
        a = math.sin(dlat/2) * math.sin(dlat/2) + \
            math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * \
            math.sin(dlon/2) * math.sin(dlon/2)
        
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        distance = R * c
        
        return distance

    def get_lightning_status(self):
        from flask import current_app
        # 获取API Key, 如果没有配置则使用空字符串（可能失败）
        api_key = current_app.config.get('NEA_API_KEY')
        
        headers = {}
        if api_key:
            # Data.gov.sg v2 API 通常使用 key 或 X-API-KEY，具体取决于文档
            # 文档确认通常是 'x-api-key' 或通过 query params
            headers['x-api-key'] = api_key

        try:
            response = requests.get(self.LIGHTNING_API_URL, headers=headers, timeout=10)
            
            if response.status_code == 403:
                return PoolStatus.GREEN, "API密钥缺失或无效", {"error": "Missing/Invalid API Key"}
            
            if response.status_code != 200:
                print(f"获取闪电数据失败: HTTP {response.status_code}")
                return PoolStatus.GREEN, "数据暂时不可用", {"error": "API unavailable"}

            data = response.json()
            
            # NEA API v2 数据结构: data.records[].item.readings[]
            # readings 中每个元素包含闪电的坐标信息
            if data.get('code') != 0:
                print(f"API返回错误: {data.get('errorMsg', 'Unknown error')}")
                return self._get_mock_status()
            
            records = data.get('data', {}).get('records', [])
            all_readings = []
            
            # 提取所有 readings
            for record in records:
                item = record.get('item', {})
                readings = item.get('readings', [])
                all_readings.extend(readings)
            
            # 计算最近的闪电距离
            min_distance = float('inf')
            lightning_count = len(all_readings)
            
            for reading in all_readings:
                # NEA API 闪电数据格式: {"lat": 1.xxx, "lon": 103.xxx, ...}
                lat = reading.get('lat')
                lon = reading.get('lon')
                
                if lat is not None and lon is not None:
                    dist = self.haversine(self.SRC_LAT, self.SRC_LON, lat, lon)
                    if dist < min_distance:
                        min_distance = dist
            
            # 状态机逻辑
            if min_distance <= self.LIGHTNING_CLOSE_THRESHOLD:
                status = PoolStatus.RED
                message = f"检测到近距离闪电 ({min_distance:.1f}km) - 游泳池关闭"
            elif min_distance <= self.LIGHTNING_WARN_THRESHOLD:
                status = PoolStatus.AMBER
                message = f"检测到附近闪电 ({min_distance:.1f}km) - 天气转差"
            else:
                status = PoolStatus.GREEN
                message = "附近无闪电活动 - 游泳池开放"

            details = {
                "min_distance_km": round(min_distance, 2) if min_distance != float('inf') else None,
                "lightning_count": lightning_count,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            return status, message, details

        except requests.exceptions.Timeout:
            print("API请求超时")
            return PoolStatus.GREEN, "网络超时，状态未知", {"error": "timeout"}
        except requests.exceptions.RequestException as e:
            print(f"网络请求异常: {e}")
            return PoolStatus.GREEN, "网络错误", {"error": str(e)}
        except Exception as e:
            print(f"天气引擎异常: {e}")
            return PoolStatus.GREEN, "系统错误", {"error": str(e)}


# 单例实例
weather_engine = WeatherEngine()
