"""Chat view — messages, input, reactions for Labhair-liom Flet GUI."""

from __future__ import annotations

import asyncio
import base64 as _b64
import time
from typing import TYPE_CHECKING

import flet as ft

from client.flet_app.theme import *
from client.flet_app.dialogs import EmojiPicker, MessageContextMenu

if TYPE_CHECKING:
    from client.main import ChatClient


class ChatView:
    """Main chat area with message display and input."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client
        self._messages: list[dict] = []
        self._typing_users: list[str] = []
        self._typing_timer = 0
        self._emoji_picker = EmojiPicker(page, self._on_emoji_select)
        self._context_menu = MessageContextMenu(page, client)
        self._save_picker = ft.FilePicker(on_result=self._on_save_result)
        self._pending_save_data: dict = {}  # name → (bytes, mime)
        self.on_search_click = None  # set by app
        self.on_invite_click = None  # set by app
        self.on_members_click = None  # set by app

    def build(self) -> ft.Column:
        """Build the chat view."""
        # Channel header
        self._streamer_label = ft.Text(
            "", color="#f23f43", size=12, weight=ft.FontWeight.BOLD,
            visible=False, tooltip="Streaming their screen",
        )
        self._channel_header = ft.Container(
            content=ft.Row([
                ft.Icon(name=ft.Icons.TAG, color=FG_DIM, size=20),
                ft.Text("Select a channel", color=FG, size=16, weight=ft.FontWeight.BOLD, expand=True),
                self._streamer_label,
                ft.IconButton(icon=ft.Icons.SEARCH, icon_color=FG_DIM, icon_size=18,
                              tooltip="Search messages",
                              on_click=lambda e: self.on_search_click() if self.on_search_click else None),
                ft.IconButton(icon=ft.Icons.PEOPLE_ALT_OUTLINED, icon_color=FG_DIM, icon_size=18,
                              tooltip="Toggle member list",
                              on_click=lambda e: self.on_members_click() if self.on_members_click else None),
                ft.IconButton(icon=ft.Icons.PERSON_ADD, icon_color=FG_DIM, icon_size=18,
                              tooltip="Invite people",
                              on_click=lambda e: self.on_invite_click() if self.on_invite_click else None),
            ], spacing=8),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
            bgcolor=BG_DARK,
        )

        # Search panel (hidden by default, toggled via search button)
        self._search_field = ft.TextField(
            hint_text="Search messages...",
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=8,
            prefix_icon=ft.Icons.SEARCH,
            text_size=13,
            expand=True,
            on_submit=self._on_search_submit,
        )
        self._search_user_field = ft.TextField(
            hint_text="Filter by user",
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=8,
            text_size=13,
            width=150,
        )
        self._search_channel_dropdown = ft.Dropdown(
            hint_text="Channel",
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=8,
            text_size=13,
            width=130,
        )
        self._search_results_list = ft.ListView(spacing=2, expand=True)
        self._search_panel = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("SEARCH", color=FG_DIM, size=12, weight=ft.FontWeight.BOLD),
                    ft.IconButton(
                        icon=ft.Icons.CLOSE,
                        icon_color=FG_DIM,
                        icon_size=14,
                        tooltip="Close search",
                        on_click=self._toggle_search_panel,
                    ),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self._search_field,
                ft.Row([
                    self._search_user_field,
                    self._search_channel_dropdown,
                ], spacing=8),
                self._search_results_list,
            ], spacing=8),
            visible=False,
            padding=12,
            bgcolor=BG_DARKER,
            border_radius=8,
            margin=ft.margin.only(left=12, right=12, top=4),
        )

        # Messages list
        self._messages_list = ft.ListView(
            spacing=4,
            expand=True,
            auto_scroll=True,
            padding=12,
        )

        # Typing indicator
        self._typing_label = ft.Text(
            "",
            color=FG_DIM,
            size=12,
            italic=True,
        )

        # Input area
        self._input_field = ft.TextField(
            hint_text="Message #channel",
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=12,
            text_size=14,
            min_lines=1,
            max_lines=5,
            expand=True,
            on_submit=self._on_send,
            on_change=self._on_typing,
            shift_enter=True,
        )

        self._emoji_btn = ft.IconButton(
            icon=ft.Icons.SENTIMENT_SATISFIED,
            icon_color=FG_DIM,
            icon_size=20,
            tooltip="Open emoji picker",
            on_click=self._toggle_emoji,
        )

        self._send_btn = ft.IconButton(
            icon=ft.Icons.SEND,
            icon_color=ACCENT,
            icon_size=20,
            tooltip="Send message",
            on_click=self._on_send,
        )

        self._image_btn = ft.IconButton(
            icon=ft.Icons.IMAGE_OUTLINED,
            icon_color=FG_DIM,
            icon_size=20,
            on_click=self._on_send_image,
            tooltip="Send Image",
        )

        self._file_btn = ft.IconButton(
            icon=ft.Icons.ATTACH_FILE,
            icon_color=FG_DIM,
            icon_size=20,
            on_click=self._on_send_file,
            tooltip="Send File",
        )

        self._file_picker = ft.FilePicker(on_result=self._on_file_picked)
        self._image_picker = ft.FilePicker(on_result=self._on_image_picked)
        self._pending_file_action: str = ""

        input_bar = ft.Container(
            content=ft.Row([
                self._image_btn,
                self._file_btn,
                self._emoji_btn,
                self._input_field,
                self._send_btn,
            ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.END),
            padding=ft.padding.symmetric(horizontal=12, vertical=8),
        )

        return ft.Column(
            controls=[
                self._channel_header,
                self._search_panel,
                ft.Divider(height=1, color=DIVIDER),
                self._messages_list,
                self._typing_label,
                ft.Divider(height=1, color=DIVIDER),
                input_bar,
            ],
            spacing=0,
            expand=True,
        )

    def _register_pickers(self):
        """Register file pickers with the page (call after build)."""
        for picker in (self._file_picker, self._image_picker, self._save_picker):
            if picker not in self.page.overlay:
                self.page.overlay.append(picker)

    def set_channel(self, channel_name: str):
        """Update the channel header."""
        self._channel_header.content.controls[1].value = f"#{channel_name}"
        self.page.update()

    def set_streamers(self, names: list[str]):
        """Show red-dot streaming indicators next to the channel name."""
        label = getattr(self, "_streamer_label", None)
        if label is None:
            return
        if names:
            label.value = "● " + " · ".join(names)
            label.visible = True
        else:
            label.value = ""
            label.visible = False
        self.page.update()

    def add_message(self, msg: dict):
        """Add a message to the chat."""
        self._messages.append(msg)
        mentioned = msg.get("mentioned", False)
        widget = self._build_message(msg)
        if mentioned:
            widget.bgcolor = "#3b2d00"
        self._messages_list.controls.append(widget)
        if mentioned:
            self._play_mention_sound()
        self.page.update()

    def _play_mention_sound(self):
        """Play a notification sound for mentions."""
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            try:
                import subprocess
                subprocess.run(["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                             capture_output=True, timeout=2)
            except Exception:
                pass

    def clear_messages(self):
        """Clear all messages."""
        self._messages.clear()
        self._messages_list.controls.clear()
        self.page.update()

    def _build_message(self, msg: dict) -> ft.Container:
        """Build a single message widget."""
        username = msg.get("username", "Unknown")
        content = msg.get("content", "")
        timestamp = msg.get("timestamp") or msg.get("created_at", "")
        msg_id = msg.get("id", "")
        reactions = msg.get("reactions", [])
        attachments = msg.get("attachments") or []

        # Parse attachments from JSON string if needed
        if isinstance(attachments, str):
            try:
                import json as _json
                attachments = _json.loads(attachments)
            except Exception:
                attachments = []

        # Format timestamp
        if isinstance(timestamp, (int, float)):
            ts = time.strftime("%H:%M", time.localtime(timestamp))
        else:
            ts = str(timestamp)[:5] if timestamp else ""

        # Username color: use highest role color, else hash-based fallback
        user_id = msg.get("user_id", username)
        roles = msg.get("roles", [])
        username_color = None
        if roles:
            # Pick the role with the highest permissions (most privileged)
            best = max(roles, key=lambda r: r.get("permissions", 0))
            c = best.get("color", 0)
            if c:
                username_color = f"#{c:06x}"
        if not username_color:
            colors = [ACCENT, "#e91e63", "#9c27b0", "#ff9800", "#4caf50", "#00bcd4"]
            color_idx = hash(user_id) % len(colors)
            username_color = colors[color_idx]

        # Build reactions row
        reaction_row = self._build_reactions(reactions, msg_id) if reactions else None

        # Message content
        username_widget = ft.Container(
            content=ft.Text(username, color=username_color, size=14, weight=ft.FontWeight.BOLD),
            on_hover=lambda e, uid=user_id, un=username, uc=username_color: self._on_username_hover(e, uid, un, uc),
            ink=False,
            border_radius=4,
            padding=ft.padding.symmetric(horizontal=2, vertical=0),
        )
        content_widgets = [
            ft.Row([
                username_widget,
                ft.Text(ts, color=FG_MUTED, size=11),
                ft.IconButton(
                    icon=ft.Icons.MORE_HORIZ,
                    icon_color=FG_MUTED,
                    icon_size=14,
                    tooltip="Message options",
                    on_click=lambda e, mid=msg_id: self._on_message_menu(mid),
                    visible=False,
                ),
            ], spacing=8),
            ft.Text(content, color=FG, size=14, selectable=True, no_wrap=False),
        ]

        # Render attachments
        for att in attachments:
            att_type = att.get("type", "")
            att_name = att.get("name", "file")
            att_data = att.get("data", "")
            is_encrypted = att.get("encrypted", False)
            if att_type == "image" and att_data:
                try:
                    raw_bytes = _b64.b64decode(att_data)
                    if is_encrypted and self.client:
                        ch_id = self.client.current_channel_id
                        key = self.client._channel_keys.get(ch_id) if hasattr(self.client, '_channel_keys') else None
                        if key:
                            raw_bytes = self.client._decrypt_with_key(key, raw_bytes)
                    img_b64 = _b64.b64encode(raw_bytes).decode()
                    img_widget = ft.Image(src_base64=img_b64, width=300, fit=ft.ImageFit.CONTAIN)
                    content_widgets.append(ft.Container(
                        content=img_widget,
                        border_radius=8,
                        bgcolor=BG_DARKER,
                        padding=4,
                        on_click=lambda e, ib64=img_b64, nm=att_name: self._preview_image(ib64, nm),
                        ink=True,
                        tooltip="Click to preview",
                    ))
                except Exception:
                    content_widgets.append(ft.Text(f"[image: {att_name}]", color=FG_DIM, size=12))
            elif att_type == "file" and att_name:
                size = att.get("size", 0)
                mime = att.get("mime", "application/octet-stream")
                size_str = f"{size / 1024:.1f} KB" if size < 1024 * 1024 else f"{size / (1024*1024):.1f} MB"
                content_widgets.append(ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.DOWNLOAD, color=ACCENT, size=20),
                        ft.Column([
                            ft.Text(att_name, color=FG, size=13),
                            ft.Text(size_str, color=FG_DIM, size=11),
                        ], spacing=0, expand=True),
                        ft.Icon(ft.Icons.DOWNLOAD, color=FG_DIM, size=16),
                    ], spacing=8),
                    bgcolor=BG_DARKER,
                    border_radius=8,
                    padding=8,
                    on_click=lambda e, d=att_data, nm=att_name, mi=mime: self._download_file(d, nm, mi),
                    ink=True,
                    tooltip="Click to download",
                ))

        if reaction_row:
            content_widgets.append(reaction_row)

        return ft.Container(
            content=ft.Column(content_widgets, spacing=2),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=8,
            on_hover=self._on_message_hover,
            data=msg_id,
        )

    def _build_reactions(self, reactions: list, msg_id: str) -> ft.Row:
        """Build reactions row for a message."""
        items = []
        for r in reactions:
            emoji = r.get("emoji", "")
            count = r.get("count", 1)
            btn = ft.Container(
                content=ft.Row([
                    ft.Text(emoji, size=14),
                    ft.Text(str(count), color=FG_DIM, size=12),
                ], spacing=4),
                padding=ft.padding.symmetric(horizontal=6, vertical=2),
                border_radius=12,
                bgcolor=REACTION_BG,
                border=ft.border.all(1, REACTION_BORDER),
                on_click=lambda e, mid=msg_id, em=emoji: self._on_reaction_click(mid, em),
            )
            items.append(btn)
        return ft.Row(items, spacing=4, wrap=True)

    def _toggle_search_panel(self, e=None):
        """Toggle the search panel visibility."""
        self._search_panel.visible = not self._search_panel.visible
        if self._search_panel.visible:
            self._search_field.value = ""
            self._search_results_list.controls.clear()
        self.page.update()

    def _on_search_submit(self, e):
        """Execute search from the chat search panel."""
        query = self._search_field.value.strip()
        if not query:
            return
        user_filter = self._search_user_field.value.strip() if self._search_user_field.value else ""
        ch_filter = self._search_channel_dropdown.value if self._search_channel_dropdown.value else ""
        self.page.run_task(self._execute_search, query, user_filter, ch_filter)

    async def _execute_search(self, query: str, user_filter: str, ch_filter: str):
        """Run search and display results."""
        await self.client.send_search_messages(
            query,
            server_id=self.client.current_server_id or None,
            channel_id=int(ch_filter) if ch_filter else None,
        )

    def _on_message_hover(self, e):
        """Show/hide menu button on hover."""
        if isinstance(e.control.content, ft.Column):
            for row in e.control.content.controls:
                if isinstance(row, ft.Row) and len(row.controls) >= 4:
                    row.controls[3].visible = e.data == "true"
                    row.update()
                    break

    def _on_username_hover(self, e, user_id: str, username: str, color: str):
        """Show mini-profile popup on username hover."""
        if e.data != "true":
            # Mouse left — close popup
            for ctrl in self.page.overlay[:]:
                if isinstance(ctrl, ft.AlertDialog) and getattr(ctrl, '_is_profile', False):
                    ctrl.open = False
                    self.page.overlay.remove(ctrl)
            self.page.update()
            return

        # Find member in client's member list
        member = None
        for m in getattr(self.client, 'members', []):
            if str(m.get('id', '')) == str(user_id):
                member = m
                break

        display = member.get('display_name', member.get('username', username)) if member else username
        avatar = member.get('avatar_url', '') if member else ''
        status = member.get('status', 'offline') if member else 'offline'
        roles = member.get('roles', []) if member else []

        status_icons = {'online': '🟢', 'idle': '🟡', 'dnd': '🔴'}
        status_text = status_icons.get(status, '⚫')

        header = ft.Row([
            ft.Text(f'{status_text} {display}', color=color, size=15, weight=ft.FontWeight.BOLD),
        ], spacing=8)

        fields = []
        fields.append(ft.Row([
            ft.Text('Username:', color=FG_DIM, size=11),
            ft.Text(username, color=FG, size=11),
        ], spacing=8))
        fields.append(ft.Row([
            ft.Text('Status:', color=FG_DIM, size=11),
            ft.Text(f'{status_text} {status}', color=FG, size=11),
        ], spacing=8))
        if roles:
            role_strs = [f"{r.get('name', '?')}" for r in roles[:5]]
            fields.append(ft.Row([
                ft.Text('Roles:', color=FG_DIM, size=11),
                ft.Text(', '.join(role_strs), color=FG, size=11),
            ], spacing=8))

        # Build avatar if available
        content_controls = []
        if avatar:
            try:
                if avatar.startswith('data:'):
                    content_controls.append(ft.Image(src_base64=avatar.split(',')[1] if ',' in avatar else '', width=48, height=48, border_radius=24))
                else:
                    content_controls.append(ft.Image(src=avatar, width=48, height=48, border_radius=24))
            except Exception:
                pass
        content_controls.extend(fields)

        async def on_dm(e):
            for ctrl in self.page.overlay[:]:
                if isinstance(ctrl, ft.AlertDialog) and getattr(ctrl, '_is_profile', False):
                    ctrl.open = False
                    self.page.overlay.remove(ctrl)
            self.page.update()
            await self.client.send_dm_send(int(user_id), '')

        async def on_add_friend(e):
            await self.client.send_friend_add(int(user_id))

        dialog = ft.AlertDialog(
            title=header,
            content=ft.Column(content_controls, spacing=6),
            actions=[
                ft.TextButton('Add Friend', on_click=on_add_friend, tooltip='Send friend request'),
                ft.TextButton('Send DM', on_click=on_dm, tooltip='Open direct message'),
            ],
            bgcolor=BG_DARK,
        )
        dialog._is_profile = True

        # Close any existing profile popup
        for ctrl in self.page.overlay[:]:
            if isinstance(ctrl, ft.AlertDialog) and getattr(ctrl, '_is_profile', False):
                ctrl.open = False
                self.page.overlay.remove(ctrl)

        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _on_message_menu(self, msg_id: str):
        """Show message context menu."""
        is_own = any(m.get("id") == msg_id and m.get("user_id") == getattr(self.client, "user_id", "")
                     for m in self._messages)
        msg_content = ""
        for m in self._messages:
            if m.get("id") == msg_id:
                msg_content = m.get("content", "")
                break
        self._context_menu.show(msg_id, is_own=is_own, content=msg_content)

    def _on_reaction_click(self, msg_id: str, emoji: str):
        """Toggle a reaction on a message."""
        self.page.run_task(self.client.send_reaction_add, int(msg_id), emoji)

    def _on_send(self, e):
        """Send a message."""
        text = self._input_field.value.strip()
        if not text:
            return

        self.page.run_task(self._send_message, text)
        self._input_field.value = ""
        self._input_field.update()

    def _show_spell_check(self, text: str, misspelled: list):
        """Show spell check dialog with suggestions."""
        from client.flet_app.spellcheck import suggestions
        words_text = ", ".join(f'"{w}"' for w, _ in misspelled[:8])
        if len(misspelled) > 8:
            words_text += f", +{len(misspelled) - 8} more"

        # Build suggestion rows
        suggestion_rows = []
        word_suggestions = {}
        for word, _ in misspelled[:6]:
            suggs = suggestions(word)
            if suggs:
                word_suggestions[word] = suggs
                buttons = []
                for s in suggs[:3]:
                    buttons.append(ft.TextButton(
                        text=s,
                        on_click=lambda e, w=word, s=s, t=text: self._replace_word(t, w, s),
                    ))
                row = ft.Row([
                    ft.Text(f'"{word}"', color=FG, size=13, weight=ft.FontWeight.BOLD),
                    ft.Row(buttons, spacing=4),
                ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                suggestion_rows.append(row)

        async def on_send_anyway(e):
            dialog.open = False
            self.page.overlay.remove(dialog)
            self.page.update()
            self.page.run_task(self._send_message, text)
            self._input_field.value = ""
            self._input_field.update()

        async def on_cancel(e):
            dialog.open = False
            self.page.overlay.remove(dialog)
            self.page.update()

        content = [ft.Text(f'Misspelled: {words_text}', color=FG_DIM, size=12)]
        if suggestion_rows:
            content.append(ft.Divider(height=1, color=DIVIDER))
            content.extend(suggestion_rows)

        dialog = ft.AlertDialog(
            title=ft.Text("Spell Check", color=FG),
            content=ft.Column(content, spacing=8, scroll=ft.ScrollMode.AUTO),
            actions=[
                ft.TextButton("Cancel", on_click=on_cancel, tooltip="Discard message"),
                ft.TextButton("Send Anyway", on_click=on_send_anyway, tooltip="Send with misspellings"),
            ],
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _replace_word(self, text: str, old_word: str, new_word: str):
        """Replace a misspelled word and re-check."""
        new_text = text.replace(old_word, new_word, 1)
        self._input_field.value = new_text
        self.page.update()
        # Close the dialog
        for ctrl in self.page.overlay[:]:
            if isinstance(ctrl, ft.AlertDialog) and ctrl.title and getattr(ctrl.title, 'value', '') == "Spell Check":
                ctrl.open = False
                self.page.overlay.remove(ctrl)
        self.page.update()
        # Re-check spelling
        self._on_send(None)

    async def _send_message(self, text: str):
        """Send message via client."""
        if hasattr(self.client, 'send_message_send'):
            await self.client.send_message_send(
                self.client.current_channel_id, text
            )

    def _on_typing(self, e):
        """Handle typing indicator."""
        now = time.time()
        if now - self._typing_timer > 3:
            self._typing_timer = now
            if hasattr(self.client, 'send_typing'):
                self.page.run_task(self.client.send_typing_start, self.client.current_channel_id)

    def _toggle_emoji(self, e):
        """Open emoji picker."""
        self._emoji_picker.show()

    def _on_emoji_select(self, emoji: str):
        """Insert selected emoji into the input field."""
        self._input_field.value = (self._input_field.value or "") + emoji
        self._input_field.update()

    def show_typing(self, users: list[str]):
        """Show typing indicator."""
        if not users:
            self._typing_label.value = ""
        elif len(users) == 1:
            self._typing_label.value = f"{users[0]} is typing..."
        else:
            self._typing_label.value = f"{', '.join(users)} are typing..."
        self.page.update()

    def _on_send_image(self, e):
        """Open image file picker."""
        self._pending_file_action = "image"
        self._image_picker.pick_files(
            dialog_title="Select Image",
            allowed_extensions=["png", "jpg", "jpeg", "gif", "webp", "bmp"],
            allow_multiple=False,
        )

    def _on_send_file(self, e):
        """Open file picker."""
        self._pending_file_action = "file"
        self._file_picker.pick_files(
            dialog_title="Select File",
            allow_multiple=False,
        )

    def _on_image_picked(self, e):
        """Handle image file selection."""
        if e.files and len(e.files) > 0:
            path = e.files[0].path
            if path and hasattr(self.client, 'send_image_channel'):
                self.page.run_task(self.client.send_image_channel, path)

    def _on_file_picked(self, e):
        """Handle file selection."""
        if e.files and len(e.files) > 0:
            path = e.files[0].path
            if path and hasattr(self.client, 'send_file_channel'):
                self.page.run_task(self.client.send_file_channel, path)

    def _preview_image(self, img_b64: str, filename: str):
        """Open image preview dialog."""
        dialog = ft.AlertDialog(
            title=ft.Text(filename, color=FG),
            content=ft.Container(
                content=ft.Image(src_base64=img_b64, fit=ft.ImageFit.CONTAIN, width=600, height=500),
                border_radius=8,
                bgcolor=BG_DARKER,
            ),
            bgcolor=BG_DARK,
            actions=[
                ft.TextButton("Close", on_click=lambda e: self._close_dialog(dialog), tooltip="Close preview"),
                ft.ElevatedButton(
                    "Download", icon=ft.Icons.DOWNLOAD, bgcolor=ACCENT, color=BG_DARK,
                    tooltip="Save image to disk",
                    on_click=lambda e: self._download_image(img_b64, filename),
                ),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _download_image(self, img_b64: str, filename: str):
        """Save image to disk via file picker."""
        self._pending_save_data[filename] = (_b64.b64decode(img_b64), "image/webp")
        self._save_picker.save_file(
            dialog_title="Save Image",
            file_name=filename,
        )

    def _download_file(self, data_b64: str, filename: str, mime: str):
        """Save file to disk via file picker."""
        raw = _b64.b64decode(data_b64)
        self._pending_save_data[filename] = (raw, mime)
        self._save_picker.save_file(
            dialog_title="Save File",
            file_name=filename,
        )

    def _on_save_result(self, e):
        """Handle save file picker result."""
        if e.path:
            name = e.file_name or e.path.split("/")[-1]
            data_tuple = self._pending_save_data.get(name)
            if not data_tuple:
                # Try matching by path suffix
                for k, v in self._pending_save_data.items():
                    if e.path.endswith(k):
                        data_tuple = v
                        break
            if data_tuple:
                import pathlib
                pathlib.Path(e.path).write_bytes(data_tuple[0])
                self.page.snack_bar = ft.SnackBar(
                    ft.Text(f"Saved: {name}", color=FG), bgcolor="#43b581",
                )
                self.page.snack_bar.open = True
                self.page.update()
            self._pending_save_data.pop(name, None)

    def _close_dialog(self, dialog: ft.AlertDialog):
        dialog.open = False
        self.page.update()
