"""Dialogs and popups for Labhair-liom Flet GUI."""

from __future__ import annotations

import asyncio

import flet as ft
from typing import TYPE_CHECKING, Callable

from client.flet_app.theme import *

if TYPE_CHECKING:
    from client.main import ChatClient


# ── Emoji Data ──────────────────────────────────────────────────

EMOJI_CATEGORIES = {
    "Smileys": [
        "😀", "😃", "😄", "😁", "😆", "😅", "🤣", "😂", "🙂", "🙃",
        "😉", "😊", "😇", "🥰", "😍", "🤩", "😘", "😗", "😚", "😙",
        "🥲", "😋", "😛", "😜", "🤪", "😝", "🤑", "🤗", "🤭", "🫢",
        "🤫", "🤔", "🫡", "🤐", "🤨", "😐", "😑", "😶", "🫥", "😏",
        "😒", "🙄", "😬", "🤥", "😌", "😔", "😪", "🤤", "😴", "😷",
        "🤒", "🤕", "🤢", "🤮", "🥵", "🥶", "🥴", "😵", "🤯", "🤠",
        "🥳", "🥸", "😎", "🤓", "🧐", "😕", "🫤", "😟", "🙁", "☹️",
        "😮", "😯", "😲", "😳", "🥺", "🥹", "😦", "😧", "😨", "😰",
        "😥", "😢", "😭", "😱", "😖", "😣", "😞", "😓", "😩", "😫",
    ],
    "Gestures": [
        "👋", "🤚", "🖐️", "✋", "🖖", "🫱", "🫲", "🫳", "🫴", "👌",
        "🤌", "🤏", "✌️", "🤞", "🫰", "🤟", "🤘", "🤙", "👈", "👉",
        "👆", "🖕", "👇", "☝️", "🫵", "👍", "👎", "✊", "👊", "🤛",
        "🤜", "👏", "🙌", "🫶", "👐", "🤲", "🤝", "🙏", "💪", "🦾",
    ],
    "Hearts": [
        "❤️", "🧡", "💛", "💚", "💙", "💜", "🖤", "🤍", "🤎", "💔",
        "❤️‍🔥", "❤️‍🩹", "❣️", "💕", "💞", "💓", "💗", "💖", "💘", "💝",
    ],
    "Objects": [
        "🎉", "🎊", "🎈", "🎁", "🎂", "🎄", "🎃", "🎗️", "🎟️", "🎫",
        "🔔", "🔕", "📣", "📢", "💬", "💭", "🗯️", "♠️", "♣️", "♥️",
        "♦️", "🔑", "🗝️", "🔒", "🔓", "🛡️", "⚙️", "🔧", "🔨", "🔩",
    ],
    "Symbols": [
        "✅", "❌", "⭕", "❗", "❓", "‼️", "⁉️", "💯", "🔥", "✨",
        "🌟", "💫", "💥", "💢", "💤", "💬", "👁️‍🗨️", "🗨️", "🗯️", "🔊",
        "🔇", "🔉", "🔊", "📢", "📻", "⚡", "🏁", "🚩", "🎌", "🏴",
    ],
}


