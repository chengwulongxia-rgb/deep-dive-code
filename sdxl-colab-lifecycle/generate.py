"""One pinned SDXL image; imports are stdlib-only until run()."""
import argparse
import hashlib
import json
import platform
import os
import subprocess
import sys
import time
import traceback
import zipfile
from pathlib import Path

MODEL_ID = 'stabilityai/stable-diffusion-xl-base-1.0'
MODEL_REVISION = '462165984030d82259a11f4367a4eed129e94a7b'
PARAMETERS = dict(model=MODEL_ID, revision=MODEL_REVISION, variant='fp16',
    prompt='A small wooden cabin beside a quiet mountain lake at sunrise, watercolor illustration, warm light, no text',
    width=1024, height=1024, num_inference_steps=25, guidance_scale=7.5, seed=42)

def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')

def gpu_preflight():
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA required; CPU fallback forbidden')
    name = torch.cuda.get_device_name(0)
    if 'L4' not in name.split():
        raise RuntimeError('NVIDIA L4 required, got ' + name)
    return torch

def run(output, preflight=gpu_preflight):
    out = Path(output)
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise FileExistsError('Output must be empty: ' + str(out))
    start = time.monotonic()
    metrics = dict(status='running', python=sys.version, platform=platform.platform())
    write_json(out/'parameters.json', PARAMETERS)
    try:
        # Select the PyTorch backend before importing transformers/diffusers;
        # TensorFlow/Flax are not part of this pipeline and are not initialized.
        os.environ['USE_TF'] = '0'
        os.environ['USE_FLAX'] = '0'
        torch = preflight()
        from diffusers import StableDiffusionXLPipeline
        import importlib.metadata
        metrics.update(torch_version=torch.__version__, cuda_version=torch.version.cuda,
            gpu=torch.cuda.get_device_name(0), packages={p: importlib.metadata.version(p) for p in
                ['diffusers','transformers','accelerate','safetensors','Pillow','huggingface-hub']})
        try:
            metrics['nvidia_smi_before'] = subprocess.check_output(['nvidia-smi'], text=True, timeout=10)
        except (OSError, subprocess.SubprocessError) as e:
            metrics['nvidia_smi_error'] = str(e)
        torch.cuda.reset_peak_memory_stats()
        load_start = time.monotonic()
        pipe = StableDiffusionXLPipeline.from_pretrained(MODEL_ID, revision=MODEL_REVISION,
            torch_dtype=torch.float16, variant='fp16', use_safetensors=True).to('cuda')
        # Keep diffusers' standard force_upcast VAE behavior; no extra optimizations/refiner.
        metrics['load_seconds'] = time.monotonic()-load_start
        torch.cuda.synchronize()
        infer_start = time.monotonic()
        image = pipe(prompt=PARAMETERS['prompt'], width=1024, height=1024,
            num_inference_steps=25, guidance_scale=7.5,
            generator=torch.Generator(device='cuda').manual_seed(42)).images[0]
        torch.cuda.synchronize()
        metrics['inference_seconds'] = time.monotonic()-infer_start
        metrics['peak_allocated_bytes'] = torch.cuda.max_memory_allocated()
        metrics['peak_reserved_bytes'] = torch.cuda.max_memory_reserved()
        if image.size != (1024,1024):
            raise RuntimeError('Unexpected image dimensions')
        if all(lo == hi for lo,hi in image.convert('RGB').getextrema()):
            raise RuntimeError('Constant image rejected')
        image.save(out/'image.png')
        metrics.update(status='success', image_dimensions=list(image.size), image_nonconstant=True)
    except BaseException as e:
        metrics.update(status='failed', error_type=type(e).__name__, error=str(e), traceback=traceback.format_exc())
        raise
    finally:
        metrics['elapsed_seconds'] = time.monotonic()-start
        write_json(out/'metrics.json', metrics)
        files = {p.name: dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(), bytes=p.stat().st_size)
                 for p in sorted(out.iterdir()) if p.is_file() and p.name not in ('manifest.json','result.zip')}
        write_json(out/'manifest.json', dict(status=metrics['status'], model=MODEL_ID,
            resolved_revision=MODEL_REVISION, files=files))
        with zipfile.ZipFile(out/'result.zip', 'w', zipfile.ZIP_DEFLATED) as z:
            for p in sorted(out.iterdir()):
                if p.is_file() and p.name != 'result.zip': z.write(p,p.name)
    return metrics

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    run(parser.parse_args().output)
