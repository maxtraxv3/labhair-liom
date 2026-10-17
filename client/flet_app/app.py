"""Main Flet application layout for Labhair-liom."""

from __future__ import annotations

import asyncio
import queue
import sys
import threading
import time
from typing import TYPE_CHECKING

import flet as ft

from client.flet_app.theme import *
from client.flet_app.connect_page import ConnectPage
from client.flet_app.server_bar import ServerBar
from client.flet_app.channel_panel import ChannelPanel
from client.flet_app.chat_view import ChatView
from client.flet_app.member_panel import MemberPanel
from client.flet_app.thread_panel import ThreadPanel
from client.flet_app.dm_view import DMView
from client.flet_app.viewer import ViewerWindow
from client.flet_app.dialogs import ServerSettingsDialog, StatusPicker, UserSettingsDialog, InviteDialog
from client.flet_app.audio_settings import AudioSettingsDialog

if TYPE_CHECKING:
    from client.main import ChatClient


class LabhairLiomApp:
    """Main Flet application wrapping the ChatClient backend."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client

        # Panels (created after connect)
        self.server_bar: ServerBar | None = None
        self.channel_panel: ChannelPanel | None = None
        self.chat_view: ChatView | None = None
        self.member_panel: MemberPanel | None = None
        self.thread_panel: ThreadPanel | None = None
        self.dm_view: DMView | None = None
        self.viewer: ViewerWindow | None = None
        self.server_settings: ServerSettingsDialog | None = None
        self.status_picker: StatusPicker | None = None

        self._current_view = "chat"  # "chat" or "dm"

        # Serialized video-frame pump: a bounded drop-oldest queue drained by a
        # single run_thread callback, so concurrent capture/network threads can
        # never flood the Flet page with parallel updates.
        self._frame_q: "queue.Queue" = queue.Queue(maxsize=2)
        self._pump_active = False

        self._setup_page()
        threading.Thread(target=self._diag_loop, daemon=True, name="viewer-diag").start()

    def _setup_page(self):
        """Configure the Flet page."""
        self.page.title = "Labhair-liom"
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.bgcolor = BG
        self.page.window.width = 1000
        self.page.window.height = 700
        self.page.window.min_width = 800
        self.page.window.min_height = 500
        self.page.padding = 0
        self.page.spacing = 0

        # Show connect dialog first
        self._show_connect()

    def _show_connect(self):
        """Show the connection/authentication dialog."""
        self.page.controls.clear()
        connect = ConnectPage(self.page, self.client, self._on_connected)
        self.page.add(connect.build())
        self.page.update()

    def _on_connected(self):
        """Called after successful authentication. Build the main UI."""
        try:
            self.page.controls.clear()

            # Create panels
            self.server_bar = ServerBar(self.page, self.client)
            self.channel_panel = ChannelPanel(self.page, self.client)
            self.chat_view = ChatView(self.page, self.client)
            self.member_panel = MemberPanel(self.page, self.client)
            self.thread_panel = ThreadPanel(self.page, self.client)
            self.dm_view = DMView(self.page, self.client)
            self.viewer = ViewerWindow(self.page, self.client)
            self.server_settings = ServerSettingsDialog(self.page, self.client)
            self.status_picker = StatusPicker(self.page, self.client)
            self.audio_settings = AudioSettingsDialog(self.page, self.client)

            # Wire up client callbacks
            self.client.on_servers_updated = self._on_servers_updated
            self.client.on_channels_updated = self._on_channels_updated
            self.client.on_members_updated = self._on_members_updated
            self.client.on_messages_updated = self._on_messages_updated
            self.client.on_message_received = self._on_message_received
            self.client.on_dm_updated = self._on_dm_updated
            self.client.on_dm_conversations = self._on_dm_conversations
            self.client.on_dm_message = self._on_dm_message
            self.client.on_dm_unread = self._on_dm_unread
            self.client.on_dm_ignore_result = self._on_dm_ignore_result
            self.client.on_friend_requests_updated = self._on_friend_requests_updated
            self.client.on_settings_updated = self._on_settings_updated
            self.client.on_local_video_frame = self._on_local_video_frame
            self.client.on_remote_video_frame = self._on_remote_video_frame
            self.client.on_search_results = self._on_search_results
            self.client.on_voice_members_update = self._on_voice_members_update
            self.client.on_speaking_update = self._on_speaking_update
            self.client.on_streaming_update = self._on_streaming_update
            self.chat_view.on_search_click = self._toggle_search_panel
            self.chat_view.on_invite_click = self._show_invite_dialog
            self.chat_view.on_members_click = self._toggle_member_panel

            # Wire up server bar callbacks
            self.server_bar.on_dm_click = self._show_dm_view
            self.member_panel.on_open_dm = self._open_dm_with_user
            self.server_bar.on_server_click = self._show_chat_view
            self.server_bar.on_settings_click = self._show_server_settings
            self.server_bar.on_viewer_click = self._toggle_viewer
            self.server_bar.on_user_settings_click = self._show_user_settings
            self.server_bar.on_threads_click = self._toggle_threads
            self.server_bar.on_status_click = self._show_status
            self.server_bar.on_audio_settings_click = self._show_audio_settings
            self.server_bar.on_voice_disconnect = self._on_voice_disconnect

            # Wire up channel panel callbacks
            self.channel_panel.on_settings_click = self._on_channel_settings_click
            self.channel_panel.on_voice_join = self._on_voice_join
            self.channel_panel.on_voice_leave = self._on_voice_leave

            # Main layout: server bar | channel panel | chat + members
            self._member_divider = ft.VerticalDivider(width=1, color=DIVIDER)
            self._member_panel_container = self.member_panel.build()
            self._chat_content = ft.Row(
                controls=[
                    self.channel_panel.build(),
                    ft.VerticalDivider(width=1, color=DIVIDER),
                    ft.Column(
                        controls=[
                            self.thread_panel.build(),
                            self.chat_view.build(),
                        ],
                        expand=True,
                        spacing=0,
                    ),
                    self._member_divider,
                    self._member_panel_container,
                ],
                expand=True,
                spacing=0,
            )

            self._dm_content = self.dm_view.build()

            # Content switcher
            self._content_area = ft.Container(
                content=self._chat_content,
                expand=True,
            )

            main_row = ft.Row(
                controls=[
                    self.server_bar.build(),
                    self._content_area,
                ],
                expand=True,
                spacing=0,
            )

            self.page.add(main_row)
            self.page.update()

            # Register file pickers for chat view
            self.chat_view._register_pickers()

            # Load initial data (auth already succeeded at this point)
            self.page.run_task(self._load_initial_data)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self.page.controls.clear()
            self.page.add(ft.Text(f"Error: {e}", color="#f23f43"))
            self.page.update()

    def _show_dm_view(self):
        """Switch to DM view."""
        self._current_view = "dm"
        self._content_area.content = self._dm_content
        # Refresh lists so the unread badge recomputes with fresh data
        self.page.run_task(self.client.send_dm_list)
        self.page.run_task(self.client.send_friend_requests)
        self.page.update()

    def _open_dm_with_user(self, user_id):
        """Switch to DM view and open conversation with user."""
        self.client.current_dm_user_id = int(user_id)
        self._show_dm_view()
        username = ""
        for m in self.client.members:
            if m.get("id") == int(user_id) or str(m.get("id")) == str(user_id):
                username = m.get("display_name", m.get("username", ""))
                break
        self.dm_view._open_dm(str(user_id), username)
        self.page.run_task(self.client.send_dm_list)

    def _show_chat_view(self, server_id: str = ""):
        """Switch to chat view."""
        self._current_view = "chat"
        self._content_area.content = self._chat_content
        if server_id:
            sid = int(server_id)
            self.client.current_server_id = sid
            self.client.current_channel_id = 0
            self.page.run_task(self.client.send_channel_list, sid)
            self.page.run_task(self.client.send_member_list, sid)
        self.page.update()

    def _show_server_settings(self, server: dict):
        """Open server settings dialog."""
        if self.server_settings:
            self.server_settings.show(server)

    def _on_channel_settings_click(self):
        """Open server settings from channel panel cog."""
        for srv in self.client.servers:
            if srv.get("id") == self.client.current_server_id:
                self._show_server_settings(srv)
                return

    def _on_voice_join(self):
        """Join voice channel — start voice engine."""
        if self.client.voice:
            return  # already in voice
        self.client.start_voice()
        self.server_bar._update_voice_buttons()

    def _on_voice_leave(self):
        """Leave voice channel — stop voice engine."""
        if self.client.voice:
            self.client.stop_voice()
            self.server_bar._update_voice_buttons()

    def _on_voice_disconnect(self):
        """Disconnect button pressed — clear channel panel tracking."""
        self.channel_panel.leave_voice()

    def _toggle_viewer(self):
        """Toggle the video viewer."""
        if self.viewer:
            self.viewer.show()

    def _on_local_video_frame(self, jpg: bytes, source: str, res: str):
        """Local capture (screen/camera) frame -> viewer window."""
        # Count capture-side push rate (feed fps) — distinguishes a slow source
        # from a slow display path in the viewer HUD.
        now = time.monotonic()
        if getattr(self, "_feed_t0", 0.0) == 0.0:
            self._feed_t0 = now
        if now - self._feed_t0 >= 1.0:
            self._feed_fps = getattr(self, "_feed_cnt", 0)
            self._feed_cnt = 0
            self._feed_t0 = now
        self._feed_cnt = getattr(self, "_feed_cnt", 0) + 1
        if self.viewer:
            self.viewer.set_feed_fps(getattr(self, "_feed_fps", 0))
        me = getattr(self.client, "display", "") or "Me"
        label = f"{me} ({source})" if source else me
        self._viewer_feed(jpg, source, res, label)

    def _on_remote_video_frame(self, jpg: bytes, source: str, sender: str):
        """Remote peer video frame -> viewer window (dropdown shows the peer's name)."""
        who = sender or "peer"
        pd = getattr(self.client, "peer_display", None)
        if pd is not None and sender and sender in pd:
            who = pd[sender]
        label = f"{who} ({source})" if source else who
        self._viewer_feed(jpg, source, "", label)

    def _viewer_feed(
        self,
        jpg: bytes,
        source: str,
        resolution: str = "",
        label: str | None = None,
    ):
        """Queue a frame for the in-app panel and schedule the serialized pump.

        The queue holds at most 2 items (drop-oldest): the panel always shows
        the freshest frame, and stale frames are discarded instead of backing
        up the Flet page thread.
        """
        if not jpg or not self.viewer or not self.viewer.is_open():
            return  # nothing marshalled while the panel is closed
        q = self._frame_q
        if q.full():
            try:
                q.get_nowait()
            except queue.Empty:
                pass
        q.put_nowait((jpg, source, resolution, label))
        if self._pump_active:
            return  # a pump callback is already draining the queue
        self._pump_active = True
        try:
            self.page.run_thread(self._pump_frames)
        except Exception:
            self._pump_active = False
            self._drain_frames()

    def _pump_frames(self):
        try:
            self._drain_frames()
        finally:
            self._pump_active = False
            if not self._frame_q.empty():
                self._pump_active = True
                try:
                    self.page.run_thread(self._pump_frames)
                except Exception:
                    self._pump_active = False

    def _drain_frames(self):
        while True:
            try:
                jpg, source, resolution, label = self._frame_q.get_nowait()
            except queue.Empty:
                return
            self._viewer_push(jpg, source, resolution, label)

    def _viewer_push(
        self, jpg: bytes, source: str, resolution: str, label: str | None = None
    ):
        try:
            self.viewer.push_jpeg(jpg, source, resolution, label)
        except Exception:
            pass

    def _diag_loop(self):
        """2-second diagnostics to stderr while video is active (debug aid)."""
        while True:
            time.sleep(2.0)
            v = self.viewer
            open_ = bool(v and v.is_open())
            disp = getattr(v, "_display_fps", -1) if v else -1
            feed = getattr(self, "_feed_fps", 0)
            ql = self._frame_q.qsize()
            bk = 0.0
            eng = getattr(self.client, "video", None)
            if eng is not None:
                bk = getattr(eng, "_last_blob_kb", 0.0)
            if open_ or feed > 0 or ql > 0:
                print(
                    f"[viewer-diag] panel_open={open_} display={disp} feed={feed} "
                    f"q={ql} blob_kb={bk:.0f}",
                    flush=True,
                )

    def _toggle_threads(self):
        """Toggle the thread sidebar."""
        if self.thread_panel:
            self.thread_panel._toggle()

    def _show_status(self):
        """Show the status picker."""
        if self.status_picker:
            self.status_picker.show()

    def _show_audio_settings(self):
        """Show audio settings dialog."""
        if self.audio_settings:
            self.audio_settings.show()

    def _show_user_settings(self):
        """Show user settings dialog."""
        dlg = UserSettingsDialog(self.page, self.client)
        dlg.show()

    async def _load_initial_data(self):
        """Load servers, channels, etc. after connection."""
        try:
            await self.client.send_server_list()
            await self.client.send_profile_get(self.client.db_user_id)
            await self.client.send_dm_list()
            await self.client.send_friend_requests()
            await self.client.send_settings_get()
        except (AssertionError, Exception):
            pass  # Not connected yet — will be loaded by on_auth_success

    def _on_auth_success(self, body: dict):
        """Called when authentication succeeds — load initial data."""
        self.page.run_task(self._load_initial_data)

    def _on_servers_updated(self):
        """Client received updated server list — refresh server bar."""
        if not self.server_bar:
            return
        self.server_bar._server_buttons.clear()
        for i, srv in enumerate(self.client.servers):
            sid = str(srv.get("id", ""))
            name = srv.get("name", f"Server {sid}")
            icon_url = srv.get("icon_url", "") or ""
            btn = self.server_bar._make_server_button(sid, name, name[0].upper(), i, icon_url)
            self.server_bar._server_buttons.append(btn)
        self.server_bar._rebuild()

    def _on_channels_updated(self):
        """Client received updated channel list — refresh channel panel."""
        if not self.channel_panel:
            return
        # Find current server name
        server_name = ""
        for srv in self.client.servers:
            if srv.get("id") == self.client.current_server_id:
                server_name = srv.get("name", "")
                break
        if server_name:
            self.channel_panel.set_server(str(self.client.current_server_id), server_name)
        self.channel_panel.set_channels(self.client.channels)

    def _on_members_updated(self):
        """Client received updated member list — refresh member panel."""
        if not self.member_panel:
            return
        self.member_panel.set_members(
            self.client.members, streaming=self.client.screen_active_peers
        )

    def _on_streaming_update(self):
        """A peer started/stopped screen sharing — refresh red dots + channel header."""
        pu = self.client.peer_display
        active = {
            uid for uid, on in self.client.screen_active_peers.items() if on
        }
        names = [pu.get(uid, uid) for uid in sorted(active)]
        if self.member_panel:
            self.member_panel.set_members(
                self.client.members, streaming=active
            )
        if self.chat_view:
            self.chat_view.set_streamers(names)
        # Keep the toolbar + viewer capture buttons in sync with reality
        if self.server_bar:
            self.server_bar.set_screen_btn(
                bool(self.client.video and self.client.video.screen_active)
            )
        if self.viewer:
            self.viewer._refresh_scr_btn()
        self.page.update()

    def _on_messages_updated(self, messages: list[dict]):
        """Client received updated message list — refresh chat view."""
        if not self.chat_view:
            return
        self.chat_view.clear_messages()
        for msg in messages:
            self.chat_view.add_message(msg)

    def _on_message_received(self, msg: dict):
        """Client received a real-time message — append to chat view."""
        if not self.chat_view:
            return
        self.chat_view.add_message(msg)

    def _on_dm_updated(self, messages: list[dict]):
        """Client loaded DM history — render it in the open conversation."""
        if not self.dm_view:
            return
        self.dm_view.set_messages(messages)

    def _on_dm_conversations(self, conversations: list[dict]):
        """Client loaded the DM conversation list — refresh the sidebar."""
        if not self.dm_view:
            return
        self.dm_view.set_conversations(conversations)

    def _on_dm_message(self, dm: dict):
        """Client received a pushed DM — show it and refresh the list."""
        if not self.dm_view:
            return
        self.dm_view.add_incoming_dm(dm)

    def _on_dm_unread(self, total: int):
        """Combined unread count (DMs + friend requests) — drive the orange dot."""
        if self.server_bar:
            self.server_bar.set_dm_badge(total > 0)

    def _on_dm_ignore_result(self, user_id: int, ok: bool):
        """DM ignore confirmed server-side — refresh conversations."""
        if not ok:
            return
        self.page.run_task(self.client.send_dm_list)

    def _on_friend_requests_updated(self, requests: list[dict]):
        """Pending friend requests changed — refresh sidebar + badge."""
        if self.dm_view:
            self.dm_view.set_friend_requests(requests)

    def _on_settings_updated(self, settings: dict):
        """User settings refreshed (auto-ignore DM etc.)."""
        pass

    def _on_search_results(self, messages: list[dict]):
        """Client received search results — display in chat search panel."""
        if not self.chat_view:
            return
        self.chat_view._search_results_list.controls.clear()
        if messages:
            for msg in messages:
                username = msg.get("username", "Unknown")
                content = msg.get("content", "")
                ch_name = msg.get("channel_name", "")
                label = f"[{ch_name}] {username}: {content[:80]}"
                self.chat_view._search_results_list.controls.append(
                    ft.Container(
                        content=ft.Text(label, color=FG, size=12, no_wrap=True, overflow=ft.TextOverflow.ELLIPSIS),
                        padding=ft.padding.symmetric(horizontal=8, vertical=4),
                        border_radius=4,
                        on_hover=lambda e: setattr(e.control, 'bgcolor', BG_HOVER if e.data == "true" else None) or e.control.update(),
                    )
                )
        else:
            self.chat_view._search_results_list.controls.append(
                ft.Text("No results found.", color=FG_DIM, size=12)
            )
        self.page.update()

    def _on_voice_members_update(self, channel_id: int, members: list[dict]):
        """Handle voice channel member list update."""
        if self.channel_panel:
            self.channel_panel.update_voice_members(channel_id, members)

    def _on_speaking_update(self, user_id: str, speaking: bool):
        """Handle speaking indicator update from voice engine."""
        if self.channel_panel:
            self.channel_panel.update_speaking(user_id, speaking)

    def _toggle_search_panel(self):
        """Toggle the search panel in chat view."""
        if self.chat_view:
            self.chat_view._toggle_search_panel()

    def _toggle_member_panel(self):
        """Toggle the member list panel visibility."""
        self._member_panel_container.visible = not self._member_panel_container.visible
        self._member_divider.visible = self._member_panel_container.visible
        self.page.update()

    def _show_invite_dialog(self):
        """Show invite dialog for current server."""
        if not self.client.current_server_id:
            return
        dlg = InviteDialog(self.page, self.client)
        dlg.show(self.client.current_server_id)


def main(page: ft.Page):
    """Flet entry point. Imports and creates the ChatClient."""
    from client.main import ChatClient

    client = ChatClient()
    app = LabhairLiomApp(page, client)


if __name__ == "__main__":
    ft.app(target=main)
