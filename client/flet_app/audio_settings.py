"""Audio settings dialog for Labhair-liom Flet GUI."""

from __future__ import annotations

import flet as ft
from typing import TYPE_CHECKING

from client.flet_app.theme import *

if TYPE_CHECKING:
    from client.main import ChatClient


class AudioSettingsDialog:
    """Dialog for selecting audio devices and adjusting volume."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client
        self._dialog: ft.AlertDialog | None = None

    def show(self):
        """Show the audio settings dialog."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            input_devices = [(i, d["name"]) for i, d in enumerate(devices) if d["max_input_channels"] > 0]
            output_devices = [(i, d["name"]) for i, d in enumerate(devices) if d["max_output_channels"] > 0]
        except Exception:
            input_devices = []
            output_devices = []

        current_input = getattr(self.client, '_input_device', None)
        current_output = getattr(self.client, '_output_device', None)

        input_options = [ft.dropdown.Option(key=str(i), text=name) for i, name in input_devices]
        output_options = [ft.dropdown.Option(key=str(i), text=name) for i, name in output_devices]

        input_dropdown = ft.Dropdown(
            label="Microphone",
            options=input_options,
            value=str(current_input) if current_input is not None else None,
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=10,
            width=350,
        )

        output_dropdown = ft.Dropdown(
            label="Speakers",
            options=output_options,
            value=str(current_output) if current_output is not None else None,
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=10,
            width=350,
        )

        input_slider = ft.Slider(
            min=0, max=100, value=100,
            label="Mic Volume",
            active_color=ACCENT,
        )

        output_slider = ft.Slider(
            min=0, max=100, value=100,
            label="Speaker Volume",
            active_color=ACCENT,
        )

        voice = getattr(self.client, 'voice', None)
        status_text = ft.Text(
            "Voice: Disconnected" if not voice else "Voice: Connected",
            color=ACCENT if voice else FG_DIM,
            size=12,
        )

        # Noise filter controls
        current_filter = getattr(voice, '_noise_filter', 'none') if voice else 'none'
        current_threshold = getattr(voice, '_noise_threshold', 0.02) if voice else 0.02

        noise_mode = ft.Dropdown(
            label="Noise Filter",
            options=[
                ft.dropdown.Option(key="none", text="Off"),
                ft.dropdown.Option(key="gate", text="Noise Gate"),
                ft.dropdown.Option(key="suppress", text="Noise Suppression"),
            ],
            value=current_filter,
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=10,
            width=350,
        )

        noise_threshold = ft.Slider(
            min=0, max=100, value=int(current_threshold * 1000),
            label="Gate Threshold",
            active_color=ACCENT,
        )

        noise_desc = ft.Text(
            "Noise Gate: silences mic when volume is below the threshold.\n"
            "Suppression: estimates and removes constant background noise.",
            color=FG_DIM, size=11,
        )

        # Camera selection
        try:
            import cv2
            cam_count = 5
            cam_options = []
            for i in range(cam_count):
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cam_options.append(ft.dropdown.Option(key=str(i), text=f"Camera {i} ({w}x{h})"))
                    cap.release()
                else:
                    cap.release()
                    break
        except ImportError:
            cam_options = [ft.dropdown.Option(key="0", text="Camera 0")]
        current_cam = str(getattr(self.client, 'cam', 0))
        cam_dropdown = ft.Dropdown(
            label="Camera", options=cam_options, value=current_cam,
            bgcolor=BG_INPUT, color=FG, border_color=DIVIDER,
            border_radius=8, content_padding=10, width=350,
        )

        # Monitor selection
        try:
            from client.screencap import list_monitors
            monitors = list_monitors()
            mon_options = [ft.dropdown.Option(key=str(m["index"]), text=m.get("label", f"Monitor {m['index']}")) for m in monitors if m.get("index", 0) > 0]
            if not mon_options:
                mon_options = [ft.dropdown.Option(key="0", text="All screens")]
        except Exception:
            mon_options = [ft.dropdown.Option(key="0", text="All screens")]
        current_mon = str(getattr(self.client, 'monitor', 0))
        monitor_dropdown = ft.Dropdown(
            label="Screen / Monitor", options=mon_options, value=current_mon,
            bgcolor=BG_INPUT, color=FG, border_color=DIVIDER,
            border_radius=8, content_padding=10, width=350,
        )

        async def on_apply(e):
            self.client._input_device = int(input_dropdown.value) if input_dropdown.value else None
            self.client._output_device = int(output_dropdown.value) if output_dropdown.value else None
            if voice:
                voice._muted = False
                voice._deafened = False
                mode = noise_mode.value or "none"
                threshold = noise_threshold.value / 1000.0 if noise_threshold.value else 0.02
                voice.set_noise_filter(mode, threshold)
            # Save video settings
            try:
                cam_val = int(cam_dropdown.value) if cam_dropdown.value else 0
                mon_val = int(monitor_dropdown.value) if monitor_dropdown.value else 0
                self.client.cam = cam_val
                self.client.monitor = mon_val
                self.client.settings.camera_index = cam_val
                self.client.settings.screen_monitor = mon_val
                self.client.settings.save()
            except Exception:
                pass
            self._close_dialog()

        def on_cancel(e):
            self._close_dialog()

        self._dialog = ft.AlertDialog(
            title=ft.Text("Audio Settings", color=FG),
            content=ft.Container(
                content=ft.Column([
                    status_text,
                    ft.Divider(color=DIVIDER),
                    input_dropdown,
                    input_slider,
                    ft.Divider(color=DIVIDER),
                    output_dropdown,
                    output_slider,
                    ft.Divider(color=DIVIDER),
                    ft.Text("Noise Filter", color=FG, size=14, weight=ft.FontWeight.BOLD),
                    noise_mode,
                    noise_threshold,
                    noise_desc,
                    ft.Divider(color=DIVIDER),
                    ft.Text("Video", color=FG, size=14, weight=ft.FontWeight.BOLD),
                    cam_dropdown,
                    monitor_dropdown,
                ], spacing=10, scroll=ft.ScrollMode.AUTO),
                width=400,
                height=450,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=on_cancel, tooltip="Discard changes"),
                ft.ElevatedButton("Apply", on_click=on_apply, bgcolor=ACCENT, color=FG, tooltip="Save audio settings"),
            ],
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(self._dialog)
        self._dialog.open = True
        self.page.update()

    def _close_dialog(self):
        if self._dialog:
            self._dialog.open = False
            self.page.update()
            try:
                self.page.overlay.remove(self._dialog)
            except ValueError:
                pass
