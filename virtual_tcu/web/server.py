import asyncio
import json
import time
from pathlib import Path

from virtual_tcu import paths
from virtual_tcu.bootstrap import exec_restart
from virtual_tcu.config.constants import DEFAULTS
from virtual_tcu.config.store import ConfigStore
from virtual_tcu.config.web_bind import (
    bind_error_hint,
    format_startup_urls,
    network_status,
    resolve_bind,
)
from virtual_tcu.deps import WSMsgType, web
from virtual_tcu.input.vjoy_output import VJoyOutput
from virtual_tcu.logic.tcu import TCULogic
from virtual_tcu.telemetry.log_capture import log_capture
from virtual_tcu.telemetry.logger import TelemetryLogger
from virtual_tcu.telemetry.receiver import TelemetryReceiver
from virtual_tcu.telemetry.udp_hub import parse_udp_hub_targets

_NO_UI_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Virtual TCU — Web UI unavailable</title>
</head>
<body>
  <h1>Web UI unavailable</h1>
  <p>Dashboard assets missing. Run UI build process.</p>
</body>
</html>
"""


def _dist_index() -> Path | None:
    p = paths.web_dist_dir() / "index.html"
    return p if p.is_file() else None


def _dist_assets_dir() -> Path | None:
    p = paths.web_dist_dir() / "assets"
    return p if p.is_dir() else None


class WebServer:
    def __init__(
        self,
        receiver: TelemetryReceiver,
        tcu: TCULogic,
        config: ConfigStore,
        logger: TelemetryLogger,
        *,
        ui_mode: str = "full",
    ):
        self._recv = receiver
        self._tcu = tcu
        self._config = config
        self._logger = logger
        self._ui_mode = "view_only" if ui_mode == "view_only" else "full"
        self._clients: set = set()
        self._ui_available = _dist_index() is not None
        self._runner = None
        self._site = None
        self._bind_host, self._bind_port = resolve_bind(config)

    async def index(self, request):
        dist = _dist_index()
        if dist is not None:
            return web.FileResponse(dist)
        return web.Response(
            text=_NO_UI_HTML,
            content_type="text/html; charset=utf-8",
            status=503,
        )

    async def websocket_handler(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        self._clients.add(ws)
        try:
            await ws.send_json(
                {
                    "type": "init",
                    "data": {
                        "mode": self._tcu.mode.value,
                        "live": self._recv.is_live,
                        "shift_count": self._tcu.shift_count,
                        "packets_total": self._recv.packets_total,
                        "config": self._config.data,
                        "defaults": DEFAULTS,
                        "log_status": self._logger.status,
                        "system_logs": log_capture.snapshot(),
                        "web_urls": network_status(self._config),
                        "effective_output_mode": (
                            "vjoy" if isinstance(self._tcu._kb, VJoyOutput) else "keyboard"
                        ),
                        "ui_mode": self._ui_mode,
                    },
                }
            )
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                        if isinstance(data, dict):
                            await self._handle_client_msg(data, ws)
                    except Exception as e:
                        print(f"[WS] msg error: {e}")
                elif msg.type == WSMsgType.ERROR:
                    break
        finally:
            self._clients.discard(ws)
        return ws

    async def _handle_client_msg(self, msg: dict, ws):
        t = msg.get("type")
        if t == "set_mode":
            self._tcu.set_mode(msg.get("mode", ""))
        elif t == "set_config":
            key = msg.get("key", "")
            val = msg.get("value")
            if key in ("web_host", "web_port", "udp_port"):
                await ws.send_json(
                    {
                        "type": "network_changed",
                        "ok": False,
                        "error": "use_set_network",
                        "data": network_status(self._config),
                    }
                )
                return
            self._config.set(key, val)
            if key in ("shift_key_up", "shift_key_down"):
                self._tcu.refresh_shift_keys()
            if key == "hud_template":
                await self._broadcast_json({"type": "config_update", "data": {"hud_template": val}})
        elif t == "set_network":
            await self._apply_network(msg)
        elif t == "save_network_and_restart":
            await self._save_network_and_restart(msg, ws)
        elif t == "set_web_bind":
            msg = {
                "web_host": msg.get("host", ""),
                "web_port": msg.get("port", 8765),
                "udp_port": self._config.get("udp_port", 5555),
            }
            await self._apply_network(msg)
        elif t == "reset_config":
            self._config.reset()
            self._tcu.set_mode(str(self._config.get("current_mode", "COMFORT")))
            self._tcu.refresh_shift_keys()
            await self._broadcast_json({"type": "config_reset", "data": self._config.data})
        elif t == "relearn_profile":
            ok, profile_key = self._tcu.relearn_current_profile()
            await self._broadcast_json(
                {"type": "profile_relearned", "ok": ok, "profile_key": profile_key}
            )
        elif t == "log_start":
            mode = msg.get("mode", "events")
            output_format = msg.get("format", self._config.get("log_output_format", "bin.gz"))
            if isinstance(output_format, str):
                self._config.set("log_output_format", output_format)
            self._logger.start(mode, str(output_format))
            chart_on_save = str(output_format).lower() == "csv_chart"
            self._tcu._fusion_logger.set_chart_on_save(chart_on_save)
            await ws.send_json({"type": "log_status", "data": self._logger.status})
        elif t == "log_stop":
            save_as = msg.get("save_as", "file")
            if save_as == "fusion_snapshot":
                fmt = str(self._config.get("log_output_format", "bin.gz")).lower()
                self._tcu._fusion_logger.set_chart_on_save(fmt == "csv_chart")
                filename = self._tcu.dump_fusion_snapshot(str(msg.get("reason", "manual_dump")))
                self._logger.stop(discard=True)
                path = str(paths.log_dir() / filename) if filename else None
            else:
                path = self._logger.stop()
            await ws.send_json(
                {"type": "log_status", "data": self._logger.status, "last_file": path}
            )
            # Async conversion when a raw .bin.gz capture is kept (upstream log_converter).
            if path and save_as != "fusion_snapshot":
                fmt = str(self._config.get("log_output_format", "bin.gz"))
                if fmt != "bin.gz":
                    from pathlib import Path as _Path

                    from virtual_tcu.telemetry.log_converter import convert_replay_async

                    bin_path = _Path(path)
                    if bin_path.suffix == ".gz":
                        loop = asyncio.get_running_loop()

                        def _on_done(files):
                            names = [f.name for f in files]
                            msg = {
                                "type": "log_conversion",
                                "ok": True,
                                "format": fmt,
                                "files": names,
                            }
                            print(f"[LogConverter] Converted to {fmt}: {names}")
                            asyncio.run_coroutine_threadsafe(self._broadcast_json(msg), loop)

                        def _on_error(e):
                            msg = {
                                "type": "log_conversion",
                                "ok": False,
                                "format": fmt,
                                "error": str(e),
                            }
                            asyncio.run_coroutine_threadsafe(self._broadcast_json(msg), loop)

                        convert_replay_async(bin_path, fmt, on_done=_on_done, on_error=_on_error)
        elif t == "trigger_fusion_snapshot":
            fmt = str(self._config.get("log_output_format", "bin.gz")).lower()
            self._tcu._fusion_logger.set_chart_on_save(fmt == "csv_chart")
            self._tcu.dump_fusion_snapshot(str(msg.get("reason", "manual_dump")))
        elif t == "request_graph":
            await ws.send_json({"type": "graph_data", "data": self._tcu.snapshot_graph()})
        elif t == "export_profile":
            export = {
                "version": "v12",
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "config": self._config.data,
            }
            await ws.send_json({"type": "profile_export", "data": export})
        elif t == "restart_backend":
            # Send ack before restarting — the process will be replaced imminently.
            await ws.send_json({"type": "restart_ack"})
            # Small delay so the WS frame is flushed before execv.
            await asyncio.sleep(0.1)
            exec_restart()

        elif t == "import_profile":
            try:
                imported = msg.get("data", {})
                if isinstance(imported, dict) and "config" in imported:
                    for k, v in imported["config"].items():
                        if k in DEFAULTS:
                            self._config.set(k, v)
                    self._tcu.refresh_shift_keys()
                    await ws.send_json(
                        {
                            "type": "profile_imported",
                            "ok": True,
                            "data": self._config.data,
                        }
                    )
                else:
                    await ws.send_json(
                        {
                            "type": "profile_imported",
                            "ok": False,
                            "error": "invalid format",
                        }
                    )
            except Exception as e:
                await ws.send_json({"type": "profile_imported", "ok": False, "error": str(e)})

    def _hub_config_from_msg(self, msg: dict, udp_port: int) -> tuple[bool, str, str]:
        hub_enabled = bool(msg.get("udp_hub_enabled", self._config.get("udp_hub_enabled", False)))
        hub_targets = str(
            msg.get("udp_hub_targets", self._config.get("udp_hub_targets", ""))
        ).strip()
        if hub_enabled and not hub_targets:
            return hub_enabled, hub_targets, "invalid_udp_hub_targets"
        if hub_enabled or hub_targets:
            try:
                parse_udp_hub_targets(hub_targets, udp_port)
            except ValueError:
                return hub_enabled, hub_targets, "invalid_udp_hub_targets"
        return hub_enabled, hub_targets, ""

    async def _save_network_and_restart(self, msg: dict, ws):
        host = msg.get("web_host", "")
        web_port = msg.get("web_port", 8765)
        udp_port = msg.get("udp_port", 5555)
        old_config = dict(self._config.data)
        ok, err = self._config.set_network(host, web_port, udp_port)
        if not ok:
            await ws.send_json(
                {
                    "type": "network_changed",
                    "ok": False,
                    "error": err,
                    "data": network_status(self._config),
                }
            )
            return

        udp_port_int = int(self._config.get("udp_port", 5555))
        hub_enabled, hub_targets, hub_err = self._hub_config_from_msg(msg, udp_port_int)
        if hub_err:
            self._config.data = old_config
            self._config.save()
            await ws.send_json(
                {
                    "type": "network_changed",
                    "ok": False,
                    "error": hub_err,
                    "data": network_status(self._config),
                }
            )
            return

        self._config.set("udp_hub_enabled", hub_enabled)
        self._config.set("udp_hub_targets", hub_targets)
        await ws.send_json(
            {
                "type": "network_changed",
                "ok": True,
                "data": network_status(self._config),
            }
        )
        await ws.send_json({"type": "restart_ack"})
        await asyncio.sleep(0.1)
        exec_restart()

    async def _apply_network(self, msg: dict):
        host = msg.get("web_host", "")
        web_port = msg.get("web_port", 8765)
        udp_port = msg.get("udp_port", 5555)
        old_udp = self._recv.bound_port
        old_web = (self._bind_host, self._bind_port)

        ok, err = self._config.set_network(host, web_port, udp_port)
        if not ok:
            await self._broadcast_json(
                {
                    "type": "network_changed",
                    "ok": False,
                    "error": err,
                    "data": network_status(self._config),
                }
            )
            return

        new_udp = int(self._config.get("udp_port", 5555))
        if new_udp != old_udp and not self._recv.restart():
            self._config.set_network(old_web[0], old_web[1], old_udp)
            await self._broadcast_json(
                {
                    "type": "network_changed",
                    "ok": False,
                    "error": "udp_bind_failed",
                    "data": network_status(self._config),
                }
            )
            return

        new_web = resolve_bind(self._config)
        web_changed = new_web != old_web

        # If only UDP changed (or nothing web-related), broadcast and return.
        # The WS listener stays up so clients receive this message normally.
        if not web_changed:
            await self._broadcast_json(
                {
                    "type": "network_changed",
                    "ok": True,
                    "data": network_status(self._config),
                }
            )
            return

        # Web bind changed → restart_listener() will drop every WS client the
        # moment it stops the old site, so any message broadcast *after* the
        # restart never reaches anyone. Broadcast optimistic-success first so
        # the frontend can record the new URL and switch over on reconnect.
        await self._broadcast_json(
            {
                "type": "network_changed",
                "ok": True,
                "data": network_status(self._config),
            }
        )
        # Small grace period so the message actually flushes before we yank
        # the socket out from under the clients.
        await asyncio.sleep(0.1)

        if not await self.restart_listener():
            # restart_listener() rolls back to the previous bind on failure,
            # so the old listener is back up and clients reconnecting to it
            # will pick up this corrected failure broadcast.
            await self._broadcast_json(
                {
                    "type": "network_changed",
                    "ok": False,
                    "error": "bind_failed",
                    "data": network_status(self._config),
                }
            )

    async def _broadcast_json(self, payload: dict):
        dead = set()
        for client_ws in list(self._clients):
            try:
                await client_ws.send_json(payload)
            except Exception:
                dead.add(client_ws)
        if dead:
            self._clients -= dead

    async def broadcast_loop(self):
        tcu_interval = 1.0 / 60.0
        broadcast_every_n = 2
        tick = 0
        while True:
            await asyncio.sleep(tcu_interval)
            tick += 1

            if tick % broadcast_every_n != 0:
                continue
            if not self._clients:
                continue

            td = self._recv.latest()

            payload_tel = {"type": "telemetry", "data": self._tcu.snapshot(td)}
            payload_st = {
                "type": "state",
                "data": {
                    "mode": self._tcu.mode.value,
                    "live": self._recv.is_live,
                    "shift_count": self._tcu.shift_count,
                    "packets_total": self._recv.packets_total,
                },
            }

            dead = set()

            async def _send_safe(client_ws, _pt=payload_tel, _ps=payload_st, _d=dead):
                try:
                    await client_ws.send_json(_pt)
                    await client_ws.send_json(_ps)
                except Exception:
                    _d.add(client_ws)

            # Eşzamanlı yayın (Race-free & Lock-free broadcast)
            tasks = [_send_safe(client) for client in self._clients]
            if tasks:
                await asyncio.gather(*tasks)

            if dead:
                self._clients -= dead

    async def _bind_with_fallback(self, host: str, port: int) -> tuple[str, int]:
        try:
            await self._start_site(host, port)
            return host, port
        except OSError as e:
            if host == "127.0.0.1":
                raise
            print(f"  [!] Web UI bind failed on {host}:{port} - {bind_error_hint(e)}")
            print(f"  [.] Falling back to 127.0.0.1:{port}")
            await self._start_site("127.0.0.1", port)
            self._config.set_web_bind("127.0.0.1", port)
            print("  [!] LAN access disabled - fix the issue above, then set 0.0.0.0 again")
            return "127.0.0.1", port

    async def restart_listener(self) -> bool:
        host, port = resolve_bind(self._config)
        if host == self._bind_host and port == self._bind_port:
            return True

        old_host, old_port = self._bind_host, self._bind_port
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

        try:
            self._bind_host, self._bind_port = await self._bind_with_fallback(host, port)
            urls = format_startup_urls(self._config)
            print(f"  [OK] Web UI rebound at {urls[0]}" + (f", {urls[1]}" if len(urls) > 1 else ""))
            return True
        except OSError as e:
            print(f"  [!] Web UI rebind failed on {host}:{port} - {bind_error_hint(e)}")
            self._config.set_web_bind(old_host, old_port)
            try:
                self._bind_host, self._bind_port = old_host, old_port
                await self._start_site(old_host, old_port)
                print(f"  [OK] Web UI restored at {old_host}:{old_port}")
            except OSError as e2:
                print(f"  [!!] Web UI restore failed - {e2}")
            return False

    async def _start_site(self, host: str, port: int):
        app = web.Application()
        assets = _dist_assets_dir()
        if assets is not None:
            app.router.add_static("/assets", assets)
        app.router.add_get("/", self.index)
        app.router.add_get("/ws", self.websocket_handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, host, port, reuse_address=True)
        try:
            await self._site.start()
        except OSError as e:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            raise OSError(f"Web UI bind failed on {host}:{port} - {bind_error_hint(e)}") from e

    async def start(self):
        host, port = resolve_bind(self._config)
        self._bind_host, self._bind_port = await self._bind_with_fallback(host, port)
        if self._ui_available:
            print(f"  [OK] Web UI (dist: {paths.web_dist_dir()})")
        else:
            print(f"  [!] Web UI assets missing ({paths.web_dist_dir()})")

        loop = asyncio.get_running_loop()

        def on_sys_log(msg):
            asyncio.run_coroutine_threadsafe(self._broadcast_json(msg), loop)

        log_capture.add_listener(on_sys_log)

        def on_fusion_snapshot(reason, filename, chart_filename=None):
            payload = {
                "type": "fusion_snapshot",
                "reason": reason,
                "filename": filename,
            }
            if chart_filename:
                payload["chart_filename"] = chart_filename
            asyncio.run_coroutine_threadsafe(self._broadcast_json(payload), loop)

        self._tcu._fusion_logger.on_snapshot_created = on_fusion_snapshot

        asyncio.create_task(self.broadcast_loop())

    async def stop(self):
        if self._site is not None:
            await self._site.stop()
            self._site = None
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
        for ws in list(self._clients):
            await ws.close()
