"""Foreground service support for Labhair-liom Android client.

Two modes:
1. start_foreground_service() — lightweight notification via NotificationManager
   (used for general background keep-alive)

2. start_media_projection_fg() — starts PythonService as a real Android foreground
   service with FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION, required for
   MediaProjection screen capture on Android 14+ (API 34+).
"""

from __future__ import annotations

import time

try:
    from jnius import autoclass
    _ANDROID = True
except ImportError:
    _ANDROID = False

_CHANNEL_ID = "labhairliom_bg"
_CHANNEL_NAME = "Labhair-liom Chat"
_NOTIFICATION_ID = 9473

# android.content.ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION
_FG_TYPE_MEDIA_PROJECTION = 0x00000400


def _get_activity():
    if not _ANDROID:
        return None
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    return PythonActivity.mActivity


def _build_notification(context, title: str, text: str):
    """Build a persistent notification."""
    NotificationChannel = autoclass("android.app.NotificationChannel")
    NotificationManager = autoclass("android.app.NotificationManager")
    NotificationBuilder = autoclass("android.app.Notification$Builder")

    nm = context.getSystemService("notification")
    channel = NotificationChannel(
        _CHANNEL_ID, _CHANNEL_NAME,
        NotificationManager.IMPORTANCE_LOW,
    )
    nm.createNotificationChannel(channel)

    builder = NotificationBuilder(context, _CHANNEL_ID)
    builder.setContentTitle(title)
    builder.setContentText(text)
    icon_res = int("0x0108009a", 16)
    builder.setSmallIcon(icon_res)
    builder.setOngoing(True)
    return builder.build()


# ── Light notification (no real foreground service) ──────────────────

def start_foreground_service(title: str = "Labhair-liom Chat",
                             text: str = "Connected") -> bool:
    """Show a persistent notification (no real foreground service)."""
    if not _ANDROID:
        return False
    try:
        activity = _get_activity()
        if activity is None:
            return False

        notification = _build_notification(activity, title, text)
        NotificationManager = autoclass("android.app.NotificationManager")
        nm = activity.getSystemService("notification")
        nm.notify(_NOTIFICATION_ID, notification)
        print("[fg-service] notification started", flush=True)
        return True
    except Exception as exc:
        print(f"[fg-service] failed: {exc}", flush=True)
        return False


def stop_foreground_service() -> None:
    if not _ANDROID:
        return
    try:
        activity = _get_activity()
        if activity is None:
            return
        NotificationManager = autoclass("android.app.NotificationManager")
        nm = activity.getSystemService("notification")
        if nm is not None:
            nm.cancel(_NOTIFICATION_ID)
        print("[fg-service] stopped", flush=True)
    except Exception as exc:
        print(f"[fg-service] stop failed: {exc}", flush=True)


def update_foreground_text(text: str) -> None:
    if not _ANDROID:
        return
    try:
        activity = _get_activity()
        if activity is None:
            return
        notification = _build_notification(activity, "Labhair-liom Chat", text)
        NotificationManager = autoclass("android.app.NotificationManager")
        nm = activity.getSystemService("notification")
        nm.notify(_NOTIFICATION_ID, notification)
    except Exception:
        pass


# ── Real foreground service for MediaProjection (Android 14+) ───────

_SERVICE_CLS = "org.labhairliom.MediaProjectionService"


def start_media_projection_fg() -> bool:
    """Start MediaProjectionService as a foreground service.

    Required for MediaProjection screen capture on Android 14+ (API 34+).
    This service runs in the **main process** (no android:process in manifest)
    and calls startForeground() with FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION.
    p4a's PythonService cannot be used because it runs in ":python_service"
    (separate process), which causes SecurityException on Android 14+.

    The Java class is compiled into the APK via android.add_src = src in
    buildozer.spec, and declared in the manifest via the template.
    """
    def _log(msg):
        import os
        for p in ("/sdcard/Download/labhairliom_crash.txt",
                  os.path.join(os.path.expanduser("~"), "labhairliom_crash.txt")):
            try:
                with open(p, "a") as f:
                    f.write(msg + "\n")
                break
            except Exception:
                continue
        print(msg, flush=True)

    _log("[fg-service] start_media_projection_fg called")

    if not _ANDROID:
        _log("[fg-service] _ANDROID is False — jnius not importable at module level")
        return False
    try:
        activity = _get_activity()
        if activity is None:
            _log("[fg-service] activity is None")
            return False

        # Use Intent.setClassName() with strings instead of autoclass().
        # pyjnius's classloader may not include the APK's dex, but
        # Android's system classloader (used by Intent) can resolve the class.
        Intent = autoclass("android.content.Intent")
        intent = Intent()
        intent.setClassName(activity.getPackageName(), _SERVICE_CLS)
        _log(f"[fg-service] intent set to {_SERVICE_CLS}")

        try:
            activity.startForegroundService(intent)
            _log("[fg-service] startForegroundService called successfully")
        except Exception as exc:
            _log(f"[fg-service] startForegroundService failed: {exc}")
            _log("[fg-service] trying startService fallback")
            activity.startService(intent)
            _log("[fg-service] startService called (fallback)")
        return True
    except Exception as exc:
        import traceback
        _log(f"[fg-service] media projection start failed: {exc}")
        _log(traceback.format_exc())
        return False


def start():
    """Legacy entry point — no longer needed (Java service handles foreground)."""
    pass
