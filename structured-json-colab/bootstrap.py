"""Install into an isolated environment, reusing only Colab's base packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

URL = 'https://files.pythonhosted.org/packages/a7/fe/a87be2a492440945e745b0dc81aef7fea9730d8194af88d854b7641f5ddf/uv-0.12.2-py3-none-manylinux_2_17_x86_64.manylinux2014_x86_64.whl'
SHA256 = '3a8d93d1fe019561b70494a8e1332492afb5f14dadc33d5239569d0964164d10'
ENV = Path('/content/structured-json-env')


def run(arguments):
    env = dict(os.environ)
    env.pop('UV_SYSTEM_PYTHON', None)
    result = subprocess.run(arguments, capture_output=True, text=True, env=env)
    print(result.stdout, flush=True)
    print(result.stderr, file=sys.stderr, flush=True)
    if result.returncode:
        raise RuntimeError('Dependency setup subprocess failed: ' + str(result.returncode))


def setup(requirements):
    wheel = Path('/content/structured-json-uv.whl')
    urllib.request.urlretrieve(URL, wheel)
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError('uv wheel checksum mismatch')
    with zipfile.ZipFile(wheel) as archive:
        members = [n for n in archive.namelist() if n.endswith('.data/scripts/uv') or n == 'uv/uv']
        if len(members) != 1:
            raise RuntimeError('Unexpected uv wheel layout')
        uv = Path('/content/structured-json-uv')
        uv.write_bytes(archive.read(members[0]))
    uv.chmod(0o755)
    run([str(uv), 'venv', '--system-site-packages', '--python', sys.executable, str(ENV)])
    # uv resolves target dependencies independently of inherited site-packages.
    # Exclude base torch to avoid replacing its matching torchvision/CUDA stack.
    import torch
    base_torch = torch.__version__
    exclude = Path('/content/structured-json-excludes.txt')
    exclude.write_text('torch\n')
    run([str(uv), 'pip', 'install', '--python', str(ENV/'bin/python'), '--excludes', str(exclude), '-r', str(requirements)])
    run([str(ENV/'bin/python'), '-c', 'import torch,torchvision; assert torch.__version__ == '+repr(base_torch)+'; print("Preserved base torch/torchvision:",torch.__version__,torchvision.__version__)'])
    Path('/content/json-bootstrap-install.json').write_text(json.dumps({'returncode': 0, 'isolated_environment': str(ENV)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--requirements', required=True)
    setup(parser.parse_args().requirements)
