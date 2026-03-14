from __future__ import annotations

import asyncio
import collections
import logging
import subprocess
import sys
import threading
from enum import Enum
from pathlib import Path

log = logging.getLogger(__name__)

_VENDOR_SCRIPT = str(Path(__file__).resolve().parent.parent / "vendor" / "diffusers_server.py")


class DaemonState(str, Enum):
    stopped = "stopped"
    starting = "starting"
    running = "running"
    error = "error"


class DiffusersDaemon:
    """Manages a vendored diffusers_server.py as a subprocess."""

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8189,
        model: str = "black-forest-labs/FLUX.2-klein-4b",
        device: str = "cuda",
        dtype: str = "bf16",
        offload: str = "none",
        quantization: str = "none",
        vae_tiling: bool = True,
    ) -> None:
        self._host = host
        self._port = port
        self._model = model
        self._device = device
        self._dtype = dtype
        self._offload = offload
        self._quantization = quantization
        self._vae_tiling = vae_tiling

        self._proc: subprocess.Popen | None = None
        self._state = DaemonState.stopped
        self._log_buf: collections.deque[str] = collections.deque(maxlen=200)
        self._reader_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def state(self) -> DaemonState:
        # Reconcile with actual process state
        if self._proc is not None and self._proc.poll() is not None:
            self._state = DaemonState.error
            self._proc = None
        return self._state

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def recent_logs(self) -> list[str]:
        return list(self._log_buf)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> dict:
        if self._proc is not None and self._proc.poll() is None:
            return {"status": "already_running"}

        self._state = DaemonState.starting
        self._log_buf.clear()

        cmd = [
            sys.executable, _VENDOR_SCRIPT,
            "--host", self._host,
            "--port", str(self._port),
            "--model", self._model,
            "--device", self._device,
            "--dtype", self._dtype,
            "--offload", self._offload,
            "--quantization", self._quantization,
        ]
        if self._vae_tiling:
            cmd.append("--vae-tiling")
        else:
            cmd.append("--no-vae-tiling")

        log.info("Starting diffusers daemon: %s", " ".join(cmd))

        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        # Background reader for stdout
        self._reader_thread = threading.Thread(
            target=self._read_stdout, daemon=True
        )
        self._reader_thread.start()

        # Poll /health with exponential backoff (up to 120s for model loading)
        ok = await self._wait_for_health(timeout=120)
        if ok:
            self._state = DaemonState.running
            log.info("Diffusers daemon is healthy")
            return {"status": "started"}
        else:
            self._state = DaemonState.error
            log.error("Diffusers daemon failed health check")
            return {"status": "error", "message": "Health check timed out"}

    async def stop(self) -> dict:
        if self._proc is None:
            self._state = DaemonState.stopped
            return {"status": "already_stopped"}

        log.info("Stopping diffusers daemon (pid=%s)", self._proc.pid)
        self._proc.terminate()
        try:
            await asyncio.to_thread(self._proc.wait, timeout=10)
        except subprocess.TimeoutExpired:
            log.warning("SIGTERM timed out, sending SIGKILL")
            self._proc.kill()
            await asyncio.to_thread(self._proc.wait, timeout=5)

        self._proc = None
        self._state = DaemonState.stopped
        return {"status": "stopped"}

    async def restart(self, **kwargs: str) -> dict:
        # Allow updating settings on restart
        for key in ("host", "port", "model", "device", "dtype", "offload", "quantization", "vae_tiling"):
            if key in kwargs:
                val = kwargs[key]
                attr = f"_{key}"
                if key == "port":
                    val = int(val)
                elif key == "vae_tiling":
                    val = val if isinstance(val, bool) else val in {"1", "true", "True"}
                setattr(self, attr, val)

        await self.stop()
        return await self.start()

    async def health_check(self) -> dict:
        import urllib.request
        import urllib.error
        import json

        url = f"{self.base_url}/health"
        try:
            resp = await asyncio.to_thread(
                lambda: urllib.request.urlopen(url, timeout=5).read()
            )
            return json.loads(resp)
        except Exception as exc:
            return {"status": "unreachable", "error": str(exc)}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_stdout(self) -> None:
        """Read process stdout into the ring buffer."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                self._log_buf.append(line.rstrip("\n"))
        except Exception:
            pass

    async def _wait_for_health(self, timeout: float = 120) -> bool:
        import urllib.request
        import urllib.error

        url = f"{self.base_url}/health"
        deadline = asyncio.get_event_loop().time() + timeout
        delay = 0.5
        while asyncio.get_event_loop().time() < deadline:
            # Check if process died
            if self._proc is not None and self._proc.poll() is not None:
                return False
            try:
                code = await asyncio.to_thread(
                    lambda: urllib.request.urlopen(url, timeout=3).status
                )
                if code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 1.5, 5.0)
        return False
