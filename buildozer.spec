[app]

# ── Basic info ──────────────────────────────────────────────────────
title = Labhair-liom
package.name = labhairliom
package.domain = org.labhairliom
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,java
source.include_patterns = shared/*,client/*
source.exclude_dirs = server,tests,bin,.buildozer,.git,.venv,node_modules
source.exclude_patterns = -,*-*,*.mkv,*.mp4,*.avi,*.mov,*.webm,*.iso,*.img

# ── Version ─────────────────────────────────────────────────────────
version = 0.5.0

# Entry point: main.py at project root

# ── Requirements ────────────────────────────────────────────────────
# No opencv — Android doesn't need it (camera uses pyjnius Camera1 API,
# screen uses MediaProjection). numpy is needed for ADPCM voice codec.
# aiosqlite is bundled with the source.
requirements =
    python3,
    kivy,
    pillow,
    numpy,
    pyjnius,
    plyer,
    openssl,
    cryptography

# ── Android-specific ────────────────────────────────────────────────
android.permissions =
    INTERNET,
    RECORD_AUDIO,
    CAMERA,
    MANAGE_EXTERNAL_STORAGE,
    FOREGROUND_SERVICE,
    FOREGROUND_SERVICE_MICROPHONE,
    FOREGROUND_SERVICE_MEDIA_PROJECTION,
    POST_NOTIFICATIONS,
    ACCESS_NETWORK_STATE

android.api = 35
android.minapi = 24
android.ndk = 26b
android.sdk = 35
android.accept_sdk_license = True
# Ship only the physical-device architecture.  The release workflow verifies
# the generated manifest rather than adding x86_64 solely for CI emulation.
android.archs = arm64-v8a

# Use fullscreen with action bar
android.fullscreen = 1
android.orientation = portrait

# Custom Java source — Gradle compiles src/org/labhairliom/*.java into the APK.
# This provides MediaProjectionService, a foreground service required for
# screen capture on Android 14+. Must run in main process (not :python_service).
android.add_src = src
# Register the custom Java foreground service.  Adding its source above only
# compiles the class; Android will not allow it to start unless it is present
# in the application manifest.
android.extra_manifest_application_arguments = src/android/manifest_application.xml

# ── Presplash ───────────────────────────────────────────────────────
# presplash.filename = %(source.dir)s/assets/presplash.png
# icon.filename = %(source.dir)s/assets/icon.png

# ── Build ───────────────────────────────────────────────────────────
# log_level = 2
# warn_on_root = 1

# ── P4A (python-for-android) recipes ───────────────────────────────
# Pin the Android packager for reproducible release APKs.  Update this
# deliberately, together with a device/emulator test, rather than tracking
# the moving development branch.
p4a.branch = v2026.05.09