class EmojiPicker:
    """Popup emoji picker with category tabs."""

    def __init__(self, page: ft.Page, on_select: Callable[[str], None]):
        self.page = page
        self.on_select = on_select
        self._dialog: ft.AlertDialog | None = None
        self._current_category = "Smileys"

    def show(self):
        """Show the emoji picker dialog."""
        if self._dialog and self._dialog.open:
            self._dialog.open = False
            self.page.update()
            return

        category_tabs = ft.Tabs(
            selected_index=0,
            tabs=[ft.Tab(text=cat) for cat in EMOJI_CATEGORIES],
            on_change=self._on_category_change,
            label_color=FG,
            unselected_label_color=FG_DIM,
            indicator_color=ACCENT,
            divider_color=DIVIDER,
            height=36,
        )

        self._emoji_grid = ft.GridView(
            runs_count=10,
            max_extent=36,
            spacing=4,
            run_spacing=4,
            child_aspect_ratio=1,
        )
        self._populate_grid("Smileys")

        self._dialog = ft.AlertDialog(
            title=ft.Text("Emoji", color=FG, size=16),
            content=ft.Container(
                content=ft.Column([
                    category_tabs,
                    self._emoji_grid,
                ], spacing=8),
                width=360,
                height=320,
            ),
            bgcolor=BG_DARK,
            shape=ft.RoundedRectangleBorder(radius=12),
        )

        self.page.overlay.append(self._dialog)
        self._dialog.open = True
        self.page.update()

    def _populate_grid(self, category: str):
        """Fill the grid with emojis from a category."""
        self._emoji_grid.controls.clear()
        for emoji in EMOJI_CATEGORIES.get(category, []):
            btn = ft.Container(
                content=ft.Text(emoji, size=20, text_align=ft.TextAlign.CENTER),
                alignment=ft.alignment.center,
                border_radius=6,
                on_click=lambda e, em=emoji: self._on_emoji_click(em),
                on_hover=self._on_emoji_hover,
            )
            self._emoji_grid.controls.append(btn)

    def _on_category_change(self, e):
        """Switch emoji category."""
        idx = e.control.selected_index
        self._current_category = list(EMOJI_CATEGORIES.keys())[idx]
        self._populate_grid(self._current_category)
        self.page.update()

    def _on_emoji_click(self, emoji: str):
        """Insert selected emoji."""
        self.on_select(emoji)
        if self._dialog:
            self._dialog.open = False
            self.page.update()

    def _on_emoji_hover(self, e):
        """Hover effect on emoji buttons."""
        e.control.bgcolor = BG_HOVER if e.data == "true" else None
        e.control.update()


