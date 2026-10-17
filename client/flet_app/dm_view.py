"""Direct Messages view for Labhair-liom Flet GUI."""

from __future__ import annotations

import time
import flet as ft
from typing import TYPE_CHECKING

from client.flet_app.theme import *

if TYPE_CHECKING:
    from client.main import ChatClient


class DMView:
    """DM conversation list and chat view."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client
        self._conversations: list[dict] = []
        self._friends: list[dict] = []
        self._pending_requests: list[dict] = []
        self._current_dm_id: str | None = None
        self._current_dm_username: str = ""
        self._banner_user_id: int | None = None
        # user_id -> whether they are on our friends list
        self._friend_map: dict[int, bool] = {}
        # senders we explicitly accepted a DM request from (allow DMs)
        self._accepted_dms: set[int] = set()
        # senders we ignored (server blocks their DMs)
        self._ignored_dms: set[int] = set()
        # senders we already warned about this session (avoid dialog spam)
        self._warned_senders: set[int] = set()

    def build(self) -> ft.Row:
        """Build the DM view with conversation list + chat."""
        # Friends / DM list sidebar
        self._dm_sidebar = ft.ListView(spacing=2, expand=True)

        self._friends_section = ft.Column([
            self._dm_sidebar,
        ], spacing=0, expand=True)

        # DM chat area
        self._warning_banner_text = ft.Text("", color="#faa61a", size=12, expand=True)
        self._warning_banner = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.WARNING_AMBER_OUTLINED, color="#faa61a", size=16),
                self._warning_banner_text,
                ft.TextButton("Accept", on_click=self._on_accept_stranger,
                              style=ft.ButtonStyle(color=ACCENT)),
                ft.TextButton("Ignore", on_click=self._on_ignore_stranger,
                              style=ft.ButtonStyle(color=FG_DIM)),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor="#3a3410",
            padding=ft.padding.symmetric(horizontal=10, vertical=4),
            visible=False,
        )

        self._dm_messages = ft.ListView(spacing=4, expand=True, auto_scroll=True, padding=12)

        self._dm_input = ft.TextField(
            hint_text="Message @user",
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=12,
            text_size=14,
            expand=True,
            on_submit=self._on_send_dm,
        )

        dm_chat = ft.Column([
            self._warning_banner,
            self._dm_messages,
            ft.Container(
                content=ft.Row([
                    self._dm_input,
                    ft.IconButton(icon=ft.Icons.SEND, icon_color=ACCENT, on_click=self._on_send_dm, tooltip="Send message"),
                ], spacing=4),
                padding=ft.padding.symmetric(horizontal=12, vertical=8),
            ),
        ], spacing=0, expand=True)

        return ft.Row([
            ft.Container(
                content=self._friends_section,
                width=240,
                bgcolor=BG_DARK,
            ),
            ft.VerticalDivider(width=1, color=DIVIDER),
            dm_chat,
        ], expand=True, spacing=0)

    def set_conversations(self, convos: list[dict]):
        """Update DM conversation list."""
        self._conversations = convos
        for convo in convos:
            try:
                other_uid = int(convo.get("id") or convo.get("other_user_id"))
            except (TypeError, ValueError):
                continue
            self._friend_map[other_uid] = bool(convo.get("is_friend", True))
        self._rebuild_sidebar()

    def set_friend_requests(self, requests: list[dict]):
        """Update the pending friend-request section of the DM sidebar."""
        self._pending_requests = requests
        self._rebuild_sidebar()

    def _rebuild_sidebar(self):
        """Re-render the DM sidebar: friend requests + conversations."""
        if getattr(self, "_dm_sidebar", None) is None:
            return
        self._dm_sidebar.controls.clear()

        if self._pending_requests:
            self._dm_sidebar.controls.append(self._section_header("FRIEND REQUESTS"))
            for req in self._pending_requests:
                self._dm_sidebar.controls.append(self._request_row(req))

        self._dm_sidebar.controls.append(self._section_header("MESSAGES"))
        for convo in self._conversations:
            username = convo.get("username") or convo.get("other_username") or convo.get("display_name", "Unknown")
            last_msg = convo.get("last_message", "")
            dm_id = convo.get("id") or convo.get("user_id") or convo.get("other_user_id", "")
            unread = convo.get("unread_count", 0)

            item = ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Text(username[0].upper(), color=FG, size=12,
                                        weight=ft.FontWeight.BOLD),
                        width=32, height=32, border_radius=16,
                        bgcolor=BG_INPUT, alignment=ft.alignment.center,
                    ),
                    ft.Column([
                        ft.Text(username, color=FG, size=13, weight=ft.FontWeight.BOLD,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(last_msg[:30] if last_msg else "No messages",
                                color=FG_DIM, size=11, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=2, expand=True),
                    ft.Container(
                        content=ft.Text(str(unread), color=FG, size=10, weight=ft.FontWeight.BOLD),
                        width=18, height=18, border_radius=9,
                        bgcolor=ACCENT, alignment=ft.alignment.center,
                        visible=unread > 0,
                    ),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.padding.symmetric(horizontal=8, vertical=6),
                border_radius=6,
                on_click=lambda e, did=dm_id: self._open_dm(did, username),
                on_hover=self._on_hover,
                data=dm_id,
            )
            self._dm_sidebar.controls.append(item)

        self._refresh_banner()
        try:
            self.page.update()
        except Exception:
            pass

    def _section_header(self, text: str) -> ft.Container:
        return ft.Container(
            content=ft.Text(text, color=FG_DIM, size=11, weight=ft.FontWeight.BOLD),
            padding=ft.padding.only(left=12, top=10, bottom=4),
        )

    def _request_row(self, req: dict) -> ft.Container:
        """A pending friend request row with Accept / Ignore actions."""
        rid = req.get("id") or req.get("user_id")
        name = req.get("username") or req.get("display_name", "Unknown")
        try:
            rid = int(rid)
        except (TypeError, ValueError):
            return ft.Container()
        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Text(name[0].upper(), color=FG, size=12,
                                    weight=ft.FontWeight.BOLD),
                    width=32, height=32, border_radius=16,
                    bgcolor="#3a3410", alignment=ft.alignment.center,
                ),
                ft.Column([
                    ft.Text(name, color="#faa61a", size=13, weight=ft.FontWeight.BOLD,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text("wants to be friends", color=FG_DIM, size=11),
                ], spacing=2, expand=True),
                ft.IconButton(
                    icon=ft.Icons.CHECK, icon_color="#43b581", icon_size=18,
                    tooltip="Accept", on_click=lambda e, u=rid: self._accept_request(u),
                ),
                ft.IconButton(
                    icon=ft.Icons.CLOSE, icon_color="#f23f43", icon_size=18,
                    tooltip="Ignore", on_click=lambda e, u=rid: self._decline_request(u),
                ),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=BG_DARK,
            padding=ft.padding.symmetric(horizontal=8, vertical=6),
            border_radius=6,
        )

    def _accept_request(self, uid: int):
        self.page.run_task(self.client.send_friend_accept, uid)
        self.page.run_task(self.client.send_dm_list)

    def _decline_request(self, uid: int):
        self.page.run_task(self.client.send_friend_decline, uid)

    def _normalize_msg(self, msg: dict) -> dict:
        """Map server field names (sender_username/created_at) onto GUI names."""
        out = dict(msg)
        if not out.get("username"):
            out["username"] = out.get("sender_username") or out.get("other_username") or "Unknown"
        if not out.get("user_id"):
            out["user_id"] = out.get("sender_id") if out.get("sender_id") is not None else out.get("recipient_id")
        if not out.get("timestamp"):
            out["timestamp"] = out.get("created_at") or ""
        return out

    def set_messages(self, messages: list[dict]):
        """Load a DM history response into the open conversation."""
        self._dm_messages.controls.clear()
        for msg in messages:
            self.add_dm_message(self._normalize_msg(msg))
        self.page.update()

    def add_dm_message(self, msg: dict):
        """Add a message to the DM chat."""
        msg = self._normalize_msg(msg)
        username = msg.get("username", "Unknown")
        content = msg.get("content", "")
        timestamp = msg.get("timestamp", "")

        if isinstance(timestamp, (int, float)):
            ts = time.strftime("%H:%M", time.localtime(timestamp))
        else:
            ts = str(timestamp)
            # SQLite "YYYY-MM-DD HH:MM:SS" → HH:MM
            if " " in ts and len(ts) >= 16:
                ts = ts[11:16]
            else:
                ts = ts[:5] if ts else ""

        user_id = msg.get("user_id", username)
        colors = [ACCENT, "#e91e63", "#9c27b0", "#ff9800", "#4caf50", "#00bcd4"]
        username_color = colors[hash(user_id) % len(colors)]

        widget = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text(username, color=username_color, size=14, weight=ft.FontWeight.BOLD),
                    ft.Text(ts, color=FG_MUTED, size=11),
                ], spacing=8),
                ft.Text(content, color=FG, size=14, selectable=True),
            ], spacing=2),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=8,
        )
        self._dm_messages.controls.append(widget)
        self.page.update()

    def _open_dm(self, dm_id: str, username: str):
        """Open a DM conversation."""
        self._current_dm_id = int(dm_id)
        self._current_dm_username = username
        self.client.current_dm_user_id = int(dm_id)
        self._dm_messages.controls.clear()
        self.page.run_task(self.client.send_dm_read, int(dm_id))
        self.page.run_task(self.client.send_dm_history, int(dm_id))
        self.page.run_task(self.client.send_dm_list)
        self._refresh_banner()

    def add_incoming_dm(self, dm: dict):
        """A DM send/push event. If it belongs to the open conversation, render
        it; always refresh the conversation list to update previews."""
        dm = self._normalize_msg(dm)
        try:
            open_id = int(self._current_dm_id)
        except (TypeError, ValueError):
            open_id = None
        mine = getattr(self.client, "db_user_id", None)
        render = False
        if open_id is not None:
            theirs = open_id
            sid = dm.get("sender_id")
            rid = dm.get("recipient_id")
            if sid in (mine, theirs) and rid in (mine, theirs):
                render = True
        if render:
            self.add_dm_message(dm)

        # Stranger-DM spam guard: warn when a non-friend messages us
        is_friend = dm.get("is_friend", True)
        try:
            sid = int(dm.get("sender_id"))
        except (TypeError, ValueError):
            sid = None
        if (
            not is_friend
            and sid is not None
            and str(sid) != str(mine)
        ):
            self._friend_map[sid] = False
            if open_id is not None and str(open_id) == str(sid):
                self._refresh_banner()
            elif sid not in self._warned_senders:
                self._warned_senders.add(sid)
                self._show_stranger_dialog(dm)

        self.page.run_task(self.client.send_dm_list)

    # --- Stranger-DM guard (accept / ignore) --------------------------------

    def _refresh_banner(self):
        """Show/hide the 'not on your friends list' warning strip for the
        open conversation."""
        if getattr(self, "_warning_banner", None) is None:
            return
        open_id = self._current_dm_id
        if open_id is None:
            self._warning_banner.visible = False
        else:
            uid = int(open_id)
            is_friend = self._friend_map.get(uid, True)
            if is_friend or uid in self._accepted_dms:
                self._warning_banner.visible = False
            else:
                name = self._current_dm_username or "This user"
                self._warning_banner_text.value = (
                    f"{name} is not on your friends list — accept their DM request "
                    "or ignore them to stop future messages."
                )
                self._banner_user_id = uid
                self._warning_banner.visible = True
        try:
            self.page.update()
        except Exception:
            pass

    def _show_stranger_dialog(self, dm: dict):
        """Prompt the user to accept or ignore a stranger's DM."""
        try:
            sender = int(dm.get("sender_id"))
        except (TypeError, ValueError):
            return
        name = dm.get("username") or "This user"
        dlg = ft.AlertDialog(
            title=ft.Text(f"{name} wants to DM you", color=FG),
            content=ft.Text(
                "They are not on your friends list. Accept to allow their "
                "messages, or Ignore to block them.",
                color=FG_DIM, size=13,
            ),
            actions=[
                ft.TextButton("Ignore", on_click=lambda e: self._dlg_ignore(dlg, sender)),
                ft.ElevatedButton(
                    "Accept",
                    bgcolor=ACCENT, color=FG,
                    on_click=lambda e: self._dlg_accept(dlg, sender),
                ),
            ],
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(dlg)
        dlg.open = True
        self.page.update()

    def _dlg_accept(self, dlg, sender: int):
        dlg.open = False
        try:
            self.page.update()
        except Exception:
            pass
        self._accept_stranger(sender)

    def _dlg_ignore(self, dlg, sender: int):
        dlg.open = False
        try:
            self.page.update()
        except Exception:
            pass
        self._ignore_stranger(sender)

    def _accept_stranger(self, uid: int):
        """Accept a stranger's DM → allow messages + send them a friend request."""
        self._warned_senders.add(uid)
        self._accepted_dms.add(uid)
        self.page.run_task(self.client.send_friend_add, uid)
        self.page.run_task(self.client.send_dm_list)
        self._refresh_banner()

    def _ignore_stranger(self, uid: int):
        """Ignore a stranger's DM → server blocks their DMs to us."""
        self._warned_senders.add(uid)
        self._ignored_dms.add(uid)
        self._accepted_dms.discard(uid)
        self.page.run_task(self.client.send_dm_ignore, uid)
        self.page.run_task(self.client.send_dm_list)
        self._refresh_banner()

    def _on_accept_stranger(self, e):
        if self._banner_user_id:
            self._accept_stranger(self._banner_user_id)

    def _on_ignore_stranger(self, e):
        if self._banner_user_id:
            self._ignore_stranger(self._banner_user_id)

    def _on_send_dm(self, e):
        """Send a DM."""
        text = self._dm_input.value.strip()
        if not text or not self._current_dm_id:
            return
        self.page.run_task(self.client.send_dm_send, self._current_dm_id, text)
        self._dm_input.value = ""
        self._dm_input.update()

    def _on_hover(self, e):
        e.control.bgcolor = BG_HOVER if e.data == "true" else None
        e.control.update()
