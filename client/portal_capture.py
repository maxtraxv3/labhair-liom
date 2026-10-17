#!/usr/bin/env python3
"""xdg-desktop-portal ScreenCast → PipeWire fd → gst-launch raw BGR frames to stdout.

Uses the same D-Bus API as Discord and OBS (org.freedesktop.portal.ScreenCast),
so it works on Wayland (including KDE/kwin) where legacy grabbers return black
frames or silently produce nothing.

This script must run under a Python that has ``dbus`` and ``gi`` available
(system Python usually does; the app's venv often does not). It is spawned as a
subprocess by ``client.screencap._PersistentPortal``.

Protocol:
  * On startup it pops the portal's screen selector (like Discord/OBS).
  * Once the user picks a screen it prints a line::

        READY <width> <height>

    and then streams raw BGR24 frames (width*height*3 bytes each, one after
    another) to *stdout*. Stderr carries gst-launch errors for debugging.

  * The session closes when this process is terminated (SIGTERM/SIGINT) or when
    the user closes the portal picker.
"""

import os
import signal
import subprocess
import sys


def _fail(msg: str) -> None:
    # Echo to stderr (captured by the parent) AND stdout so the parent's first
    # readline() can tell a real failure from a silent exit.
    print(f"ERROR: {msg}", flush=True)
    print(f"ERROR: {msg}", file=sys.stderr, flush=True)
    os._exit(1)