class MessageContextMenu:
    """Context menu for right-clicking on a message."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client
        self._menu: ft.AlertDialog | None = None

    def show(self, msg_id: str, is_own: bool = False, content: str = ""):
        """Show the context menu for a message."""
        self._last_menu_content = content
        items = []

        # React submenu
        quick_reactions = [
            ("👍", "👍"), ("❤️", "❤️"), ("😂", "😂"), ("👎", "👎"),
        ]
        for label, emoji in quick_reactions:
            items.append(ft.PopupMenuItem(
                content=ft.Row([ft.Text(emoji, size=16), ft.Text(label, color=FG)]),
                on_click=lambda e, mid=msg_id, em=emoji: self._add_reaction(mid, em),
            ))

        items.append(ft.PopupMenuDivider())

        if is_own:
            items.append(ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.EDIT, size=16, color=FG),
                    ft.Text("Edit Message", color=FG),
                ]),
                on_click=lambda e, mid=msg_id: self._edit_message(mid),
            ))

        items.append(ft.PopupMenuItem(
            content=ft.Row([
                ft.Icon(ft.Icons.PUSH_PIN_OUTLINED, size=16, color=FG),
                ft.Text("Pin Message", color=FG),
            ]),
            on_click=lambda e, mid=msg_id: self._pin_message(mid),
        ))

        if is_own:
            items.append(ft.PopupMenuDivider())
            items.append(ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.DELETE_OUTLINE, size=16, color="#f23f43"),
                    ft.Text("Delete Message", color="#f23f43"),
                ]),
                on_click=lambda e, mid=msg_id: self._delete_message(mid),
            ))

        menu = ft.PopupMenuButton(
            items=items,
            bgcolor=BG_DARK,
            elevation=8,
        )

        # Trigger the menu
        menu.__getattribute__("_on_click")(None)

    def _add_reaction(self, msg_id: str, emoji: str):
        self.page.run_task(self.client.send_reaction_add, int(msg_id), emoji)

    def _edit_message(self, msg_id: str):
        content = self._last_menu_content if hasattr(self, '_last_menu_content') else ""
        edit_field = ft.TextField(
            value=content,
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=12,
            text_size=14,
            autofocus=True,
            min_lines=2,
            max_lines=6,
        )

        async def on_save(e):
            new_text = edit_field.value.strip()
            if new_text:
                await self.client.send_message_edit(int(msg_id), new_text)
            dialog.open = False
            self.page.overlay.remove(dialog)
            self.page.update()

        async def on_cancel(e):
            dialog.open = False
            self.page.overlay.remove(dialog)
            self.page.update()

        dialog = ft.AlertDialog(
            title=ft.Text("Edit Message", color=FG),
            content=ft.Column([edit_field], spacing=8),
            actions=[
                ft.TextButton("Cancel", on_click=on_cancel, tooltip="Discard changes"),
                ft.TextButton("Save", on_click=on_save, tooltip="Save edits"),
            ],
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _pin_message(self, msg_id: str):
        self.page.run_task(self.client.send_msg_pin, int(msg_id))

    def _delete_message(self, msg_id: str):
        """Show confirmation and delete."""
        self._show_delete_confirmation(msg_id)

    def _show_delete_confirmation(self, msg_id: str):
        async def on_confirm(e):
            await self.client.send_message_delete(msg_id)
            dialog.open = False
            self.page.update()

        dialog = ft.AlertDialog(
            title=ft.Text("Delete Message", color=FG),
            content=ft.Text("Are you sure you want to delete this message?", color=FG_DIM),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close(dialog), tooltip="Keep message"),
                ft.ElevatedButton("Delete", on_click=on_confirm, bgcolor="#f23f43", color=FG, tooltip="Permanently delete"),
            ],
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _close(self, dialog: ft.AlertDialog):
        dialog.open = False
        self.page.update()


class ServerSettingsDialog:
    """Server settings dialog with tabs for Server, Channels, Roles."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client
        self._dialog: ft.AlertDialog | None = None
        self._server: dict = {}

    def show(self, server: dict):
        """Show server settings."""
        self._server = server
        server_name = server.get("name", "Server")
        server_desc = server.get("description", "")
        channels = server.get("channels", [])
        roles = server.get("roles", [])

        # Check if current user is admin/owner
        uid = getattr(self.client, 'db_user_id', None)
        is_admin = False
        if uid and hasattr(self.client, 'members'):
            for m in self.client.members:
                if m.get("id") == uid:
                    for r in m.get("roles", []):
                        if r.get("permissions", 0) == 2147483647:
                            is_admin = True
                            break
                    break
        # Also check if owner
        if uid and server.get("owner_id") == uid:
            is_admin = True

        name_field = ft.TextField(
            value=server_name,
            label="Server Name",
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
        )
        desc_field = ft.TextField(
            value=server_desc,
            label="Description",
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            multiline=True,
        )

        # Server icon
        current_icon_url = server.get("icon_url", "") or ""
        self._selected_icon_path: str = ""

        if current_icon_url and current_icon_url.startswith("http"):
            self._icon_preview = ft.Image(src=current_icon_url, width=64, height=64, fit=ft.ImageFit.COVER)
        elif current_icon_url and current_icon_url.startswith("data:"):
            self._icon_preview = ft.Image(src=current_icon_url, width=64, height=64, fit=ft.ImageFit.COVER)
        else:
            self._icon_preview = ft.Icon(ft.Icons.DNS, color=FG_DIM, size=64)

        self._icon_picker = ft.FilePicker(on_result=self._on_icon_picked)
        self.page.overlay.append(self._icon_picker)
        self._icon_label = ft.Text("No new icon selected", color=FG_DIM, size=11)

        async def on_save(e):
            new_name = name_field.value.strip()
            new_desc = desc_field.value.strip()
            icon_url = None
            # Upload new icon if selected
            if self._selected_icon_path:
                try:
                    import os, mimetypes
                    from PIL import Image
                    from io import BytesIO
                    import base64 as _b64mod
                    path = self._selected_icon_path
                    mime = mimetypes.guess_type(path)[0] or "image/png"
                    img = Image.open(path)
                    img = img.convert("RGBA") if img.mode == "RGBA" else img.convert("RGB")
                    img.thumbnail((128, 128))
                    buf = BytesIO()
                    img.save(buf, format="PNG")
                    data = buf.getvalue()
                    b64str = _b64mod.b64encode(data).decode()
                    icon_url = f"data:image/png;base64,{b64str}"
                except Exception:
                    pass
            if new_name:
                kwargs = {"name": new_name, "description": new_desc}
                if icon_url:
                    kwargs["icon_url"] = icon_url
                await self.client.send_server_update(server.get("id"), **kwargs)
            self._close()

        def on_delete_server(e):
            self._show_delete_server_confirm(server)

        # Channels tab
        channel_list = ft.ListView(spacing=2, height=300)
        for ch in channels:
            ch_type = ch.get("channel_type", ch.get("type", "text"))
            ch_id = ch.get("id", "")
            ch_name = ch.get("name", "?")
            icon = ft.Icons.MIC_OUTLINED if ch_type == "voice" else ft.Icons.TAG
            channel_list.controls.append(ft.Container(
                content=ft.Row([
                    ft.Icon(icon, color=CHANNEL_VOICE if ch_type == "voice" else FG_DIM, size=16),
                    ft.Text(ch_name, color=FG, expand=True),
                    ft.Text(ch_type, color=FG_DIM, size=11),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE, icon_color="#f23f43", icon_size=14,
                        tooltip="Delete channel",
                        on_click=lambda e, cid=ch_id, cn=ch_name: self.page.run_task(
                            self._confirm_delete_channel, cid, cn,
                        ),
                    ),
                ]),
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                border_radius=6,
            ))

        new_ch_name = ft.TextField(
            hint_text="New channel name",
            bgcolor=BG_INPUT, color=FG, border_color=DIVIDER,
            border_radius=8, content_padding=8, expand=True,
        )
        new_ch_type = ft.Dropdown(
            width=100,
            options=[ft.dropdown.Option("text"), ft.dropdown.Option("voice")],
            value="text",
            bgcolor=BG_INPUT, color=FG, border_color=DIVIDER,
            border_radius=8, content_padding=8,
        )
        add_channel_row = ft.Row([
            new_ch_name,
            new_ch_type,
            ft.IconButton(
                icon=ft.Icons.ADD, icon_color=ACCENT, icon_size=18,
                tooltip="Add channel",
                on_click=lambda e: self.page.run_task(
                    self._create_channel,
                    server.get("id"), new_ch_name.value, new_ch_type.value,
                ),
            ),
        ])

        # Roles tab
        role_list = ft.ListView(spacing=2, height=300)
        for role in roles:
            color = role.get("color", FG)
            role_id = role.get("id", "")
            role_name = role.get("name", "?")
            role_list.controls.append(ft.Container(
                content=ft.Row([
                    ft.Container(width=12, height=12, border_radius=6, bgcolor=f"#{color:06x}" if color else FG_DIM),
                    ft.Text(role_name, color=FG, expand=True),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE, icon_color="#f23f43", icon_size=14,
                        tooltip="Delete role",
                        on_click=lambda e, rid=role_id: self.page.run_task(
                            self._delete_role, rid,
                        ),
                        visible=is_admin,
                    ),
                ]),
                padding=ft.padding.symmetric(horizontal=8, vertical=4),
                border_radius=6,
            ))

        new_role_name = ft.TextField(
            hint_text="New role name",
            bgcolor=BG_INPUT, color=FG, border_color=DIVIDER,
            border_radius=8, content_padding=8, expand=True,
        )
        _role_color_value = 0
        _role_color_display = ft.Container(
            width=24, height=24, border_radius=12, bgcolor="#80848e",
            border=ft.border.all(2, FG_DIM),
        )

        def _pick_role_color(hex_color: str):
            nonlocal _role_color_value
            _role_color_value = int(hex_color.lstrip("#"), 16)
            _role_color_display.bgcolor = hex_color
            _role_color_display.update()

        preset_colors = [
            ("#f23f43", "Red"), ("#faa61a", "Orange"), ("#fee75c", "Yellow"),
            ("#57f287", "Green"), ("#5865f2", "Blue"), ("#9b59b6", "Purple"),
            ("#eb459e", "Pink"), ("#80848e", "Gray"),
        ]
        color_buttons = ft.Row(
            [ft.Container(
                width=20, height=20, border_radius=10, bgcolor=c,
                border=ft.border.all(2, FG_DIM),
                on_click=lambda e, hc=c: _pick_role_color(hc),
                on_hover=lambda e: setattr(e.control, 'scale', ft.transform.Scale(1.3) if e.data == "true" else ft.transform.Scale(1.0)) or e.control.update(),
            ) for c, _ in preset_colors],
            spacing=4,
        )

        add_role_row = ft.Column([
            ft.Row([
                new_role_name,
                _role_color_display,
                ft.IconButton(
                    icon=ft.Icons.ADD, icon_color=ACCENT, icon_size=18,
                    tooltip="Add role",
                    on_click=lambda e: self.page.run_task(
                        self._create_role,
                        server.get("id"), new_role_name.value, _role_color_value,
                    ),
                ),
            ]),
            color_buttons,
        ], spacing=4, visible=is_admin)

        tabs = ft.Tabs(
            selected_index=0,
            width=450,
            height=400,
            tabs=[
                ft.Tab(
                    text="Server",
                    content=ft.Column([
                        ft.Row([
                            self._icon_preview,
                            ft.Column([
                                name_field,
                                desc_field,
                            ], spacing=8, expand=True),
                        ], spacing=12),
                        ft.Text("Server Icon", color=FG, size=13, weight=ft.FontWeight.BOLD),
                        ft.Row([
                            ft.ElevatedButton(
                                "Choose Image", icon=ft.Icons.IMAGE,
                                tooltip="Upload server icon",
                                on_click=lambda e: self._icon_picker.pick_files(
                                    allowed_extensions=["png", "jpg", "jpeg", "gif"],
                                    dialog_title="Choose server icon",
                                ),
                            ),
                            self._icon_label,
                        ], spacing=8),
                        ft.Divider(color=DIVIDER),
                        ft.ElevatedButton(
                            "Delete Server", bgcolor="#f23f43", color=FG,
                            tooltip="Permanently delete this server",
                            on_click=on_delete_server,
                            visible=is_admin,
                        ),
                    ], spacing=10, scroll=ft.ScrollMode.AUTO),
                ),
                ft.Tab(
                    text=f"Channels ({len(channels)})",
                    content=ft.Column([channel_list, add_channel_row], spacing=4),
                ),
                ft.Tab(
                    text=f"Roles ({len(roles)})",
                    content=ft.Column([role_list, add_role_row], spacing=4),
                ),
            ],
            label_color=FG,
            unselected_label_color=FG_DIM,
            indicator_color=ACCENT,
            divider_color=DIVIDER,
        )

        self._dialog = ft.AlertDialog(
            title=ft.Text(f"Server Settings — {server_name}", color=FG),
            content=ft.Container(
                content=tabs,
                width=450,
                height=420,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close(), tooltip="Discard changes"),
                ft.ElevatedButton("Save", on_click=on_save, bgcolor=ACCENT, color=FG, tooltip="Save server settings"),
            ],
            bgcolor=BG_DARK,
            shape=ft.RoundedRectangleBorder(radius=12),
        )

        self.page.overlay.append(self._dialog)
        self._dialog.open = True
        self.page.update()

    def _on_icon_picked(self, e: ft.FilePickerResultEvent):
        if e.files:
            self._selected_icon_path = e.files[0].path
            self._icon_label.value = e.files[0].name
            self._icon_label.color = FG
        else:
            self._selected_icon_path = ""
            self._icon_label.value = "No new icon selected"
            self._icon_label.color = FG_DIM
        self.page.update()

    def _show_delete_server_confirm(self, server: dict):
        """Show confirmation dialog for deleting a server."""
        name = server.get("name", "Server")
        confirm = ft.AlertDialog(
            title=ft.Text(f"Delete {name}?", color="#f23f43"),
            content=ft.Text(
                f"Are you sure you want to delete \"{name}\"? "
                "ALL channels, messages, roles, and members will be permanently deleted. "
                "This cannot be undone.",
                color=FG,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close_confirm(confirm), tooltip="Keep server"),
                ft.ElevatedButton(
                    "Delete", bgcolor="#f23f43", color=FG,
                    tooltip="Permanently delete server",
                    on_click=lambda e: self.page.run_task(
                        self._delete_server, server.get("id"), confirm,
                    ),
                ),
            ],
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(confirm)
        confirm.open = True
        self.page.update()

    async def _delete_server(self, server_id, confirm_dialog):
        """Delete the server."""
        await self.client.send_server_delete(int(server_id))
        self._close_confirm(confirm_dialog)
        self._close()

    async def _confirm_delete_channel(self, channel_id, channel_name):
        """Show confirmation for deleting a channel."""
        confirm = ft.AlertDialog(
            title=ft.Text(f"Delete #{channel_name}?", color="#f23f43"),
            content=ft.Text(
                f"Are you sure you want to delete \"{channel_name}\"? "
                "All messages in this channel will be permanently deleted.",
                color=FG,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close_confirm(confirm), tooltip="Keep channel"),
                ft.ElevatedButton(
                    "Delete", bgcolor="#f23f43", color=FG,
                    tooltip="Permanently delete channel",
                    on_click=lambda e: self.page.run_task(
                        self._delete_channel, channel_id, confirm,
                    ),
                ),
            ],
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(confirm)
        confirm.open = True
        self.page.update()

    async def _create_channel(self, server_id, name, ch_type):
        """Create a new channel."""
        if not name or not name.strip():
            return
        await self.client.send_channel_create(int(server_id), name.strip(), ch_type or "text")
        self._close()

    async def _delete_channel(self, channel_id, confirm_dialog=None):
        """Delete a channel."""
        if channel_id:
            await self.client.send_channel_delete(int(channel_id))
            if confirm_dialog:
                self._close_confirm(confirm_dialog)
            self._close()

    async def _create_role(self, server_id, name, color=0):
        """Create a new role."""
        if not name or not name.strip():
            return
        await self.client.send_role_create(int(server_id), name.strip(), color=color)
        await self.client.send_server_list()
        self._close()

    async def _delete_role(self, role_id):
        """Delete a role."""
        if role_id:
            await self.client.send_role_delete(int(role_id))
            await self.client.send_server_list()
            self._close()

    def _close_confirm(self, dialog):
        """Close a confirmation dialog."""
        if dialog:
            dialog.open = False
            self.page.update()
            try:
                self.page.overlay.remove(dialog)
            except ValueError:
                pass

    def _close(self):
        if self._dialog:
            self._dialog.open = False
            self.page.update()


