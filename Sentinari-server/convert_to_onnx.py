"""Gemma -> ONNX conversion — Phase 0 of the_process_to_follow.md.

This script drives Microsoft's onnxruntime-genai model builder via its
OFFICIAL command-line interface (``python -m onnxruntime_genai.models.builder``).
The 0.17.0 API moved the plumbing into the CLI (create_model now demands
prepared hf_details), so we wrap the supported entrypoint instead of
re-implementing it — that keeps this script churn-proof across releases.

MODES
-----
1. ONLINE (machine has internet — the one sanctioned touchpoint):

       python convert_to_onnx.py --model google/gemma-4-12B-it \\
           --output ./models/gemma-12b-onnx --precision int4 \\
           --execution-provider cpu

   Downloads the source checkpoint from Hugging Face (un-gated, no token),
   converts to ONNX, writes a self-contained folder: ONNX weights +
   tokenizer + genai config. NOTHING HF-authored needs to execute at
   runtime — the runtime installs onnxruntime-genai only.

2. OFFLINE (air-gapped rig — the roadmap's discipline):

   Step A (on the CONNECTED box, e.g. this Windows machine):

       python convert_to_onnx.py --download-only --model google/gemma-4-12B-it \\
           --snapshot-dir ./carry/gemma-4-12B-it

   Step B: carry ./carry/gemma-4-12B-it across by hand (USB / LAN).

   Step C (on the rig, still offline):

       python convert_to_onnx.py --input ./carry/gemma-4-12B-it \\
           --output ./models/gemma-12b-onnx --precision int4 \\
           --execution-provider cpu

The conversion itself is CPU/RAM heavy: ~24 GB download (fp16 weights),
~40-50 GB RAM peak during export on CPU. int4 output lands around 7-8 GB.

After it finishes: verify the output folder, then point the runtime's
inference_settings.yaml (model.path) at it — or POST it live to
/api/inference/model/load on a running Sentinari inference server.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

# Python 3.14 law (learned the hard way 2026-09-27, conversion.log):
# argparse now VALIDATES help strings at add_argument time
# (ArgumentParser._check_help), and onnxruntime-genai's builder help text
# contains literal '%' characters — the builder crashes before it even
# parses our arguments ("ValueError: badly formed help string"). The shim
# relaxes that one check inside the builder's own subprocess; nothing else
# is touched, and on Python <= 3.13 it is a no-op (the attribute is absent).
_BUILDER_SHIM = r'''
import argparse, runpy, sys
if hasattr(argparse.ArgumentParser, '_check_help'):
    argparse.ArgumentParser._check_help = lambda self, action: None

def _install_rope_compat():
    """Keep the legacy RoPE adjustment for old builders and enable Gemma4's
    documented global-attribute access during base initialization."""
    from importlib.metadata import version
    from packaging.version import Version
    from onnxruntime_genai.models.builders import base as _base
    from transformers import AutoConfig

    native_gemma4 = Version(version("onnxruntime-genai")) >= Version("0.20.0")
    _orig = _base.Model.make_config_init
    def _patched(self, config):
        result = _orig(self, config)
        rp = getattr(config, 'rope_parameters', None)
        if not native_gemma4 and isinstance(rp, dict) and 'rope_type' not in rp and isinstance(rp.get('sliding_attention'), dict):
            sliding = rp.get('sliding_attention') or {}
            full = rp.get('full_attention') or sliding
            if not getattr(config, 'rope_theta', None) and 'rope_theta' in full:
                config.rope_theta = full['rope_theta']
            if not getattr(config, 'rope_local_base_freq', None) and 'rope_theta' in sliding:
                config.rope_local_base_freq = sliding['rope_theta']
            config.rope_parameters = None
        return result
    _base.Model.make_config_init = _patched
    _orig_auto_config = AutoConfig.from_pretrained
    def _patched_auto_config(cls, *args, **kwargs):
        config = _orig_auto_config(*args, **kwargs)
        architectures = getattr(config, 'architectures', None) or []
        if architectures and architectures[0] in (
            'Gemma4UnifiedForConditionalGeneration',
            'Gemma4ForConditionalGeneration',
        ):
            config.allow_global_per_layer_attribute_access = True
            text_config = getattr(config, 'text_config', None)
            text_config = config if text_config is None else text_config
            text_config.allow_global_per_layer_attribute_access = True
            full_layers = [
                text_config.per_layer_config[index]
                for index, layer_type in enumerate(text_config.layer_types)
                if layer_type == 'full_attention'
            ]
            if not full_layers:
                raise ValueError('Gemma4 config has no full-attention layers')
            global_geometry = {
                (layer.head_dim, layer.num_key_value_heads)
                for layer in full_layers
            }
            if len(global_geometry) != 1:
                raise ValueError('Gemma4 full-attention layers have inconsistent geometry')
            config.global_head_dim, config.num_global_key_value_heads = global_geometry.pop()
            print('[rope-compat] enabled Gemma4 per-layer config access', flush=True)
            print(
                '[rope-compat] derived global geometry:',
                config.global_head_dim,
                config.num_global_key_value_heads,
                flush=True,
            )
        return config
    AutoConfig.from_pretrained = classmethod(_patched_auto_config)
    print('[rope-compat] patched Model id =', id(_base.Model), 'qualname:', _base.Model.make_config_init.__qualname__, flush=True)
    _orig_rope = _base.Model.make_rope_init
    def _rope_probe(self, config):
        rp = getattr(config, 'rope_parameters', None)
        print('[rope-compat] make_rope_init sees rp =', str(rp)[:100], '| self class id =', id(type(self)), '| Model id =', id(_base.Model), flush=True)
        return _orig_rope(self, config)
    _base.Model.make_rope_init = _rope_probe

_install_rope_compat()
runpy.run_module('onnxruntime_genai.models.builder', run_name='__main__')
'''


def _ensure_rope_compat() -> None:
    """Idempotent source patch for onnxruntime-genai's builders/base.py.

    ORT GenAI 0.20 has native Gemma4 RoPE handling and must retain the nested
    per-layer parameters. Keep the compatibility patch only for older builders.
    """
    try:
        import importlib.metadata
        import importlib.util
        from packaging.version import Version

        if Version(importlib.metadata.version("onnxruntime-genai")) >= Version("0.20.0"):
            print("[rope-compat] using native Gemma4 RoPE handling")
            return

        spec = importlib.util.find_spec("onnxruntime_genai.models.builders.base")
        if not spec or not spec.origin:
            return
        path = Path(spec.origin)
        source = path.read_text(encoding="utf-8")
        if "[sentinari rope-compat]" in source:
            return
        anchor = (
            '        if hasattr(config, "rope_parameters") and isinstance(config.rope_parameters, dict):\n'
            "            # Collapse all options inside rope_parameters to the top-level config for easier access.\n"
            "            rope_params = config.rope_parameters\n"
            "            for key in rope_params:\n"
            "                if not hasattr(config, key):\n"
            "                    setattr(config, key, rope_params[key])"
        )
        if anchor not in source:
            print("[rope-compat] anchor not found — builder source changed; NOT patched", file=sys.stderr)
            return
        addition = anchor + '\n\n        # [sentinari rope-compat]\n        _rp = getattr(config, "rope_parameters", None)\n'
        addition += '        if isinstance(_rp, dict) and "rope_type" not in _rp and isinstance(_rp.get("sliding_attention"), dict):\n'
        addition += '            _sliding = _rp.get("sliding_attention") or {}\n'
        addition += '            _full = _rp.get("full_attention") or _sliding\n'
        addition += '            if not getattr(config, "rope_theta", None) and "rope_theta" in _full:\n'
        addition += '                config.rope_theta = _full["rope_theta"]\n'
        addition += '            if not getattr(config, "rope_local_base_freq", None) and "rope_theta" in _sliding:\n'
        addition += '                config.rope_local_base_freq = _sliding["rope_theta"]\n'
        addition += '            config.rope_parameters = None'
        path.write_text(source.replace(anchor, addition, 1), encoding="utf-8")
        print("[rope-compat] applied to", path)
    except Exception as ex:  # a broken patch must never block the CLI check
        print(f"[rope-compat] could not apply: {ex}", file=sys.stderr)


def _builder_module() -> str:
    """Confirm the conversion toolchain is installed, or die loudly."""
    try:
        import onnxruntime_genai  # noqa: F401
    except ImportError:
        print(
            "ERROR: onnxruntime-genai not installed in this environment.\n"
            "Install the conversion toolchain first:\n"
            "    pip install -r requirements-conversion.txt",
            file=sys.stderr,
        )
        sys.exit(1)
    return "onnxruntime_genai.models.builder"


def _download_snapshot(model: str, snapshot_dir: Path) -> None:
    """Download the HF checkpoint to a portable folder (no conversion)."""
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("ERROR: huggingface_hub not installed (see requirements-conversion.txt).", file=sys.stderr)
        sys.exit(1)
    print(f"[download-only] fetching {model} -> {snapshot_dir}")
    snapshot_download(repo_id=model, local_dir=str(snapshot_dir))
    print(f"[download-only] done. Carry {snapshot_dir} to the air-gapped machine by hand.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert a Gemma checkpoint to ONNX for onnxruntime-genai.")
    parser.add_argument("--model", default="google/gemma-4-12B-it", help="Hugging Face repo id (online mode).")
    parser.add_argument("--input", default="", help="Local HF-format checkpoint folder (offline mode, -i hf_path).")
    parser.add_argument("--output", required=True, help="Output folder for the converted ONNX model.")
    parser.add_argument("--precision", default="int4", choices=["fp32", "fp16", "int4", "int8"])
    parser.add_argument("--execution-provider", default="cpu", choices=["cpu", "cuda", "dml"])
    parser.add_argument("--cache-dir", default="./hf_cache", help="HF download / temp export cache.")
    parser.add_argument(
        "--download-only", action="store_true",
        help="Only download the checkpoint to --snapshot-dir for hand-carrying (no conversion).",
    )
    parser.add_argument("--snapshot-dir", default="./carry", help="Target folder for --download-only.")
    parser.add_argument(
        "--extra-options",
        nargs="*",
        default=[],
        metavar="KEY=VALUE",
        help="Forwarded verbatim to the builder's --extra_options (e.g. hf_token=false for ungated repos with no token).",
    )
    args = parser.parse_args()

    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.download_only:
        _download_snapshot(args.model, Path(args.snapshot_dir).resolve())
        return

    module = _builder_module()  # importability check only (see _BUILDER_SHIM)
    _ensure_rope_compat()
    cli = [sys.executable, "-c", _BUILDER_SHIM]
    if args.input:
        input_path = Path(args.input).resolve()
        if not input_path.exists():
            print(f"ERROR: --input folder not found: {input_path}", file=sys.stderr)
            sys.exit(1)
        # 0.17 law (learned 2026-10-06): pass the BARE path. The builder's
        # help text advertises `hf_path: <path>` but no code parses that
        # prefix — with it, isdir() fails, hf_name falls back to the hub
        # model id, and the gated Gemma repo demands a token we don't need
        # (everything is local). Bare dir -> config/tokenizer load from disk.
        cli += ["-i", str(input_path)]
    else:
        cli += ["-m", args.model]
    cli += [
        "-o", str(output_dir),
        "-p", args.precision,
        "-e", args.execution_provider,
        "-c", str(Path(args.cache_dir).resolve()),
    ]
    if args.extra_options:
        cli += ["--extra_options", *args.extra_options]

    print("[convert] official builder CLI:", " ".join(cli))
    print(f"[convert] target: {args.precision} / {args.execution_provider} -> {output_dir}")
    if not args.input:
        print("[convert] ONLINE MODE: this downloads the checkpoint from Hugging Face —")
        print("[convert] the one internet touchpoint of the whole pipeline.")
    result = subprocess.run(cli)
    if result.returncode != 0:
        print(f"[convert] builder exited with code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)

    print(f"\n[convert] DONE. Verify {output_dir} contains: *.onnx + tokenizer files + genai_config.json.")
    print("[convert] Point the runtime's inference_settings.yaml (model.path) at this folder,")
    print("[convert] or POST it to a running server via /api/inference/model/load.")
    if shutil.which("nvidia-smi") is None and args.execution_provider != "cpu":
        print("[convert] NOTE: no NVIDIA driver visible — double-check the execution provider.", file=sys.stderr)


if __name__ == "__main__":
    main()
