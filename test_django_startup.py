import subprocess, os

env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'config.settings', 'DATABASE_URL': ''}
result = subprocess.run(
    [r'C:\Users\LENOVO\Desktop\driver\.venv\Scripts\python.exe', '-c',
     'import django; django.setup(); print("Django OK")'],
    capture_output=True, text=True,
    cwd=r'C:\Users\LENOVO\Desktop\driver\django_smarthaul',
    env=env
)
print('stdout:', result.stdout.strip())
if result.stderr:
    print('stderr:', result.stderr[:800])
print('returncode:', result.returncode)
