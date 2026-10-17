"""Connection/authentication page for Labhair-liom Flet GUI."""

from __future__ import annotations

import asyncio
import flet as ft
from typing import Callable

from client.flet_app.theme import *
from shared.settings import Settings


class ConnectPage:
    """Auth dialog with Sign In and Register modes."""

    def __init__(self, page: ft.Page, client, on_connected: Callable):
        self.page = page
        self.client = client
        self.on_connected = on_connected
        self._mode = "signin"  # signin, register
        self._settings = Settings()

    def build(self) -> ft.Container:
        title = ft.Text(
            "Labhair-liom",
            size=32,
            weight=ft.FontWeight.BOLD,
            color=FG,
            text_align=ft.TextAlign.CENTER,
        )

        subtitle = ft.Text(
            "End-to-end encrypted chat",
            size=14,
            color=FG_DIM,
            text_align=ft.TextAlign.CENTER,
        )

        # Pre-fill from last connection
        saved_host = self._settings.last_host
        saved_port = self._settings.last_port
        saved_user = self._settings.last_username
        host_value = f"{saved_host}:{saved_port}" if saved_host and saved_port else ""

        self._host_field = ft.TextField(
            label="Server",
            value=host_value,
            hint_text="192.168.1.100:9473 or .onion address",
            bgcolor=BG_INPUT,
            color=FG,
            border_color=DIVIDER,
            border_radius=8,
            content_padding=12,
            text_size=14,
            autofocus=True,
        )

        self._mode_tabs = ft.Tabs(
            selected_index=0,
            tabs=[
                ft.Tab(text="Sign In"),
                ft.Tab(text="Register"),
            ],
            on_change=self._on_mode_change,
            label_color=FG,
            unselected_label_color=FG_DIM,
            indicator_color=ACCENT,
            divider_color=DIVIDER,
            overlay_color=ft.Colors.with_opacity(0.1, ACCENT),
        )

        self._signin_fields = ft.Column([
            ft.TextField(
                label="Username",
                value=saved_user,
                bgcolor=BG_INPUT,
                color=FG,
                border_color=DIVIDER,
                border_radius=8,
                content_padding=12,
                text_size=14,
            ),
            ft.TextField(
                label="Password",
                password=True,
                can_reveal_password=True,
                bgcolor=BG_INPUT,
                color=FG,
                border_color=DIVIDER,
                border_radius=8,
                content_padding=12,
                text_size=14,
            ),
        ], spacing=10)

        self._register_fields = ft.Column([
            ft.TextField(
                label="Username",
                value=saved_user,
                hint_text="Letters, numbers, - and _",
                bgcolor=BG_INPUT,
                color=FG,
                border_color=DIVIDER,
                border_radius=8,
                content_padding=12,
                text_size=14,
            ),
            ft.TextField(
                label="Email",
                bgcolor=BG_INPUT,
                color=FG,
                border_color=DIVIDER,
                border_radius=8,
                content_padding=12,
                text_size=14,
            ),
            ft.TextField(
                label="Password",
                password=True,
                can_reveal_password=True,
                bgcolor=BG_INPUT,
                color=FG,
                border_color=DIVIDER,
                border_radius=8,
                content_padding=12,
                text_size=14,
            ),
            ft.Text(
                "Min 8 chars, 1 uppercase, 1 lowercase, 1 digit",
                color=FG_DIM,
                size=11,
            ),
            ft.TextField(
                label="Confirm Password",
                password=True,
                can_reveal_password=True,
                bgcolor=BG_INPUT,
                color=FG,
                border_color=DIVIDER,
                border_radius=8,
                content_padding=12,
                text_size=14,
            ),
        ], spacing=10)

        self._fields_container = ft.Container(
            content=self._signin_fields,
            padding=ft.padding.only(top=10),
        )

        self._connect_btn = ft.ElevatedButton(
            text="Sign In",
            bgcolor=ACCENT,
            color=FG,
            tooltip="Connect to server",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
                padding=14,
            ),
            expand=True,
            on_click=self._on_connect,
        )

        self._error_text = ft.Text(
            "",
            color="#f23f43",
            size=12,
            text_align=ft.TextAlign.CENTER,
        )

        self._status_text = ft.Text(
            "",
            color=FG_SYS,
            size=12,
            text_align=ft.TextAlign.CENTER,
        )

        card = ft.Container(
            content=ft.Column([
                title,
                subtitle,
                ft.Divider(height=1, color=DIVIDER),
                self._host_field,
                self._mode_tabs,
                self._fields_container,
                self._error_text,
                self._status_text,
                self._connect_btn,
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            width=400,
            padding=30,
            border_radius=12,
            bgcolor=BG_DARK,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=20,
                color=ft.Colors.with_opacity(0.3, "#000000"),
                offset=ft.Offset(0, 4),
            ),
        )

        return ft.Container(
            content=card,
            expand=True,
            alignment=ft.alignment.center,
            bgcolor=BG,
        )

    def _on_mode_change(self, e):
        index = self._mode_tabs.selected_index
        modes = ["signin", "register"]
        self._mode = modes[index]

        fields = {
            "signin": self._signin_fields,
            "register": self._register_fields,
        }
        buttons = {
            "signin": "Sign In",
            "register": "Create Account",
        }

        self._fields_container.content = fields[self._mode]
        self._connect_btn.text = buttons[self._mode]
        self._error_text.value = ""
        self.page.update()

    def _on_auth_error(self, body: dict):
        """Called when server rejects login/register."""
        error = body.get("error", "Authentication failed")
        self._error_text.value = error
        self._status_text.value = ""
        self._connect_btn.disabled = False
        # Stop the client so next connect is clean
        if self.client._stop:
            self.client._stop.set()
        self.page.update()

    def _on_connect(self, e):
        host = self._host_field.value.strip()
        if not host:
            self._error_text.value = "Please enter a server address"
            self.page.update()
            return

        self._status_text.value = "Connecting..."
        self._error_text.value = ""
        self._connect_btn.disabled = True
        self.page.update()

        self.page.run_task(self._do_connect, host)

    async def _do_connect(self, host: str):
        try:
            if ":" in host:
                host_part, port_str = host.rsplit(":", 1)
                port = int(port_str)
            else:
                host_part = host
                port = 9473

            self.client.host = host_part
            self.client.port = port
            self.client.room = "lobby"

            if self._mode == "signin":
                username = self._signin_fields.controls[0].value.strip()
                password = self._signin_fields.controls[1].value
                if not username or not password:
                    self._error_text.value = "Username and password required"
                    self._connect_btn.disabled = False
                    self._status_text.value = ""
                    self.page.update()
                    return

                self.client.user_id = username
                self.client.display = username
                self.client._pending_auth = ("login", username, "", password)

            elif self._mode == "register":
                username = self._register_fields.controls[0].value.strip()
                email = self._register_fields.controls[1].value.strip()
                password = self._register_fields.controls[2].value
                confirm = self._register_fields.controls[4].value
                if not username or not password:
                    self._error_text.value = "Username and password required"
                    self._connect_btn.disabled = False
                    self._status_text.value = ""
                    self.page.update()
                    return
                if password != confirm:
                    self._error_text.value = "Passwords do not match"
                    self._connect_btn.disabled = False
                    self._status_text.value = ""
                    self.page.update()
                    return

                self.client.user_id = username
                self.client.display = username
                self.client._pending_auth = ("register", username, email, password)

            # Wire auth callbacks BEFORE starting client
            self.client.on_auth_error = self._on_auth_error

            def _on_auth_ok(body):
                self.client.on_auth_error = None
                # Remember the last connection
                self._settings.last_host = self.client.host
                self._settings.last_port = self.client.port
                username = (self._signin_fields.controls[0].value
                            if self._mode == "signin"
                            else self._register_fields.controls[0].value)
                self._settings.last_username = username.strip() if username else ""
                self._settings.save()
                self.on_connected()

            self.client.on_auth_success = _on_auth_ok

            # Reset stop event so client.run() can start fresh
            self.client._stop = asyncio.Event()

            self.page.run_task(self.client.run)

        except Exception as ex:
            self._error_text.value = f"Connection failed: {ex}"
            self._connect_btn.disabled = False
            self._status_text.value = ""
            self.page.update()
