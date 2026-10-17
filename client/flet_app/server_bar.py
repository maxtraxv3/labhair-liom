"""Left server icon rail for Labhair-liom Flet GUI."""

from __future__ import annotations

import flet as ft
from typing import TYPE_CHECKING

from client.flet_app.theme import *

if TYPE_CHECKING:
    from client.main import ChatClient


class ServerBar:
    """Vertical icon bar on the left edge — servers, DM, voice controls."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client
        self._server_buttons: list[ft.Control] = []
        self._screen_active = False
        self._selected_index: int | None = None
        self._dm_badge_dot: ft.Container | None = None

        # Callbacks (set by LabhairLiomApp)
        self.on_dm_click = None
        self.on_server_click = None
        self.on_settings_click = None
        self.on_viewer_click = None
        self.on_threads_click = None
        self.on_status_click = None
        self.on_audio_settings_click = None
        self.on_user_settings_click = None
        self.on_voice_disconnect = None  # set by app

    def build(self) -> ft.Container:
        """Build the server bar."""
        self._user_btn = self._make_icon_button(
            icon=ft.Icons.ACCOUNT_CIRCLE,
            label="User Settings",
            on_click=self._on_user_settings,
        )

        self._dm_button = self._make_icon_button(
            icon=ft.Icons.HOME_OUTLINED,
            label="Direct Messages",
            on_click=self._on_dm_click,
            badge=True,
        )

        self._add_server_btn = self._make_icon_button(
            icon=ft.Icons.ADD,
            label="Add Server",
            on_click=self._on_add_server,
        )

        self._join_server_btn = self._make_icon_button(
            icon=ft.Icons.DOWNLOAD,
            label="Join via Invite",
            on_click=self._on_join_server,
        )

        self._mute_btn = self._make_icon_button(
            icon=ft.Icons.MIC_OFF_OUTLINED,
            label="Mute",
            on_click=self._on_mute,
        )

        self._deafen_btn = self._make_icon_button(
            icon=ft.Icons.HEADSET_OFF_OUTLINED,
            label="Deafen",
            on_click=self._on_deafen,
        )

        self._disconnect_btn = self._make_icon_button(
            icon=ft.Icons.PHONE_DISABLED,
            label="Disconnect",
            on_click=self._on_disconnect,
            visible=False,
        )

        self._audio_settings_btn = self._make_icon_button(
            icon=ft.Icons.SETTINGS_OUTLINED,
            label="Audio Settings",
            on_click=self._on_audio_settings,
        )

        self._viewer_btn = self._make_icon_button(
            icon=ft.Icons.VIDEOCAM_OUTLINED,
            label="Viewer",
            on_click=self._on_viewer,
        )

        self._screen_btn = self._make_icon_button(
            icon=ft.Icons.SCREEN_SHARE_OUTLINED,
            label="Share Screen",
            on_click=self._on_screen,
        )

        self._camera_btn = self._make_icon_button(
            icon=ft.Icons.CAMERA_ALT_OUTLINED,
            label="Camera",
            on_click=self._on_camera,
        )

        self._buttons_column = ft.Column(
            controls=[
                self._user_btn,
                self._dm_button,
                ft.Divider(height=1, color=DIVIDER, leading_indent=8, trailing_indent=8),
                *self._server_buttons,
                ft.Divider(height=1, color=DIVIDER, leading_indent=8, trailing_indent=8),
                self._add_server_btn,
                self._join_server_btn,
                ft.Divider(height=1, color=DIVIDER, leading_indent=8, trailing_indent=8),
                self._disconnect_btn,
                self._mute_btn,
                self._deafen_btn,
                ft.Divider(height=1, color=DIVIDER, leading_indent=8, trailing_indent=8),
                self._viewer_btn,
                self._screen_btn,
                self._camera_btn,
                self._audio_settings_btn,
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Container(
            content=self._buttons_column,
            width=54,
            bgcolor=BG_DARKER,
            padding=ft.padding.symmetric(horizontal=0, vertical=8),
            alignment=ft.alignment.top_center,
        )

    def _make_icon_button(
        self,
        icon: str,
        label: str,
        on_click=None,
        visible: bool = True,
        badge: bool = False,
    ) -> ft.Control:
        """Create a circular icon button with tooltip.

        With ``badge=True`` the returned button wraps a small orange dot in the
        top-right corner (toggled via :meth:`set_dm_badge`).
        """
        btn = ft.Container(
            content=ft.Icon(name=icon, color=FG_DIM, size=20),
            width=36,
            height=36,
            border_radius=18,
            bgcolor=BG_DARK,
            alignment=ft.alignment.center,
            on_click=on_click,
            on_hover=lambda e: self._on_hover(e, btn),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
        )
        btn.tooltip = label
        if badge:
            self._dm_badge_dot = ft.Container(
                width=10, height=10, bgcolor="#faa61a",
                border_radius=5, visible=False,
            )
            stack = ft.Stack(
                controls=[
                    btn,
                    ft.Container(content=self._dm_badge_dot, right=1, top=1),
                ],
                width=40,
                height=40,
            )
            return stack
        return btn

    def set_dm_badge(self, show: bool):
        """Show/hide the orange 'unread DMs / friend requests' dot."""
        if not getattr(self, "_dm_badge_dot", None):
            return
        if self._dm_badge_dot.visible != bool(show):
            self._dm_badge_dot.visible = bool(show)
            try:
                self._dm_badge_dot.update()
            except Exception:
                pass

    def _on_hover(self, e, btn: ft.Container):
        """Hover effect on icon buttons."""
        is_screen = btn is getattr(self, "_screen_btn", None)
        if e.data == "true":
            if is_screen and self._screen_active:
                btn.bgcolor = RED
                btn.content.color = "#ffffff"
                btn.update()
                return
            btn.bgcolor = ACCENT
            btn.content.color = FG
        else:
            if is_screen and self._screen_active:
                btn.bgcolor = RED_BG
                btn.content.color = RED
                btn.update()
                return
            btn.bgcolor = BG_DARK
            btn.content.color = FG_DIM
        btn.update()

    def set_screen_btn(self, active: bool):
        """Reflect screen-share state on the toolbar button (red = streaming)."""
        self._screen_active = bool(active)
        icon = self._screen_btn.content
        if self._screen_active:
            icon.color = RED
            icon.name = ft.Icons.SCREEN_SHARE
            self._screen_btn.bgcolor = RED_BG
            self._screen_btn.tooltip = "Stop screen share"
        else:
            icon.color = FG_DIM
            icon.name = ft.Icons.SCREEN_SHARE_OUTLINED
            self._screen_btn.bgcolor = BG_DARK
            self._screen_btn.tooltip = "Share Screen"

    def add_server(self, server_id: str, name: str, index: int, icon_url: str = ""):
        """Add a server icon to the bar."""
        btn = self._make_server_button(server_id, name, name[0].upper() if name else "?", index, icon_url)
        self._server_buttons.append(btn)
        self._rebuild()

    def _make_server_button(self, server_id: str, name: str, icon: str, index: int, icon_url: str = "") -> ft.Tooltip:
        """Create a server icon button — shows image if icon_url provided, else first letter."""
        if icon_url:
            content = ft.Image(src=icon_url, width=36, height=36, fit=ft.ImageFit.COVER, border_radius=18)
        else:
            content = ft.Text(icon, color=FG, size=16, weight=ft.FontWeight.BOLD)
        btn = ft.Container(
            content=content,
            width=36,
            height=36,
            border_radius=18,
            bgcolor=ACCENT if not icon_url else None,
            alignment=ft.alignment.center,
            on_click=lambda e, sid=server_id: self._on_server_click(sid),
            on_hover=lambda e, b=None: self._on_hover(e, btn),
            animate=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            data=server_id,
        )
        btn.tooltip = name
        return btn

    def _rebuild(self):
        """Rebuild the buttons column."""
        self._buttons_column.controls.clear()
        self._buttons_column.controls.extend([
            self._user_btn,
            self._dm_button,
            ft.Divider(height=1, color=DIVIDER, leading_indent=8, trailing_indent=8),
            *self._server_buttons,
            ft.Divider(height=1, color=DIVIDER, leading_indent=8, trailing_indent=8),
            self._add_server_btn,
            self._join_server_btn,
            ft.Divider(height=1, color=DIVIDER, leading_indent=8, trailing_indent=8),
            self._disconnect_btn,
            self._mute_btn,
            self._deafen_btn,
            ft.Divider(height=1, color=DIVIDER, leading_indent=8, trailing_indent=8),
            self._viewer_btn,
            self._screen_btn,
            self._camera_btn,
            self._audio_settings_btn,
        ])
        self.page.update()

    def _on_dm_click(self, e):
        """Switch to DM view."""
        if self.on_dm_click:
            self.on_dm_click()

    def _on_server_click(self, server_id: str):
        """Join a server channel view."""
        if self.on_server_click:
            self.on_server_click(server_id)
        else:
            sid = int(server_id)
            self.client.current_server_id = sid
            self.page.run_task(self.client.send_channel_list, sid)
            self.page.run_task(self.client.send_member_list, sid)

    def _on_add_server(self, e):
        """Show create server dialog."""
        self._show_create_server_dialog()

    def _on_join_server(self, e):
        """Show join server dialog."""
        self._show_join_server_dialog()

    def _on_mute(self, e):
        """Toggle microphone mute."""
        self.page.run_task(self._toggle_mute)

    def _on_deafen(self, e):
        """Toggle deafen."""
        self.page.run_task(self._toggle_deafen)

    def _on_disconnect(self, e):
        """Disconnect from voice."""
        self.page.run_task(self._disconnect_voice)

    def _on_audio_settings(self, e):
        """Open audio settings."""
        if self.on_audio_settings_click:
            self.on_audio_settings_click()

    def _on_viewer(self, e):
        """Toggle viewer window."""
        if self.on_viewer_click:
            self.on_viewer_click()

    def _on_user_settings(self, e):
        """Open user settings."""
        if self.on_user_settings_click:
            self.on_user_settings_click()

    def _on_screen(self, e):
        """Toggle screen sharing."""
        self.page.run_task(self._toggle_screen)

    def _on_camera(self, e):
        """Toggle camera."""
        self.page.run_task(self._toggle_camera)

    async def _toggle_screen(self):
        """Toggle screen sharing on/off.

        Uses the client-level wrappers so presence, the local streaming dot,
        and the capture lifecycle all stay in sync (the engine itself is only
        touched via ``client.start_screen()`` / ``client.stop_screen()``).
        """
        video = getattr(self.client, 'video', None) or self.client._ensure_video_engine()
        if not video:
            self.page.snack_bar = ft.SnackBar(
                ft.Text("Video engine not available", color=FG), bgcolor="#f23f43",
            )
            self.page.snack_bar.open = True
            self.page.update()
            return
        if video.screen_active:
            self.client.stop_screen()
            self.set_screen_btn(False)
        else:
            # Apply saved monitor setting
            mon = getattr(self.client, 'monitor', 0)
            self.client.monitor = mon
            try:
                self.client.start_screen()
            except Exception as exc:
                self.page.snack_bar = ft.SnackBar(
                    ft.Text(f"Screen share failed: {exc}", color=FG), bgcolor="#f23f43",
                )
                self.page.snack_bar.open = True
                self.set_screen_btn(False)
                self.page.update()
                return
            eng = getattr(self.client, 'video', None) or video
            self.set_screen_btn(bool(getattr(eng, 'screen_active', False)))
        self.page.update()

    async def _toggle_camera(self):
        """Toggle camera on/off."""
        video = getattr(self.client, 'video', None) or self.client._ensure_video_engine()
        if not video:
            self.page.snack_bar = ft.SnackBar(
                ft.Text("Video engine not available", color=FG), bgcolor="#f23f43",
            )
            self.page.snack_bar.open = True
            self.page.update()
            return
        if video.camera_active:
            video.stop_camera()
            self._camera_btn.content.color = FG_DIM
        else:
            # Apply saved camera setting
            cam_idx = getattr(self.client, 'cam', 0)
            video.camera_index = cam_idx
            # Check if camera is accessible before starting
            import cv2
            cap = cv2.VideoCapture(cam_idx)
            if not cap.isOpened():
                cap.release()
                self.page.snack_bar = ft.SnackBar(
                    ft.Text(f"No camera found at index {cam_idx}", color=FG), bgcolor="#f23f43",
                )
                self.page.snack_bar.open = True
                self.page.update()
                return
            cap.release()
            try:
                video.start_camera()
                self._camera_btn.content.color = ACCENT
            except Exception as exc:
                self.page.snack_bar = ft.SnackBar(
                    ft.Text(f"Camera failed: {exc}", color=FG), bgcolor="#f23f43",
                )
                self.page.snack_bar.open = True
        self.page.update()

    async def _toggle_mute(self):
        voice = getattr(self.client, 'voice', None)
        if voice:
            if voice.is_muted:
                voice.unmute()
            else:
                voice.mute()
            self._update_voice_buttons()

    async def _toggle_deafen(self):
        voice = getattr(self.client, 'voice', None)
        if voice:
            if voice.is_deafened:
                voice.undeafen()
            else:
                voice.deafen()
            self._update_voice_buttons()

    async def _disconnect_voice(self):
        if hasattr(self.client, 'stop_voice'):
            self.client.stop_voice()
        self._update_voice_buttons()
        if self.on_voice_disconnect:
            self.on_voice_disconnect()

    def _update_voice_buttons(self):
        """Update mute/deafen button icons based on current state."""
        voice = getattr(self.client, 'voice', None)
        is_muted = voice.is_muted if voice else False
        is_deafened = voice.is_deafened if voice else False
        self._mute_btn.icon = ft.Icons.MIC_OFF if is_muted else ft.Icons.MIC_OUTLINED
        self._deafen_btn.icon = ft.Icons.HEADSET_OFF if is_deafened else ft.Icons.HEADSET_OUTLINED
        self._disconnect_btn.visible = voice is not None
        self.page.update()

    def _show_create_server_dialog(self):
        """Show dialog to create a new server."""
        name_field = ft.TextField(
            hint_text="Server name",
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=10,
            autofocus=True,
        )

        async def on_create(e):
            name = name_field.value.strip()
            if name:
                await self.client.send_server_create(name)
                dialog.open = False
                self.page.update()

        dialog = ft.AlertDialog(
            title=ft.Text("Create Server", color=FG),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Give your new server a name.", color=FG_DIM),
                    name_field,
                    ft.Text("Invite-only — you'll share invite codes to let others join.", color=FG_DIM, size=11),
                ], spacing=10),
                width=350,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close_dialog(dialog), tooltip="Discard"),
                ft.ElevatedButton("Create", on_click=on_create, bgcolor=ACCENT, color=FG, tooltip="Create server"),
            ],
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _show_join_server_dialog(self):
        """Show dialog to join a server via invite code."""
        id_field = ft.TextField(
            hint_text="Invite code",
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=10,
            autofocus=True,
        )

        async def on_join(e):
            code = id_field.value.strip()
            if code:
                await self.client.send_invite_join(code)
                dialog.open = False
                self.page.update()

        dialog = ft.AlertDialog(
            title=ft.Text("Join via Invite", color=FG),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Enter an invite code to join a server.", color=FG_DIM),
                    id_field,
                ], spacing=10),
                width=350,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close_dialog(dialog), tooltip="Discard"),
                ft.ElevatedButton("Join", on_click=on_join, bgcolor=ACCENT, color=FG, tooltip="Join server"),
            ],
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _close_dialog(self, dialog: ft.AlertDialog):
        dialog.open = False
        self.page.update()
