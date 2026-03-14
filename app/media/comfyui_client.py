from __future__ import annotations

import asyncio
import json
import logging
import urllib.error
import urllib.request
from copy import deepcopy

log = logging.getLogger(__name__)

# Minimal txt2img workflow for FLUX-style models in ComfyUI.
# Placeholders: {{prompt}}, {{width}}, {{height}}, {{steps}}, {{seed}}, {{model}}
DEFAULT_FLUX_WORKFLOW: dict = {
    "3": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "{{model}}"},
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "{{prompt}}",
            "clip": ["3", 1],
        },
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "",
            "clip": ["3", 1],
        },
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": "{{width}}",
            "height": "{{height}}",
            "batch_size": 1,
        },
    },
    "10": {
        "class_type": "KSampler",
        "inputs": {
            "seed": "{{seed}}",
            "steps": "{{steps}}",
            "cfg": 3.5,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["3", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["10", 0],
            "vae": ["3", 2],
        },
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": "webui",
            "images": ["8", 0],
        },
    },
}


def _substitute(obj: object, replacements: dict[str, str | int]) -> object:
    """Recursively replace {{key}} placeholders in a workflow dict."""
    if isinstance(obj, str):
        for key, val in replacements.items():
            placeholder = "{{" + key + "}}"
            if obj == placeholder:
                return val  # preserve type for ints
            obj = obj.replace(placeholder, str(val))
        return obj
    if isinstance(obj, dict):
        return {k: _substitute(v, replacements) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_substitute(v, replacements) for v in obj]
    return obj


class ComfyUIClient:
    """HTTP client for an external ComfyUI instance."""

    def __init__(
        self,
        base_url: str,
        workflow_template: dict | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._workflow = workflow_template or DEFAULT_FLUX_WORKFLOW

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self._base}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(f"{self._base}{path}", timeout=30) as resp:
            return json.loads(resp.read())

    def _get_bytes(self, path: str) -> bytes:
        with urllib.request.urlopen(f"{self._base}{path}", timeout=60) as resp:
            return resp.read()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def health(self) -> bool:
        try:
            result = await asyncio.to_thread(self._get, "/system_stats")
            return isinstance(result, dict)
        except Exception:
            return False

    async def queue_prompt(
        self,
        *,
        prompt: str,
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        seed: int = -1,
        model: str = "",
    ) -> str:
        """Queue a prompt using the workflow template. Returns prompt_id."""
        import random

        if seed < 0:
            seed = random.randint(0, 2**31 - 1)

        workflow = deepcopy(self._workflow)
        replacements = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "steps": steps,
            "seed": seed,
            "model": model,
        }
        workflow = _substitute(workflow, replacements)

        body = {"prompt": workflow}
        result = await asyncio.to_thread(self._post, "/prompt", body)
        return result["prompt_id"]

    async def poll_until_complete(
        self,
        prompt_id: str,
        *,
        timeout: float = 300,
        interval: float = 2.0,
    ) -> dict:
        import time

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                history = await asyncio.to_thread(
                    self._get, f"/history/{prompt_id}"
                )
                if prompt_id in history:
                    entry = history[prompt_id]
                    status = entry.get("status", {})
                    if status.get("completed", False):
                        return entry
                    if status.get("status_str") == "error":
                        return {"status": "failed", "error": str(status)}
            except Exception:
                pass
            await asyncio.sleep(interval)
        return {"status": "timeout", "error": f"Timed out after {timeout}s"}

    async def download_image(
        self, filename: str, subfolder: str = "", type_: str = "output"
    ) -> bytes:
        params = f"?filename={filename}&subfolder={subfolder}&type={type_}"
        return await asyncio.to_thread(self._get_bytes, f"/view{params}")

    def set_workflow_template(self, workflow: dict) -> None:
        self._workflow = workflow
