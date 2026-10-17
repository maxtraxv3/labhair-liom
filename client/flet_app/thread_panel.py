"""Thread sidebar panel for Labhair-liom Flet GUI."""

from __future__ import annotations

import flet as ft
from typing import TYPE_CHECKING

from client.flet_app.theme import *

if TYPE_CHECKING:
    from client.main import ChatClient


class ThreadPanel:
    """Sidebar showing threads in the current channel."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client
        self._threads: list[dict] = []
        self._visible = False

    def build(self) -> ft.Container:
        """Build the thread panel."""
        self._thread_list = ft.ListView(spacing=2, expand=True)

        header = ft.Container(
            content=ft.Row([
                ft.Text("THREADS", color=FG_DIM, size=12, weight=ft.FontWeight.BOLD, expand=True),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_color=FG_DIM,
                    icon_size=14,
                    tooltip="Close threads panel",
                    on_click=self._toggle,
                ),
            ]),
            padding=ft.padding.only(left=8, top=8, bottom=4),
        )

        new_thread_btn = ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.ADD, color=ACCENT, size=16),
                ft.Text("New Thread", color=ACCENT, size=13),
            ], spacing=6),
            padding=ft.padding.symmetric(horizontal=8, vertical=6),
            border_radius=6,
            on_click=self._create_thread,
            on_hover=self._on_hover,
        )

        self._panel = ft.Container(
            content=ft.Column([
                header,
                new_thread_btn,
                ft.Divider(height=1, color=DIVIDER),
                self._thread_list,
            ], spacing=0, expand=True),
            width=220,
            bgcolor=BG_DARK,
            visible=False,
        )

        return self._panel

    def _toggle(self, e=None):
        """Toggle panel visibility."""
        self._visible = not self._visible
        self._panel.visible = self._visible
        self.page.update()

    def show(self):
        self._visible = True
        self._panel.visible = True
        self.page.update()

    def hide(self):
        self._visible = False
        self._panel.visible = False
        self.page.update()

    def set_threads(self, threads: list[dict]):
        """Populate the thread list."""
        self._threads = threads
        self._thread_list.controls.clear()

        for thread in threads:
            name = thread.get("name", "Thread")
            thread_id = thread.get("id", "")
            creator = thread.get("creator", "Unknown")
            msg_count = thread.get("message_count", 0)

            item = ft.Container(
                content=ft.Column([
                    ft.Text(name, color=FG, size=13, weight=ft.FontWeight.BOLD),
                    ft.Row([
                        ft.Text(f"by {creator}", color=FG_DIM, size=11),
                        ft.Text(f"• {msg_count} msgs", color=FG_MUTED, size=11),
                    ], spacing=4),
                ], spacing=2),
                padding=ft.padding.symmetric(horizontal=8, vertical=6),
                border_radius=6,
                on_click=lambda e, tid=thread_id: self._on_thread_click(tid),
                on_hover=self._on_hover,
                data=thread_id,
            )
            self._thread_list.controls.append(item)

        self.page.update()

    def _on_thread_click(self, thread_id: str):
        """Join a thread."""
        self.page.run_task(self.client.send_thread_join, thread_id)

    def _create_thread(self, e):
        """Show create thread dialog."""
        name_field = ft.TextField(
            hint_text="Thread name",
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
                channel_id = self.client.current_channel_id or 0
                await self.client.send_thread_create(channel_id, name)
                dialog.open = False
                self.page.update()

        dialog = ft.AlertDialog(
            title=ft.Text("Create Thread", color=FG),
            content=ft.Container(
                content=ft.Column([
                    ft.Text("Give your thread a name.", color=FG_DIM),
                    name_field,
                ], spacing=10),
                width=350,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: self._close(dialog), tooltip="Discard"),
                ft.ElevatedButton("Create", on_click=on_create, bgcolor=ACCENT, color=FG, tooltip="Create new thread"),
            ],
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _close(self, dialog: ft.AlertDialog):
        dialog.open = False
        self.page.update()

    def _on_hover(self, e):
        e.control.bgcolor = BG_HOVER if e.data == "true" else None
        e.control.update()
