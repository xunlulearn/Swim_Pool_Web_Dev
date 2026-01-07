import requests
import json

URL = "https://api-open.data.gov.sg/v2/real-time/api/weather?api=lightning"

response = requests.get(URL, timeout=10)
data = response.json()

print(json.dumps(data, indent=2, ensure_ascii=False))
