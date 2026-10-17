"""Entry point for the Android build — imports and runs the Kivy app."""
import sys
import os

def _write_error(msg: str) -> None:
    for p in (
        "/sdcard/Download/labhairliom_crash.txt",
        os.path.join(os.path.expanduser("~"), "labhairliom_crash.txt"),
    ):
        try:
            with open(p, "w") as f:
                f.write(msg)
            break
        except Exception:
            continue

try:
    from client.android_app.main import LabhairLiomApp
    LabhairLiomApp().run()
except Exception as exc:
    import traceback
    msg = f"CRASH: {exc}\n{traceback.format_exc()}"
    _write_error(msg)
    print(msg, file=sys.stderr)
