import subprocess, os, sys

result = subprocess.run(
    ['git', 'ls-files'],
    capture_output=True, text=True,
    cwd='C:/Users/LENOVO/Desktop/driver'
)
files = result.stdout.strip().split('\n')
issues = []
for f in files:
    path = f'C:/Users/LENOVO/Desktop/driver/{f}'
    if os.path.exists(path) and os.path.isfile(path):
        with open(path, 'rb') as fp:
            if b'\x00' in fp.read():
                issues.append(f)

if issues:
    print('FILES WITH NULL BYTES:')
    for f in issues:
        print(f'  {f}')
    sys.exit(1)
else:
    print('All clean - no null bytes in any tracked file.')
