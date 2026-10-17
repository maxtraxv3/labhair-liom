"""Channel sidebar panel for Labhair-liom Flet GUI."""

from __future__ import annotations

import flet as ft
from typing import TYPE_CHECKING

from client.flet_app.theme import *

if TYPE_CHECKING:
    from client.main import ChatClient


class ChannelPanel:
    """Left sidebar showing channels, threads, and search."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client
        self._channels: list[dict] = []
        self._current_server_name = ""
        self._selected_channel_id: str | None = None
        self._current_voice_channel_id: str | None = None  # track joined voice channel
        self._voice_members: dict[str, list[dict]] = {}  # channel_id → [{user_id, display}]
        self._voice_member_containers: dict[str, ft.Column] = {}  # channel_id → ft.Column
        self._speaking_users: dict[str, bool] = {}  # user_id → currently speaking
        self.on_settings_click = None  # set by app
        self.on_voice_join = None  # set by app
        self.on_voice_leave = None  # set by app

    def build(self) -> ft.Container:
        """Build the channel panel."""
        self._server_name_text = ft.Text(
            "No Server",
            color=FG,
            size=14,
            weight=ft.FontWeight.BOLD,
            expand=True,
        )

        self._cog_button = ft.IconButton(
            icon=ft.Icons.SETTINGS_OUTLINED,
            icon_color=FG_DIM,
            icon_size=16,
            tooltip="Channel settings",
            on_click=self._on_settings_click,
            visible=False,
        )

        self._channels_list = ft.ListView(
            spacing=2,
            expand=True,
            auto_scroll=False,
        )

        self._thread_section = ft.Column(
            controls=[
                ft.Container(
                    content=ft.Text("THREADS", color=FG_DIM, size=12, weight=ft.FontWeight.BOLD),
                    padding=ft.padding.only(left=8, top=8, bottom=4),
                ),
                ft.ListView(spacing=2, expand=True),
            ],
            visible=False,
            expand=True,
        )

        header = ft.Container(
            content=ft.Row([
                self._server_name_text,
                self._cog_button,
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            padding=ft.padding.symmetric(horizontal=12, vertical=10),
        )

        channels_header = ft.Container(
            content=ft.Text("CHANNELS", color=FG_DIM, size=12, weight=ft.FontWeight.BOLD),
            padding=ft.padding.only(left=12, top=8, bottom=4),
        )

        content = ft.Column(
            controls=[
                header,
                ft.Divider(height=1, color=DIVIDER),
                channels_header,
                self._channels_list,
                self._thread_section,
            ],
            spacing=0,
            expand=True,
        )

        return ft.Container(
            content=content,
            width=200,
            bgcolor=BG_DARK,
            padding=ft.padding.only(top=0),
        )

    def set_server(self, server_id: str, name: str):
        """Update the displayed server name."""
        self._current_server_name = name
        self._server_name_text.value = name
        self._cog_button.visible = True
        self.page.update()

    def set_channels(self, channels: list[dict]):
        """Populate the channel list."""
        self._channels = channels
        self._channels_list.controls.clear()
        self._voice_member_containers.clear()

        for ch in channels:
            ch_type = ch.get("channel_type", ch.get("type", "text"))
            is_voice = ch_type == "voice"
            icon = ft.Icons.MIC_OUTLINED if is_voice else ft.Icons.TAG
            icon_color = CHANNEL_VOICE if is_voice else CHANNEL_TEXT
            name = ch.get("name", f"Channel {ch.get('id', '?')}")
            ch_id = str(ch.get("id", ""))

            channel_controls = [
                ft.Container(
                    content=ft.Row([
                        ft.Icon(name=icon, color=icon_color, size=16),
                        ft.Text(name, color=FG_DIM, size=14, expand=True),
                    ], spacing=6),
                    padding=ft.padding.symmetric(horizontal=8, vertical=6),
                    border_radius=6,
                    on_click=lambda e, cid=ch_id, vt=is_voice: self._on_channel_click(cid, vt),
                    on_hover=self._on_item_hover,
                    data=ch_id,
                ),
            ]

            if is_voice:
                voice_col = ft.Column(spacing=0, controls=[])
                self._voice_member_containers[ch_id] = voice_col
                channel_controls.append(voice_col)
                # Restore any cached members
                if ch_id in self._voice_members:
                    self._render_voice_members(ch_id)

            self._channels_list.controls.append(
                ft.Column(controls=channel_controls, spacing=0)
            )

        self.page.update()

    def update_voice_members(self, channel_id: str | int, members: list[dict]):
        """Update the voice member display for a channel."""
        channel_id = str(channel_id)
        self._voice_members[channel_id] = members
        self._render_voice_members(channel_id)
        self.page.update()

    def update_speaking(self, user_id: str, speaking: bool):
        """Update speaking indicator for a voice channel member."""
        self._speaking_users[user_id] = speaking
        # Re-render all voice channels that might contain this user
        for ch_id, members in self._voice_members.items():
            for m in members:
                if str(m.get("user_id", "")) == str(user_id) or m.get("display", "") == user_id:
                    self._render_voice_members(ch_id)
                    self.page.update()
                    return

    def _render_voice_members(self, channel_id: str):
        """Render connected users under a voice channel."""
        container = self._voice_member_containers.get(channel_id)
        if not container:
            return
        container.controls.clear()
        members = self._voice_members.get(channel_id, [])
        for m in members:
            display = m.get("display", "Unknown")
            uid = str(m.get("user_id", ""))
            is_speaking = self._speaking_users.get(uid, False) or self._speaking_users.get(display, False)
            # Mic icon: green glow when speaking, dim when quiet
            mic_color = STATUS_ONLINE if is_speaking else CHANNEL_VOICE
            mic_icon = ft.Icon(ft.Icons.MIC, color=mic_color, size=12)
            # Add a subtle ring effect when speaking
            if is_speaking:
                mic_icon = ft.Container(
                    content=ft.Icon(ft.Icons.MIC, color=STATUS_ONLINE, size=12),
                    border=ft.border.all(1, STATUS_ONLINE),
                    border_radius=6,
                    padding=1,
                )
            container.controls.append(
                ft.Container(
                    content=ft.Row([
                        mic_icon,
                        ft.Text(display, color=FG_DIM if not is_speaking else FG, size=12,
                                weight=ft.FontWeight.NORMAL if not is_speaking else ft.FontWeight.BOLD),
                    ], spacing=4),
                    padding=ft.padding.only(left=28, right=8, top=2, bottom=2),
                )
            )

    def _on_channel_click(self, channel_id: str, is_voice: bool = False):
        """Join a channel. For voice channels, handle switching with confirmation."""
        self._selected_channel_id = channel_id
        self._highlight_selected()

        if is_voice:
            # Already in a voice channel?
            if self._current_voice_channel_id and self._current_voice_channel_id != channel_id:
                # Find the name of the new channel
                new_name = channel_id
                for ch in self._channels:
                    if str(ch.get("id")) == channel_id:
                        new_name = ch.get("name", channel_id)
                        break
                self._show_voice_switch_confirm(channel_id, new_name)
                return
            # Joining the same voice channel — no-op
            if self._current_voice_channel_id == channel_id:
                return
            # First voice join
            self._current_voice_channel_id = channel_id
            self.page.run_task(self.client.send_channel_join, int(channel_id))
            if self.on_voice_join:
                self.on_voice_join()
        else:
            # Text channel — also send join to switch
            self.page.run_task(self.client.send_channel_join, int(channel_id))

    def _show_voice_switch_confirm(self, new_channel_id: str, new_channel_name: str):
        """Show confirmation dialog when switching voice channels."""
        dialog = ft.AlertDialog(
            title=ft.Text("Switch Voice Channel?", color=FG),
            content=ft.Text(
                f"You're already in a voice channel. Leave and join #{new_channel_name}?",
                color=FG,
            ),
            bgcolor=BG_DARK,
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close_voice_dialog(dialog), tooltip="Keep current channel"),
                ft.ElevatedButton(
                    "Switch", bgcolor=ACCENT, color=BG_DARK,
                    tooltip="Switch voice channel",
                    on_click=lambda e: self.page.run_task(
                        self._confirm_voice_switch, dialog, new_channel_id,
                    ),
                ),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    async def _confirm_voice_switch(self, dialog: ft.AlertDialog, new_channel_id: str):
        """Leave current voice channel and join new one."""
        old_id = self._current_voice_channel_id
        dialog.open = False
        self.page.update()
        try:
            self.page.overlay.remove(dialog)
        except ValueError:
            pass
        # Clear old channel's voice member display
        if old_id:
            self.update_voice_members(old_id, [])
        # Leave old voice channel
        if self.on_voice_leave:
            self.on_voice_leave()
        # Join new voice channel
        self._current_voice_channel_id = new_channel_id
        self.page.run_task(self.client.send_channel_join, int(new_channel_id))
        if self.on_voice_join:
            self.on_voice_join()

    def _close_voice_dialog(self, dialog: ft.AlertDialog):
        dialog.open = False
        self.page.update()
        try:
            self.page.overlay.remove(dialog)
        except ValueError:
            pass

    def leave_voice(self):
        """Called when voice is disconnected (e.g. disconnect button)."""
        old_id = self._current_voice_channel_id
        self._current_voice_channel_id = None
        # Clear the old channel's voice member display
        if old_id:
            self.update_voice_members(old_id, [])

    def _highlight_selected(self):
        """Highlight the selected channel."""
        for wrapper in self._channels_list.controls:
            # wrapper is either a Container (text) or Column (text + voice members)
            if isinstance(wrapper, ft.Column):
                item = wrapper.controls[0] if wrapper.controls else None
            else:
                item = wrapper
            if isinstance(item, ft.Container) and item.data == self._selected_channel_id:
                item.bgcolor = BG_SELECTED
                if isinstance(item.content, ft.Row) and len(item.content.controls) > 1:
                    item.content.controls[1].color = FG
            elif isinstance(item, ft.Container):
                item.bgcolor = None
                if isinstance(item.content, ft.Row) and len(item.content.controls) > 1:
                    item.content.controls[1].color = FG_DIM
        self.page.update()

    def _on_item_hover(self, e):
        """Hover effect on channel items."""
        ctrl = e.control
        # If hovering on a Column wrapper, target the inner Container
        if isinstance(ctrl, ft.Column) and ctrl.controls:
            ctrl = ctrl.controls[0]
        if isinstance(ctrl, ft.Container) and ctrl.data != self._selected_channel_id:
            ctrl.bgcolor = BG_HOVER if e.data == "true" else None
            ctrl.update()

    def _on_settings_click(self, e):
        """Open server settings."""
        if self.on_settings_click:
            self.on_settings_click()
        pass
