import os
from dotenv import load_dotenv
import requests

# Load env vars
load_dotenv()

URL = "https://api-open.data.gov.sg/v2/real-time/api/lightning"
API_KEY = os.getenv('NEA_API_KEY')

print(f"API Key from .env: {API_KEY}")
print(f"Testing {URL}...\n")

headers = {}
if API_KEY and API_KEY != 'optional-if-needed':
    headers['x-api-key'] = API_KEY

try:
    response = requests.get(URL, headers=headers, timeout=10)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print("✅ Success! API is working.")
        
        # Check structure
        if 'data' in data:
            print(f"Found {len(data.get('data', {}).get('features', []))} lightning features")
        else:
            print(f"Found {len(data.get('features', []))} features directly")
            
    elif response.status_code == 403:
        print("❌ 403 Forbidden - API Key is missing or invalid")
        print("Please get a valid key from https://developer.data.gov.sg/")
    else:
        print(f"Response: {response.text[:200]}")
        
except Exception as e:
    print(f"Error: {e}")
