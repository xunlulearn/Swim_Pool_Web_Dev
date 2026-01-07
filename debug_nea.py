import requests
import json

URL = "https://api-open.data.gov.sg/v2/real-time/api/lightning"

try:
    print(f"Connecting to {URL}...")
    response = requests.get(URL, timeout=10)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        print("\nResponse Data Structure (Keys):")
        print(data.keys())
        
        if 'data' in data:
            print("\n'data' keys:", data['data'].keys())
            if 'features' in data['data']:
                print(f"Found {len(data['data']['features'])} features.")
            else:
                print("'features' NOT found in data['data']")
        elif 'features' in data:
             print(f"Found {len(data['features'])} features directly in root.")
        else:
            print("Cannot find 'features' list in response.")
            
        print("\nFirst 500 chars of response:")
        print(json.dumps(data, indent=2)[:500])
    else:
        print("Response Text:", response.text)

except Exception as e:
    print(f"Error: {e}")
