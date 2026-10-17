"""Member sidebar panel for Labhair-liom Flet GUI."""

from __future__ import annotations

import flet as ft
from typing import TYPE_CHECKING

from client.flet_app.theme import *

if TYPE_CHECKING:
    from client.main import ChatClient


class MemberPanel:
    """Right sidebar showing server members with status."""

    def __init__(self, page: ft.Page, client: ChatClient):
        self.page = page
        self.client = client
        self._members: list[dict] = []
        self._streaming: set[str] = set()  # user_ids currently streaming screen
        self.on_open_dm = None

    def build(self) -> ft.Container:
        """Build the member panel."""
        self._members_list = ft.ListView(
            spacing=2,
            expand=True,
        )

        header = ft.Container(
            content=ft.Text("MEMBERS", color=FG_DIM, size=12, weight=ft.FontWeight.BOLD),
            padding=ft.padding.only(left=12, top=8, bottom=4),
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    header,
                    self._members_list,
                ],
                spacing=0,
                expand=True,
            ),
            width=200,
            bgcolor=BG_DARK,
        )

    def set_members(self, members: list[dict], streaming: set[str] | dict | None = None):
        """Populate the member list grouped by role (like Discord).

        ``streaming`` is a set of user_ids (or a {uid: bool} map, e.g. from
        ``client.screen_active_peers``) whose members get a red LIVE dot.
        """
        self._members = members
        if streaming is None:
            self._streaming = set()
        elif isinstance(streaming, str):
            self._streaming = {streaming} if streaming else set()
        elif isinstance(streaming, dict):
            self._streaming = {str(k) for k, v in streaming.items() if v}
        else:
            self._streaming = {str(k) for k in streaming}

        online = [m for m in members if m.get("status", "offline") == "online"]
        offline = [m for m in members if m.get("status", "offline") != "online"]

        self._members_list.controls.clear()

        # Group online members by their highest role
        if online:
            self._members_list.controls.append(
                ft.Container(
                    content=ft.Text(f"ONLINE — {len(online)}", color=FG_DIM, size=11, weight=ft.FontWeight.BOLD),
                    padding=ft.padding.only(left=8, top=8, bottom=4),
                )
            )
            role_groups = self._group_by_role(online)
            for role_name, role_color, role_members in role_groups:
                # Role header
                color_hex = f"#{role_color:06x}" if role_color else FG_DIM
                self._members_list.controls.append(
                    ft.Container(
                        content=ft.Text(
                            f"{role_name.upper()} — {len(role_members)}",
                            color=color_hex, size=11, weight=ft.FontWeight.BOLD,
                        ),
                        padding=ft.padding.only(left=8, top=6, bottom=2),
                    )
                )
                for m in role_members:
                    self._members_list.controls.append(self._build_member(m))

        # Offline section (no role grouping)
        if offline:
            self._members_list.controls.append(
                ft.Container(
                    content=ft.Text(f"OFFLINE — {len(offline)}", color=FG_DIM, size=11, weight=ft.FontWeight.BOLD),
                    padding=ft.padding.only(left=8, top=8, bottom=4),
                )
            )
            for m in offline:
                self._members_list.controls.append(self._build_member(m, offline=True))

        self.page.update()

    def _group_by_role(self, members: list[dict]) -> list[tuple[str, int, list[dict]]]:
        """Group members by their highest-privilege role. Returns [(role_name, color, members)]."""
        # Collect all roles from all members
        role_map = {}  # role_id → (name, color, permissions, [members])
        unroleed = []
        for m in members:
            roles = m.get("roles", [])
            # Filter out @everyone (it has low permissions and is Everyone)
            assignable = [r for r in roles if r.get("permissions", 0) < 2147483647 and r.get("name", "") != "@everyone"]
            if assignable:
                # Pick highest privilege role
                best = max(assignable, key=lambda r: r.get("permissions", 0))
                rid = best.get("id", best.get("name", "?"))
                if rid not in role_map:
                    role_map[rid] = (best.get("name", "?"), best.get("color", 0), best.get("permissions", 0), [])
                role_map[rid][3].append(m)
            else:
                unroleed.append(m)
        # Sort groups by permission level (highest first), then build result
        result = []
        for rid, (name, color, perms, group) in sorted(role_map.items(), key=lambda x: -x[1][2]):
            result.append((name, color, group))
        if unroleed:
            result.append(("Member", 0, unroleed))
        return result

    def _build_member(self, member: dict, offline: bool = False) -> ft.Container:
        """Build a single member item."""
        username = member.get("username", "Unknown")
        status = member.get("status", "online")
        roles = member.get("roles", [])
        user_id = member.get("id", username)

        # Status dot color
        status_colors = {
            "online": STATUS_ONLINE,
            "idle": STATUS_IDLE,
            "dnd": STATUS_DND,
            "offline": STATUS_INVISIBLE,
            "invisible": STATUS_INVISIBLE,
        }
        dot_color = status_colors.get(status, STATUS_ONLINE)

        # Username color from highest role or default
        role_color = None
        if roles:
            best = max(roles, key=lambda r: r.get("permissions", 0))
            c = best.get("color", 0)
            if c:
                role_color = f"#{c:06x}"
        if not role_color:
            role_color = FG_DIM if offline else FG

        # Status dot
        status_dot = ft.Container(
            width=8,
            height=8,
            border_radius=4,
            bgcolor=dot_color,
            margin=ft.margin.only(right=4),
        )

        # Avatar placeholder (first letter)
        avatar = ft.Container(
            content=ft.Text(
                username[0].upper(),
                color=FG,
                size=12,
                weight=ft.FontWeight.BOLD,
            ),
            width=28,
            height=28,
            border_radius=14,
            bgcolor=BG_INPUT,
            alignment=ft.alignment.center,
        )

        # Red LIVE dot when this member is streaming their screen
        streaming = str(user_id) in self._streaming and not offline
        streaming_dot = None
        if streaming:
            streaming_dot = ft.Container(
                content=ft.Text("●", color="#f23f43", size=10),
                tooltip=f"{username} is streaming their screen",
                margin=ft.margin.only(left=2),
            )

        return ft.Container(
            content=ft.Row([
                ft.Stack([
                    avatar,
                    ft.Container(
                        content=status_dot,
                        alignment=ft.alignment.bottom_right,
                        margin=ft.margin.only(bottom=-2, right=-2),
                    ),
                ]),
                ft.Text(
                    username,
                    color=role_color,
                    size=13,
                    opacity=0.5 if offline else 1.0,
                    expand=True,
                ),
            ] + ([streaming_dot] if streaming_dot else []), spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.padding.symmetric(horizontal=8, vertical=4),
            border_radius=6,
            on_hover=self._on_hover,
            on_click=lambda e, uid=user_id: self._on_member_click(uid),
        )

    def _on_hover(self, e):
        """Hover effect on member items."""
        e.control.bgcolor = BG_HOVER if e.data == "true" else None
        e.control.update()

    def _on_member_click(self, user_id: str):
        """Show profile dialog with option to send DM."""
        # Find member data
        member_data = None
        for m in self._members:
            if str(m.get("id", "")) == str(user_id):
                member_data = m
                break

        display = member_data.get("display_name", member_data.get("username", "Unknown")) if member_data else "Unknown"
        username = member_data.get("username", "") if member_data else ""
        status = member_data.get("status", "offline") if member_data else "offline"
        bio = member_data.get("bio", "") if member_data else ""
        custom_status = member_data.get("custom_status", "") if member_data else ""
        roles = member_data.get("roles", []) if member_data else []
        avatar = member_data.get("avatar_url", "") if member_data else ""

        status_icons = {"online": "🟢", "idle": "🟡", "dnd": "🔴"}
        status_text = status_icons.get(status, "⚫")

        header = ft.Row([
            ft.Text(f"{status_text} {display}", color=FG, size=16, weight=ft.FontWeight.BOLD),
        ], spacing=8)

        fields = []
        if username:
            fields.append(ft.Row([
                ft.Text("Username:", color=FG_DIM, size=12),
                ft.Text(username, color=FG, size=12),
            ], spacing=8))
        if custom_status:
            fields.append(ft.Row([
                ft.Text("Status:", color=FG_DIM, size=12),
                ft.Text(custom_status, color=FG, size=12),
            ], spacing=8))
        else:
            fields.append(ft.Row([
                ft.Text("Status:", color=FG_DIM, size=12),
                ft.Text(f"{status_text} {status}", color=FG, size=12),
            ], spacing=8))
        if bio:
            fields.append(ft.Divider(height=1, color=DIVIDER))
            fields.append(ft.Text("About Me", color=FG, size=12, weight=ft.FontWeight.BOLD))
            fields.append(ft.Text(bio, color=FG, size=12, selectable=True))
        if roles:
            role_strs = []
            for r in roles:
                rname = r.get("name", "?")
                rcolor = r.get("color", 0)
                if rcolor:
                    role_strs.append(ft.Text(rname, color=f"#{rcolor:06x}", size=11))
                else:
                    role_strs.append(ft.Text(rname, color=FG_DIM, size=11))
            if role_strs:
                fields.append(ft.Divider(height=1, color=DIVIDER))
                fields.append(ft.Text("Roles", color=FG, size=12, weight=ft.FontWeight.BOLD))
                fields.append(ft.Row(role_strs, spacing=6, wrap=True))

        async def on_dm(e):
            if self.on_open_dm:
                self.on_open_dm(user_id)
            self._close_dialog(dialog)

        dialog = ft.AlertDialog(
            title=header,
            content=ft.Column(fields, spacing=6),
            actions=[
                ft.TextButton("Send DM", on_click=on_dm, tooltip="Send direct message"),
                ft.TextButton("Close", on_click=lambda e: self._close_dialog(dialog), tooltip="Close"),
            ],
            bgcolor=BG_DARK,
        )
        self.page.overlay.append(dialog)
        dialog.open = True
        self.page.update()

    def _close_dialog(self, dialog):
        dialog.open = False
        self.page.overlay.remove(dialog)
        self.page.update()
