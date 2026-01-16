"""验证降雨API数据解析"""
import json
import math

# NTU SRC 坐标
SRC_LAT = 1.349383588
SRC_LON = 103.6877553

def haversine(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# 读取降雨样本数据
with open('tests/sample_nea_rainfall_data.json', 'r') as f:
    data = json.load(f)

print('=== 降雨API数据结构验证 ===')
print(f"API code: {data.get('code')}")
print(f"readingType: {data.get('data', {}).get('readingType')}")
print(f"readingUnit: {data.get('data', {}).get('readingUnit')}")

# 解析站点
stations = data.get('data', {}).get('stations', [])
print(f"\n总站点数: {len(stations)}")

# 建立映射
station_map = {}
for station in stations:
    station_id = station.get('id')
    location = station.get('location', {})
    lat = location.get('latitude')
    lon = location.get('longitude')
    name = station.get('name')
    if station_id and lat is not None:
        station_map[station_id] = {'name': name, 'lat': float(lat), 'lon': float(lon)}

# 找最近站点
nearest_id = None
nearest_name = None
min_dist = float('inf')

for sid, info in station_map.items():
    dist = haversine(SRC_LAT, SRC_LON, info['lat'], info['lon'])
    if dist < min_dist:
        min_dist = dist
        nearest_id = sid
        nearest_name = info['name']

print(f"\n离NTU最近的站点: {nearest_name} ({nearest_id})")
print(f"距离NTU: {min_dist:.2f} km")

# 获取该站点的降雨值
readings = data.get('data', {}).get('readings', [])
if readings:
    latest = readings[-1]
    print(f"\n最新读数时间: {latest.get('timestamp')}")
    for item in latest.get('data', []):
        if item.get('stationId') == nearest_id:
            value_5min = item.get('value')
            value_per_hour = value_5min * 12
            print(f"5分钟降雨量: {value_5min} mm")
            print(f"换算小时降雨量: {value_per_hour} mm/h")
            if value_per_hour > 5:
                print('状态: 降雨量超过阈值 (>5mm/h) - 触发AMBER警告')
            else:
                print('状态: 降雨量正常 (<5mm/h)')
            break
