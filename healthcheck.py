import requests, sys, json

url = 'https://smarthaul-059r.onrender.com/api/auth/health/'
print(f'GET {url}')
try:
    r = requests.get(url, timeout=45)
    print(f'Status: {r.status_code}')
    if r.headers.get('content-type', '').startswith('application/json'):
        print(f'Body: {json.dumps(r.json(), indent=2)}')
    else:
        print(f'Body: {r.text[:300]}')
    sys.exit(0 if r.status_code == 200 else 1)
except requests.exceptions.Timeout:
    print('TIMEOUT after 45s - server still not responding')
    sys.exit(2)
except Exception as e:
    print(f'{type(e).__name__}: {e}')
    sys.exit(3)
