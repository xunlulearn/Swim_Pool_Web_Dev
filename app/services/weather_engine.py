import requests
import math
import json
import os
from datetime import datetime, timezone, timedelta
from enum import Enum

# 测试模式：设为 True 使用本地样例数据，设为 False 使用实时API
USE_SAMPLE_DATA = False
SAMPLE_LIGHTNING_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'tests', 'sample_nea_lightning_data.json')
SAMPLE_RAINFALL_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'tests', 'sample_nea_rainfall_data.json')

class PoolStatus(Enum):
    """游泳池开放状态枚举"""
    GREEN = "Open"       # 开放
    AMBER = "Warning"    # 警告
    RED = "Closed"       # 关闭

class WeatherEngine:
    """
    天气引擎服务 - 基于NEA闪电和降雨数据判断游泳池开放状态
    
    状态逻辑（有限状态机）:
    - RED (关闭): 闪电距离 ≤ 8km
    - AMBER (警告): 闪电距离 8km - 15km 或 降雨量 > 5mm/h
    - GREEN (开放): 无闪电或闪电距离 > 15km 且 降雨量 < 5mm/h
    """
    
    # NTU 体育与娱乐中心坐标
    SRC_LAT = 1.349383588
    SRC_LON = 103.6877553
    
    # 闪电距离阈值 (单位: km)
    LIGHTNING_CLOSE_THRESHOLD = 8.0   # 红色警告 (关闭)
    LIGHTNING_WARN_THRESHOLD = 15.0   # 黄色警告 (新规则: 15km内关闭)
    
    # 降雨阈值 (单位: mm/h)
    RAINFALL_WARN_THRESHOLD = 5.0     # 黄色警告
    
    # NEA API 端点
    LIGHTNING_API_URL = "https://api-open.data.gov.sg/v2/real-time/api/weather?api=lightning"
    RAINFALL_API_URL = "https://api-open.data.gov.sg/v2/real-time/api/rainfall"
    
    def __init__(self):
        # 状态持久化变量
        self.last_lightning_alert_time = None  # 上次闪电警报时间
        self.last_rain_alert_time = None       # 上次降雨警报时间
        
        # 2026年新加坡公共假期 (YYYY-MM-DD)
        self.PUBLIC_HOLIDAYS_2026 = {
            "2026-01-01", # New Year's Day
            "2026-02-17", "2026-02-18", # CNY
            "2026-03-21", # Hari Raya Puasa
            "2026-04-03", # Good Friday
            "2026-05-01", # Labour Day
            "2026-05-27", # Hari Raya Haji
            "2026-05-31", "2026-06-01", # Vesak Day + Observed
            "2026-08-09", "2026-08-10", # National Day + Observed
            "2026-11-08", "2026-11-09", # Deepavali + Observed
            "2026-12-25"  # Christmas
        }

    def _is_operating_hours(self):
        """
        检查是否在运营时间内
        周一至周五: 07:00 - 21:30
        周末及公假: 08:00 - 20:00
        """
        # 获取新加坡时间 (UTC+8)
        sgt_now = datetime.now(timezone(timedelta(hours=8)))
        
        date_str = sgt_now.strftime("%Y-%m-%d")
        is_weekend = sgt_now.weekday() >= 5 # 5=Sat, 6=Sun
        is_holiday = date_str in self.PUBLIC_HOLIDAYS_2026
        
        current_time = sgt_now.time()
        
        if is_weekend or is_holiday:
            # 8:00 AM - 8:00 PM
            start_time = datetime.strptime("08:00", "%H:%M").time()
            end_time = datetime.strptime("20:00", "%H:%M").time()
        else:
            # 7:00 AM - 9:30 PM
            start_time = datetime.strptime("07:00", "%H:%M").time()
            end_time = datetime.strptime("21:30", "%H:%M").time()
            
        if start_time <= current_time <= end_time:
            return True, None
        else:
            msg = f"游泳池关闭 - 非运营时间 ({'周末/假日' if is_weekend or is_holiday else '工作日'} {start_time.strftime('%H:%M')}-{end_time.strftime('%H:%M')})"
            return False, msg

    def _get_community_consensus(self):
        """
        检查社区共识: 30分钟内连续5个不同用户汇报相同状态
        """
        try:
            from app.models.report import PoolReport
            
            # 30分钟前 (UTC时间)
            cutoff_time = datetime.utcnow() - timedelta(minutes=30)
            
            # 获取最近的报告 (按时间倒序)
            recent_reports = PoolReport.query.filter(
                PoolReport.created_at >= cutoff_time
            ).order_by(PoolReport.created_at.desc()).limit(10).all()
            
            if len(recent_reports) < 5:
                return None
            
            # 取最新的5条
            latest_5 = recent_reports[:5]
            
            # 检查是否为同一状态
            first_status = latest_5[0].status
            if not all(r.status == first_status for r in latest_5):
                return None
            
            # 检查是否为5个不同用户
            user_ids = {r.user_id for r in latest_5}
            if len(user_ids) < 5:
                return None
            
            # 计算有效期 (最后一条报告后10分钟内有效)
            latest_report_time = latest_5[0].created_at
            if (datetime.utcnow() - latest_report_time) > timedelta(minutes=10):
                return None
            
            return first_status # "Open" or "Closed"
            
        except Exception as e:
            print(f"获取社区共识失败: {e}")
            return None

    def get_overall_status(self):
        """
        获取综合状态 (主逻辑入口)
        优先级: 运营时间 > 社区共识 > 闪电 > 降雨 > 默认
        """
        # 首先获取天气数据
        l_status, l_msg, l_details = self.get_lightning_status()
        r_rate, r_station, r_dist = self.get_rainfall_status()
        
        now = datetime.now(timezone.utc)
        
        # 提取闪电距离
        l_dist = l_details.get('min_distance_km')
        has_lightning = l_dist is not None and l_dist <= 15.0
        
        # 基础指标数据 (用于所有返回)
        base_metrics = {
            "lightning_dist": l_dist,
            "rainfall_rate": r_rate,
            "lightning_count": l_details.get("lightning_count"),
            "min_distance_km": l_dist  # For frontend compatibility
        }

        # 1. 检查运营时间 (最高优先级)
        is_open_hours, hours_msg = self._is_operating_hours()
        if not is_open_hours:
            return PoolStatus.RED, hours_msg, {**base_metrics, "reason": "operating_hours"}

        # 2. 检查社区共识
        community_status = self._get_community_consensus()
        if community_status:
            status = PoolStatus.GREEN if community_status == "Open" else PoolStatus.RED
            color = "Open" if status == PoolStatus.GREEN else "Closed"
            return status, f"社区汇报: 游泳池{color} (基于用户手动汇报)", {
                **base_metrics,
                "reason": "community_consensus", 
                "reported_status": community_status
            }
        
        # 3. 闪电逻辑 (30分钟持久化)
        if has_lightning:
            self.last_lightning_alert_time = now
        
        # 检查闪电持久化
        if self.last_lightning_alert_time:
            time_since_alert = (now - self.last_lightning_alert_time).total_seconds() / 60
            if time_since_alert <= 30:
                # 在30分钟警告期内
                remaining = 30 - int(time_since_alert)
                msg_suffix = f" (持续30分钟, 剩余{remaining}分)" if not has_lightning else ""
                warning_dist = l_dist if has_lightning else "历史"
                return PoolStatus.RED, f"游泳池因雷电预警关闭 (最近 {warning_dist}km){msg_suffix}", {
                    **base_metrics,
                    "reason": "lightning",
                    "distance": l_dist,
                    "last_alert": self.last_lightning_alert_time.isoformat()
                }
            else:
                self.last_lightning_alert_time = None # 过期重置

        # 4. 降雨逻辑 (30分钟持久化)
        # S44 (Nanyang Avenue) 降雨 > 5mm/h
        has_heavy_rain = r_rate is not None and r_rate > self.RAINFALL_WARN_THRESHOLD

        if has_heavy_rain:
            self.last_rain_alert_time = now
            
        if self.last_rain_alert_time:
            time_since_alert = (now - self.last_rain_alert_time).total_seconds() / 60
            if time_since_alert <= 30:
                remaining = 30 - int(time_since_alert)
                msg_suffix = f" (持续30分钟, 剩余{remaining}分)" if not has_heavy_rain else ""
                current_rate = f"{r_rate:.1f}mm/h" if has_heavy_rain else "历史"
                return PoolStatus.RED, f"游泳池因大雨关闭 ({current_rate}){msg_suffix}", {
                    **base_metrics,
                    "reason": "heavy_rain", 
                    "rainfall_rate": r_rate,
                    "last_alert": self.last_rain_alert_time.isoformat()
                }
            else:
                self.last_rain_alert_time = None

        # 5. 默认开放
        return PoolStatus.GREEN, "游泳池正在开放", base_metrics

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
        try:
            # 测试模式：使用本地样例数据
            if USE_SAMPLE_DATA:
                with open(SAMPLE_LIGHTNING_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                from flask import current_app
                # 获取API Key, 如果没有配置则使用空字符串（可能失败）
                api_key = current_app.config.get('NEA_API_KEY')
                
                headers = {}
                if api_key:
                    headers['x-api-key'] = api_key

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
                # NEA API 闪电数据格式: {"location": {"latitude": "1.xxx", "longitude": "103.xxx"}, ...}
                location = reading.get('location', {})
                lat_str = location.get('latitude')
                lon_str = location.get('longitude')
                
                if lat_str is not None and lon_str is not None:
                    try:
                        lat = float(lat_str)
                        lon = float(lon_str)
                        dist = self.haversine(self.SRC_LAT, self.SRC_LON, lat, lon)
                        if dist < min_distance:
                            min_distance = dist
                    except (ValueError, TypeError):
                        # 跳过无效坐标
                        continue
            
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

    def get_rainfall_status(self):
        """
        获取NTU附近的降雨状态
        
        Returns:
            tuple: (rainfall_mm_per_hour, nearest_station_name, station_distance_km)
        """
        try:
            # 测试模式：使用本地样例数据
            if USE_SAMPLE_DATA:
                with open(SAMPLE_RAINFALL_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                from flask import current_app
                api_key = current_app.config.get('NEA_API_KEY')
                
                headers = {}
                if api_key:
                    headers['x-api-key'] = api_key

                response = requests.get(self.RAINFALL_API_URL, headers=headers, timeout=10)
                
                if response.status_code != 200:
                    print(f"获取降雨数据失败: HTTP {response.status_code}")
                    return 0.0, None, None

                data = response.json()
            
            if data.get('code') != 0:
                print(f"降雨API返回错误: {data.get('errorMsg', 'Unknown error')}")
                return 0.0, None, None
            
            # 解析站点信息 - 建立 stationId -> {name, lat, lon} 映射
            stations = data.get('data', {}).get('stations', [])
            station_map = {}
            for station in stations:
                station_id = station.get('id')
                location = station.get('location', {})
                # 注意：降雨API的坐标是数字，不是字符串
                lat = location.get('latitude')
                lon = location.get('longitude')
                name = station.get('name')
                
                if station_id and lat is not None and lon is not None:
                    station_map[station_id] = {
                        'name': name,
                        'lat': float(lat),
                        'lon': float(lon)
                    }
            
            # 找到离NTU最近的站点
            nearest_station_id = None
            nearest_station_name = None
            min_distance = float('inf')
            
            for station_id, info in station_map.items():
                dist = self.haversine(self.SRC_LAT, self.SRC_LON, info['lat'], info['lon'])
                if dist < min_distance:
                    min_distance = dist
                    nearest_station_id = station_id
                    nearest_station_name = info['name']
            
            if nearest_station_id is None:
                return 0.0, None, None
            
            # 获取最近站点的降雨值
            readings = data.get('data', {}).get('readings', [])
            rainfall_5min = 0.0
            
            if readings:
                latest_reading = readings[-1]  # 取最新的读数
                reading_data = latest_reading.get('data', [])
                
                for item in reading_data:
                    if item.get('stationId') == nearest_station_id:
                        rainfall_5min = float(item.get('value', 0))
                        break
            
            # 将5分钟降雨量换算为小时降雨量 (mm/5min * 12 = mm/h)
            rainfall_per_hour = rainfall_5min * 12
            
            return rainfall_per_hour, nearest_station_name, round(min_distance, 2)
            
        except Exception as e:
            print(f"获取降雨数据异常: {e}")
            return 0.0, None, None


# 单例实例
weather_engine = WeatherEngine()
