import requests

URL = "https://api-open.data.gov.sg/v2/real-time/api/weather?api=lightning"

print(f"Testing CORRECT endpoint: {URL}\n")

try:
    response = requests.get(URL, timeout=10)
    print(f"Status Code: {response.status_code}")
    
    if response.status_code == 200:
        print("✅ Success! No API Key needed!")
        data = response.json()
        
        # Print structure
        print(f"\nResponse keys: {list(data.keys())}")
        
        if 'data' in data:
            print(f"data keys: {list(data['data'].keys())}")
            if 'features' in data['data']:
                print(f"Found {len(data['data']['features'])} lightning features")
        
        print("\nFirst 300 chars:")
        import json
        print(json.dumps(data, indent=2)[:300])
    else:
        print(f"Error: {response.text}")
        
except Exception as e:
    print(f"Error: {e}")