def main() -> None:
    try:
        import dbus
        import dbus.mainloop.glib
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import GLib
    except Exception as exc:  # pragma: no cover - environment dependent
        _fail(f"portal capture needs dbus + gi: {exc}")

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    proxy = bus.get_object(
        "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop"
    )
    iface = dbus.Interface(proxy, "org.freedesktop.portal.ScreenCast")
    loop = GLib.MainLoop()

    session_path = None
    gst_proc = None
    started = False

    def cleanup() -> None:
        nonlocal gst_proc
        if gst_proc is not None and gst_proc.poll() is None:
            try:
                gst_proc.terminate()
                gst_proc.wait(timeout=5)
            except Exception:
                pass
        if session_path:
            try:
                s_iface = dbus.Interface(
                    bus.get_object("org.freedesktop.portal.Desktop", session_path),
                    "org.freedesktop.portal.Session",
                )
                s_iface.Close()
            except Exception:
                pass
        try:
            loop.quit()
        except Exception:
            pass

    def on_start_response(response, result):
        nonlocal gst_proc, started
        if response != 0:
            if response == 1:
                _fail("screen picker was closed or cancelled")
            else:
                _fail(f"screen capture failed (portal response {response})")
            return
        try:
            streams = result.get("streams", [])
            if not streams:
                _fail("no streams available")

            # Surface the portal's stream info for debugging (it later shows up
            # in the parent's portal/gst stderr dump).
            try:
                print(f"PORTAL_STREAMS: {list(streams)}", file=sys.stderr, flush=True)
            except Exception:
                pass

            # The Start() response carries the PipeWire node id of the screen
            # stream. pipewiresrc's plain `fd` + autoconnect fails to find the
            # session node ("stream error: target not found"), so we pin it via
            # path=<node_id> - the canonical portal recipe (GNOME's own
            # xdp-screen-cast.py uses 'pipewiresrc fd=%d path=%u').
            node_id = None
            try:
                first = streams[0]
                if isinstance(first, dict):
                    # Older portal schema: plain dict with node_id (or numeric path).
                    raw = first.get("node_id")
                    if raw is None:
                        maybe = first.get("path")
                        if maybe is not None and str(maybe).strip().isdigit():
                            raw = maybe
                    if raw is not None:
                        node_id = int(raw)
                else:
                    # Newer portal schema: each stream is a struct of the form
                    # (u node_id, a{sv} properties) - the node id is element 0.
                    node_id = int(first[0])
            except Exception:
                node_id = None
            if node_id is not None:
                print(f"PORTAL_NODE_ID: {node_id}", file=sys.stderr, flush=True)
            else:
                print(
                    "PORTAL_NODE_ID: none found in first stream "
                    "(keys below; portal may omit node_id)",
                    file=sys.stderr, flush=True,
                )

            session_obj = bus.get_object(
                "org.freedesktop.portal.Desktop", session_path
            )
            session_iface = dbus.Interface(
                session_obj, "org.freedesktop.portal.Session"
            )
            # Since xdg-desktop-portal 1.18/1.20 OpenPipeWireRemote lives on the
            # ScreenCast interface of the *main* portal object and takes the
            # session handle as its first argument; older portals (1.10-1.17)
            # export it on the Session interface of the session object with just
            # an options dict. Try the current form first, fall back to the old.
            try:
                fd_obj = iface.OpenPipeWireRemote(
                    session_path, dbus.Dictionary({}, signature="sv")
                )
            except Exception as exc1:
                try:
                    fd_obj = session_iface.OpenPipeWireRemote(
                        dbus.Dictionary({}, signature="sv")
                    )
                except Exception as exc2:
                    _fail(f"OpenPipeWireRemote failed: {exc1} (and {exc2})")
            # dbus-python returns an h (Unix fd) as a dbus.UnixFd object; take()
            # hands over the underlying integer fd and invalidates the wrapper.
            pw_fd = fd_obj.take()

            try:
                scale_w = int(os.environ.get("LABHAIR_LIOM_PORTAL_WIDTH", "640"))
                scale_h = int(os.environ.get("LABHAIR_LIOM_PORTAL_HEIGHT", "360"))
            except ValueError:
                scale_w, scale_h = 640, 360

            # Ensure the PipeWire fd survives into gst-launch. subprocess.Popen
            # with close_fds=True closes everything except pass_fds, so the fd
            # MUST be listed there (set_inheritable alone is not enough).
            try:
                os.set_inheritable(pw_fd, True)
            except Exception:
                pass
            gst_cmd = [
                "gst-launch-1.0", "-e",
                # IMPORTANT: pipewiresrc and its fd MUST be separate argv tokens.
                # gst-launch-1.0 parses each argv element as a pipeline token; a
                # single "pipewiresrc fd=N" element containing a space fails with
                # "WARNING: erroneous pipeline: syntax error" (verified locally).
                "pipewiresrc", f"fd={pw_fd}",
            ]
            if node_id is not None:
                # Pin the portal screen-stream node. The canonical portal recipe
                # (GNOME xdp-screen-cast.py: 'pipewiresrc fd=%d path=%u') uses
                # path=<node_id>: the pipewire gst plugin parses it as the
                # pw_stream_connect target id (direct bind). No space in token.
                gst_cmd.append(f"path={node_id}")
            gst_cmd += [
                "!", "video/x-raw",
                "!", "videoconvert",
                "!", "video/x-raw,format=BGR",
                "!", "videoscale",
                "!", f"video/x-raw,width={scale_w},height={scale_h}",
                "!", "fdsink", "fd=1",
            ]
            try:
                print(f"GST_CMD: {' '.join(gst_cmd)}", file=sys.stderr, flush=True)
            except Exception:
                pass
            # Inherit our stdout so the parent process reads raw frames directly.
            gst_proc = subprocess.Popen(
                gst_cmd, stdout=sys.stdout.buffer, stderr=sys.stderr, pass_fds=[pw_fd]
            )
        except Exception as exc:
            _fail(f"gst-launch start failed: {exc}")
        print(f"READY {scale_w} {scale_h}", flush=True)
        started = True

    def on_select_response(response, result):
        if response != 0:
            if response == 1:
                _fail("screen source picker was closed or cancelled")
            else:
                _fail(f"source selection failed (portal response {response})")
            return
        start = iface.Start(session_path, "screen_share", {"handle_token": "start1"})
        req = dbus.Interface(
            bus.get_object("org.freedesktop.portal.Desktop", start),
            "org.freedesktop.portal.Request",
        )
        req.connect_to_signal("Response", on_start_response)

    def on_create_response(response, result):
        nonlocal session_path
        if response != 0:
            if response == 1:
                _fail("session creation cancelled (portal unavailable?)")
            else:
                _fail(f"session creation failed (portal response {response})")
            return
        session_path = result["session_handle"]
        sel = iface.SelectSources(
            session_path,
            {
                "handle_token": "src_select",
                "types": dbus.UInt32(1),  # 1 = monitor
                "cursor_mode": dbus.UInt32(2),
            },
        )
        req = dbus.Interface(
            bus.get_object("org.freedesktop.portal.Desktop", sel),
            "org.freedesktop.portal.Request",
        )
        req.connect_to_signal("Response", on_select_response)

    def watch_gst():
        if started and gst_proc is not None and gst_proc.poll() is not None:
            cleanup()
            return False
        return True

    GLib.timeout_add(500, watch_gst)
    signal.signal(signal.SIGTERM, lambda *a: cleanup())
    signal.signal(signal.SIGINT, lambda *a: cleanup())

    session = iface.CreateSession(
        {"handle_token": "create1", "session_handle_token": "sess1"}
    )
    req = dbus.Interface(
        bus.get_object("org.freedesktop.portal.Desktop", session),
        "org.freedesktop.portal.Request",
    )
    req.connect_to_signal("Response", on_create_response)

    loop.run()
    os._exit(0)


if __name__ == "__main__":
    main()