class StatusPicker:
    """Status picker popup (Online, Idle, DnD, Invisible)."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client

    def show(self):
        items = [
            ("🟢", "Online", "online"),
            ("🟡", "Idle", "idle"),
            ("🔴", "Do Not Disturb", "dnd"),
            ("⚫", "Invisible", "offline"),
        ]

        buttons = []
        for icon, label, status in items:
            buttons.append(ft.TextButton(
                content=ft.Row([
                    ft.Text(icon, size=16),
                    ft.Text(label, color=FG),
                ], spacing=8),
                on_click=lambda e, s=status: self._pick(s),
            ))

        dialog = ft.AlertDialog(
            title=ft.Text("Set Status", color=FG),
            content=ft.Column(buttons, spacing=4),
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _pick(self, status: str):
        self.page.run_task(self.client.send_status_update, status)
        # Close the dialog
        for control in self.page.overlay[:]:
            if isinstance(control, ft.AlertDialog) and control.title and getattr(control.title, 'value', '') == "Set Status":
                control.open = False
                self.page.overlay.remove(control)
                break
        self.page.update()


class UserSettingsDialog:
    """User settings dialog (profile, status, avatar)."""

    def __init__(self, page: ft.Page, client):
        self.page = page
        self.client = client

    def show(self):
        display = getattr(self.client, 'display', 'Unknown')
        user_id = getattr(self.client, 'user_id', '')
        bio = getattr(self.client, '_bio', '') or ''
        custom_status = getattr(self.client, '_custom_status', '') or ''
        avatar_url = getattr(self.client, '_avatar_url', '') or ''

        self._bio_field = ft.TextField(
            label="Bio", value=bio, multiline=True, min_lines=2, max_lines=4,
            border_color=FG_DIM, focused_border_color=ACCENT, cursor_color=FG,
            text_style=ft.TextStyle(color=FG),
        )
        self._status_field = ft.TextField(
            label="Custom Status", value=custom_status,
            border_color=FG_DIM, focused_border_color=ACCENT, cursor_color=FG,
            text_style=ft.TextStyle(color=FG),
        )
        self._selected_avatar_path: str = ""

        # Avatar preview
        if avatar_url and avatar_url.startswith("http"):
            self._avatar_preview = ft.Image(src=avatar_url, width=64, height=64, fit=ft.ImageFit.COVER)
        else:
            self._avatar_preview = ft.Icon(ft.Icons.ACCOUNT_CIRCLE, color=FG_DIM, size=64)

        # File picker for avatar
        self._avatar_picker = ft.FilePicker(on_result=self._on_avatar_picked)
        self.page.overlay.append(self._avatar_picker)

        self._avatar_label = ft.Text("No new file selected", color=FG_DIM, size=11)

        # Privacy: auto-ignore DM requests from non-friends
        self._auto_ignore_switch = ft.Switch(
            value=bool(getattr(self.client, "auto_ignore_dm", False)),
            active_color="#faa61a",
            scale=0.8,
            tooltip="Reject DMs from people not on your friends list",
        )
        self.page.run_task(self._load_auto_ignore_value)

        content = ft.Container(
            content=ft.Column([
                ft.Row([
                    self._avatar_preview,
                    ft.Column([
                        ft.Text(display, color=FG, size=20, weight=ft.FontWeight.BOLD),
                        ft.Text(f"ID: {user_id}", color=FG_DIM, size=12),
                    ], spacing=2),
                ], spacing=12),
                ft.Divider(height=1, color=DIVIDER),
                ft.Text("Status", color=FG, size=14, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.ElevatedButton("Online", bgcolor="#43b581", color=FG, tooltip="Set status to Online", on_click=lambda e: self._set_status("online")),
                    ft.ElevatedButton("Idle", bgcolor="#faa61a", color=FG, tooltip="Set status to Idle", on_click=lambda e: self._set_status("idle")),
                    ft.ElevatedButton("DND", bgcolor="#f23f43", color=FG, tooltip="Set status to Do Not Disturb", on_click=lambda e: self._set_status("dnd")),
                    ft.ElevatedButton("Offline", bgcolor=FG_DIM, color=FG, tooltip="Set status to Offline", on_click=lambda e: self._set_status("offline")),
                ], spacing=8),
                self._status_field,
                ft.Divider(height=1, color=DIVIDER),
                ft.Text("Profile", color=FG, size=14, weight=ft.FontWeight.BOLD),
                self._bio_field,
                ft.Text("Avatar", color=FG, size=14, weight=ft.FontWeight.BOLD),
                ft.Row([
                    ft.ElevatedButton(
                        "Choose Image", icon=ft.Icons.IMAGE,
                        tooltip="Upload avatar image",
                        on_click=lambda e: self._avatar_picker.pick_files(
                            allowed_extensions=["png", "jpg", "jpeg", "gif"],
                            dialog_title="Choose avatar image",
                        ),
                    ),
                    self._avatar_label,
                ], spacing=8),
                ft.Divider(height=1, color=DIVIDER),
                ft.Text("Privacy", color=FG, size=14, weight=ft.FontWeight.BOLD),
                ft.Row([
                    self._auto_ignore_switch,
                    ft.Column([
                        ft.Text("Auto-ignore DMs from non-friends", color=FG, size=13),
                        ft.Text("Rejects messages from people not on your friends list",
                                color=FG_MUTED, size=11),
                    ], spacing=1, expand=True),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=12),
            width=420,
            padding=20,
        )

        dialog = ft.AlertDialog(
            title=ft.Text("User Settings", color=FG),
            content=content,
            bgcolor=BG_DARK,
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close(dialog), tooltip="Discard changes"),
                ft.ElevatedButton(
                    "Save", bgcolor=ACCENT, color=BG_DARK,
                    tooltip="Save user settings",
                    on_click=lambda e: self.page.run_task(self._save, dialog),
                ),
            ],
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    async def _load_auto_ignore_value(self):
        """Fetch the server-side auto-ignore value and sync the switch once the
        SETTINGS_GET response arrives."""
        try:
            await self.client.send_settings_get()
            for _ in range(40):
                if getattr(self.client, "settings_loaded", False):
                    break
                await asyncio.sleep(0.05)
            if getattr(self, "_auto_ignore_switch", None) is None:
                return
            self._auto_ignore_switch.value = bool(
                getattr(self.client, "auto_ignore_dm", False)
            )
            try:
                self.page.update()
            except Exception:
                pass
        except Exception:
            pass

    def _set_status(self, status: str):
        self.page.run_task(self.client.send_status_update, status)

    def _on_avatar_picked(self, e: ft.FilePickerResultEvent):
        if e.files:
            self._selected_avatar_path = e.files[0].path
            self._avatar_label.value = e.files[0].name
            self._avatar_label.color = FG
        else:
            self._selected_avatar_path = ""
            self._avatar_label.value = "No new file selected"
            self._avatar_label.color = FG_DIM
        self.page.update()

    async def _save(self, dialog: ft.AlertDialog):
        bio = self._bio_field.value.strip()
        custom = self._status_field.value.strip()
        avatar_path = self._selected_avatar_path or None
        err = await self.client.send_profile_update(
            bio=bio if bio else None,
            custom_status=custom if custom else None,
            avatar_path=avatar_path,
        )
        # Persist privacy setting
        await self.client.send_settings_update(
            auto_ignore_dm=bool(self._auto_ignore_switch.value)
        )
        if err:
            self.page.snack_bar = ft.SnackBar(
                ft.Text(err, color="#f04747"), bgcolor="#2c2f33",
            )
        else:
            self.page.snack_bar = ft.SnackBar(
                ft.Text("Settings saved!", color=FG), bgcolor="#43b581",
            )
        self.page.snack_bar.open = True
        self._close(dialog)

    def _close(self, dialog: ft.AlertDialog):
        dialog.open = False
        self.page.update()


class InviteDialog:
    """Invite management dialog — create, list, and delete invite codes."""

    def __init__(self, page: ft.Page, client):
        self.page = page
        self.client = client
        self._dialog: ft.AlertDialog | None = None
        self._invites_list: ft.Column | None = None

    def show(self, server_id: int):
        self._server_id = server_id
        self._invites_list = ft.Column(spacing=4)

        create_row = ft.Row([
            ft.ElevatedButton(
                "Create Invite", icon=ft.Icons.ADD, bgcolor=ACCENT, color=BG_DARK,
                tooltip="Generate new invite code",
                on_click=lambda e: self.page.run_task(self._create_invite),
            ),
        ])

        self._dialog = ft.AlertDialog(
            title=ft.Text("Invite People", color=FG),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Share an invite code to let others join this server.", color=FG_DIM, size=12),
                    create_row,
                    ft.Divider(color=DIVIDER),
                    self._invites_list,
                ], spacing=8, scroll=ft.ScrollMode.AUTO),
                width=400,
                height=350,
            ),
            bgcolor=BG_DARK,
            actions=[ft.TextButton("Close", on_click=lambda e: self._close(), tooltip="Close invite dialog")],
        )
        self.page.overlay.append(self._dialog)
        self._dialog.open = True
        self.page.update()
        self.page.run_task(self._load_invites)

    async def _load_invites(self):
        await self.client.send_invite_list(self._server_id)
        # Wait a moment for response, then refresh
        import asyncio
        await asyncio.sleep(0.5)
        self._refresh_invite_list()

    def _refresh_invite_list(self):
        if not self._invites_list:
            return
        self._invites_list.controls.clear()
        # Check for invites in client data
        invites = getattr(self.client, '_last_invites', [])
        if not invites:
            self._invites_list.controls.append(
                ft.Text("No active invites", color=FG_DIM, size=12)
            )
        else:
            for inv in invites:
                code = inv.get("code", "?")
                uses = inv.get("uses", 0)
                max_uses = inv.get("max_uses", 0)
                uses_str = f"{uses}/{max_uses}" if max_uses else f"{uses}/∞"
                self._invites_list.controls.append(ft.Container(
                    content=ft.Row([
                        ft.Column([
                            ft.Text(code, color=ACCENT, size=14, selectable=True),
                            ft.Text(f"Uses: {uses_str}", color=FG_DIM, size=11),
                        ], spacing=0, expand=True),
                        ft.IconButton(
                            icon=ft.Icons.COPY, icon_color=FG_DIM, icon_size=14,
                            tooltip="Copy code",
                            on_click=lambda e, c=code: self._copy_code(c),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE, icon_color="#f23f43", icon_size=14,
                            tooltip="Delete invite",
                            on_click=lambda e, inv_id=inv.get("id"): self.page.run_task(
                                self._delete_invite, inv_id,
                            ),
                        ),
                    ], spacing=4),
                    bgcolor=BG_DARKER,
                    border_radius=6,
                    padding=8,
                ))
        self.page.update()

    async def _create_invite(self):
        await self.client.send_invite_create(self._server_id)
        import asyncio
        await asyncio.sleep(0.5)
        self._refresh_invite_list()

    async def _delete_invite(self, invite_id):
        if invite_id:
            await self.client.send_invite_delete(invite_id, self._server_id)
            import asyncio
            await asyncio.sleep(0.3)
            self._refresh_invite_list()

    def _copy_code(self, code: str):
        self.page.set_clipboard(code)
        self.page.snack_bar = ft.SnackBar(
            ft.Text(f"Copied: {code}", color=FG), bgcolor="#43b581",
        )
        self.page.snack_bar.open = True
        self.page.update()

    def _close(self):
        if self._dialog:
            self._dialog.open = False
            self.page.update()
            try:
                self.page.overlay.remove(self._dialog)
            except ValueError:
                pass
