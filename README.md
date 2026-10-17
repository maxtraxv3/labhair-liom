# Labhair-liom

End-to-end encrypted chat with Discord-like features.

- **E2E encrypted** — X25519 key exchange + ChaCha20-Poly1305 session encryption
- **Servers & channels** — persistent Discord-like server/channel system with roles and permissions
- **Invite-only servers** — all servers require an invite code to join (max 5 servers per user)
- **Flet GUI** — modern Discord-like desktop UI (Flutter-based, dark theme)
- **tkinter GUI** — legacy Discord-like interface (still available via `--gui`)
- **Voice channels** — per-channel voice chat with member tracking
- **Noise filtering** — mic noise gate and noise suppression options
- **Camera & screen share** — webcam + desktop capture with JPEG viewer
- **ADPCM voice** — IMA/DVI ADPCM @ 8 kHz (free, public-domain, ultra-low CPU)
- **Image sharing** — send images with inline preview (encrypted channel attachments)
- **File sharing** — send any file with per-channel AES-256-GCM encryption
- **Direct messages** — private conversations with friends
- **Friend system** — add friends, accept/decline requests, see online status
- **Member management** — kick/ban users with role-based permissions
- **User avatars & server icons** — upload images for profiles and servers
- **Message search** — search across servers/channels with user/channel filters
- **Threads** — threaded conversations within channels
- **Reactions & editing** — add reactions, edit/delete messages
- **Android** — Kivy mobile client with Camera1 + MediaProjection + mic/speaker
- **Tor support** — route through Tor hidden services for anonymous relay hosting
- **Windows** — standalone `.exe` builds for Windows 10/11

The relay is **untrusted**: it only routes opaque ciphertext between room members.

## Quick start

```bash
cd ~/Projects/Labhair-liom
python3 -m venv .venv
source .venv/bin/activate   # or: .venv/bin/activate.fish
pip install -r requirements.txt

# Terminal 1 — relay
python server/relay.py --port 9473

# Terminal 2 — Alice (Flet GUI)
python client/gui_flet.py --user alice --port 9473

# Terminal 3 — Bob (Flet GUI)
python client/gui_flet.py --user bob --port 9473
```

### Terminal mode

```bash
# Terminal 1 — relay
python server/relay.py --port 9473

# Terminal 2 — Alice (camera + screen share + viewer)
python client/main.py --user alice --room demo --voice --video --screen --viewer

# Terminal 3 — Bob
python client/main.py --user bob --room demo --voice --video
```

### Authentication

The GUI provides a connection dialog with three modes:
- **Sign In** — enter username + password
- **Register** — create a new account (username, email, password with strength requirements)
- **Legacy** — connect without an account (room + display name only)

Terminal mode supports authentication via commands:

| Command | Action |
|---------|--------|
| `/register <username> <password> [email]` | Create a new account |
| `/login <username> <password>` | Sign in to an existing account |
| `/logout` | Sign out |

Password requirements: min 8 chars, 1 uppercase, 1 lowercase, 1 digit.

### Servers & Channels

Once authenticated, you can create and join servers via invite codes:

| Command | Action |
|---------|--------|
| `/server create <name> [description]` | Create a new server (max 5 per user) |
| `/server list` | List your servers |
| `/server join <id>` | Join via invite code |
| `/server leave` | Leave current server |
| `/channel create <name> [type]` | Create a channel (text/voice) |
| `/channel list` | List channels in current server |
| `/channel join <id>` | Join a channel |
| `/channel delete <id>` | Delete a channel (Admin only) |

### Invites

All servers are invite-only. Share invite codes to let others join:

| Command | Action |
|---------|--------|
| `/invite create` | Create an invite code |
| `/invite list` | List active invites |
| `/invite join <code>` | Join a server via invite code |
| `/invite delete <id>` | Delete an invite |

### Members & Roles

| Command | Action |
|---------|--------|
| `/members` | List members in current server |
| `/kick <user_id>` | Kick a member (KICK_MEMBERS permission) |
| `/ban <user_id> [reason]` | Ban a member (BAN_MEMBERS permission) |
| `/unban <user_id>` | Unban a member (BAN_MEMBERS permission) |
| `/role create <name> [color]` | Create a role (Admin only) |
| `/role assign <user_id> <role_id>` | Assign a role to a member |
| `/role remove <user_id> <role_id>` | Remove a role from a member |

### Direct Messages & Friends

| Command | Action |
|---------|--------|
| `/dm <user_id>` | Open a DM conversation |
| `/dm list` | List DM conversations |
| `/friend add <user_id>` | Send a friend request |
| `/friend accept <user_id>` | Accept a friend request |
| `/friend remove <user_id>` | Remove a friend |
| `/friend list` | List friends |
| `/friend pending` | List pending friend requests |

### Media & Sharing

| Command | Action |
|---------|--------|
| `/voice on\|off` | ADPCM voice chat |
| `/video on\|off` | Camera track |
| `/screen on\|off` | Desktop screen share |
| `/screen show on\|off` | toggle remote screen frames in terminal (default: off) |
| `/viewer [off]` | open/close Canvas viewer in browser |
| `/monitors` | list displays |
| `/monitor N` | pick monitor for screen share (0 = all) |
| `/region L T W H` | crop screen share to a pixel region |
| `/region clear` | full monitor again |
| `/show [camera\|screen]` | redraw last remote ASCII frame |
| `/sendimage <path>` | send an image (auto-converted to WebP) |
| `/images` | list received images |
| `/sendfile <path>` | send a file (up to 1 MiB) |
| `/files` | list received files |
| `/download <id>` | save a received image or file to disk |
| `/preview <id>` | re-show ASCII preview of a received image |
| `/peers` | list peers + fingerprints |
| `/devices` | list audio devices |
| `/speaker <idx>` | select speaker output device |
| `/help` | show all commands |
| `/quit` | exit |

### Threads & Search

| Command | Action |
|---------|--------|
| `/thread create <name>` | create a thread in the current channel |
| `/thread list` | list active threads |
| `/thread join <id>` | join a thread |
| `/thread leave <id>` | leave a thread |
| `/thread msg <id> <text>` | send a message in a thread |
| `/thread archive <id>` | archive a thread (creator only) |
| `/search <query>` | search messages across servers |
| `/search <query> --channel <id>` | search in a specific channel |
| `/search <query> --server <id>` | search in a specific server |

### Reactions & Editing

| Command | Action |
|---------|--------|
| `/react <msg_id> <emoji>` | add a reaction to a message |
| `/unreact <msg_id> <emoji>` | remove your reaction |
| `/edit <msg_id> <new content>` | edit your message |
| `/delete <msg_id>` | delete your message |

### Profiles & Settings

| Command | Action |
|---------|--------|
| `/profile view [user_id]` | view a user profile |
| `/profile set bio <text>` | set your bio |
| `/profile set status <text>` | set custom status |
| `/profile set avatar <path>` | upload avatar image |
| `/status online\|idle\|dnd\|offline` | set online status |

### CLI flags

| Flag | Description |
|------|-------------|
| `--screen` | start screen share on connect |
| `--viewer` | open Canvas viewer in browser on connect |
| `--voice` | start voice chat on connect |
| `--video` | start camera on connect |
| `--monitor N` | select monitor for screen share |
| `--gui` | launch tkinter client GUI |
| `--flet` | launch Flet GUI (default for `gui_flet.py`) |
| `--no-gui` | force terminal mode |
| `--upnp` | map viewer port via UPnP IGD (client) |
| `--tor` | route through Tor SOCKS5 proxy |
| `--tor-proxy URL` | custom SOCKS5 proxy (default: `socks5://127.0.0.1:9050`) |
| `--port PORT` | relay listen port (default: 9473) |
| `--encrypt-db` | encrypt database with AES-256-GCM field-level encryption |
| `--host HOST` | relay bind address (default: 0.0.0.0) |
| `--tls` | connect to relay via TLS |
| `--no-verify` | skip TLS certificate verification (for self-signed certs) |

### TLS encryption

All traffic (including authentication) is encrypted in transit when using `--tls`:

```bash
# Server: auto-generates self-signed cert on first run
python server/relay.py --tls --port 9473

# Server: use your own cert
python server/relay.py --tls --certfile /path/to/cert.pem --keyfile /path/to/key.pem

# Client: connect with TLS (skip verification for self-signed)
python client/gui_flet.py --tls --no-verify --port 9473

# Terminal client
python client/main.py --tls --no-verify --user alice --port 9473
```

Without `--tls`, the relay runs plain TCP (E2E encryption still protects chat content, but auth packets are exposed). With `--tls`, all traffic including registration and login is encrypted.

The server auto-generates a self-signed certificate (stored as `.labhairliom_cert.pem` and `.labhairliom_key.pem` in the database directory) if no `--certfile`/`--keyfile` is provided. Clients must use `--no-verify` unless the cert is trusted by the system CA store.

### Relay controls

Run `python server/relay.py --gui` to open the relay control window. It shows
whether the relay is listening, the active peer/room count, and offers a
Start/Stop button. Enable **Host through Tor (.onion)** before starting to
create an ephemeral onion service; its address appears in the status area.
This requires a local Tor daemon with its ControlPort enabled (default
`127.0.0.1:9051`). The onion service is removed when the relay stops. The
packaged Windows relay opens this window when launched normally; pass
`--no-gui` to use its console mode.

**Relay TLS flags**: `--tls` enables TLS (auto-generates self-signed cert),
`--certfile PATH` / `--keyfile PATH` for custom certificates.

### Upload privacy

Images are re-encoded as metadata-free WebP and sent with the neutral name
`image.webp`; source filenames and embedded EXIF/GPS/device metadata are not
copied. Other file formats are sent only after a warning and confirmation,
because the app cannot safely scrub every document, archive, audio, or video
format. Choosing **Send anyway** displays a red warning that identifying
metadata was not stripped.

## Flet GUI

The Flet GUI (`client/gui_flet.py`) provides a modern Discord-like interface built on Flutter:

- **Server bar** — left sidebar with server icons, DM, voice controls, viewer/screen/camera buttons
- **Channel panel** — channel list with text/voice channels, voice member display, search panel
- **Chat view** — message list with role-colored names, inline image preview, file attachment display
- **Member panel** — right sidebar grouped by role with role-colored names
- **Server settings** — tabbed dialog for server name/icon, channel management, role management
- **User settings** — profile editor with avatar upload, status, bio, camera/monitor selection
- **Audio settings** — mic/speaker device selection, volume, noise gate/suppression
- **Invite dialog** — create, list, copy, and delete invite codes
- **Context menu** — right-click messages for reactions, edit, delete, reply, copy
- **Emoji picker** — quick reaction picker with common emojis

### Audio noise filtering

The Audio Settings dialog provides three mic filter modes:

| Mode | Description |
|------|-------------|
| **Off** | No filtering (raw mic input) |
| **Noise Gate** | Silences mic when volume is below threshold. Good for cutting background hum between speech. |
| **Noise Suppression** | Estimates and removes constant background noise (fans, keyboard clicks). Calibrates from the first 30 frames of silence. |

Adjust the threshold slider to control how aggressively the gate cuts audio.

### Avatars & Server Icons

- **User avatars**: Click "Choose Image" in User Settings to upload a PNG/JPG/GIF. Images are resized to 128x128 and sent as base64.
- **Server icons**: Click the server settings cog, then "Choose Image" under Server Icon. Images are resized to 128x128 and stored as data URLs.
- Server bar buttons display icon images when set, otherwise show the first letter of the server name.

## Building for Windows

Two standalone `.exe` files can be built — a console relay server and a windowed GUI client.

### Local build (on Windows)

```bash
git clone https://github.com/YOU/labhair-liom.git
cd labhair-liom
pip install -r requirements.txt pyinstaller
python build.py
```

Produces:
- `dist/labhairliom-relay.exe` — relay server (console)
- `dist/labhairliom-client.exe` — GUI client (no console window)

### Pre-built downloads

Go to [Releases](../../releases) and grab the latest `labhairliom-relay.exe` and `labhairliom-client.exe` — no Python install required.

### Build via GitHub Actions

Pushing a tag starting with `v` (e.g. `v1.0.0`) triggers an automated build:

```bash
git tag v1.0.0
git push --tags
```

The workflow builds both `.exe` files on `windows-latest` and attaches them to a GitHub Release.

## Building for Android

An Android APK can be built using [Buildozer](https://buildozer.readthedocs.io/) + [python-for-android](https://python-for-android.readthedocs.io/).

### Local build on Ubuntu / Debian

```bash
sudo apt install build-essential git python3-pip autoconf libtool pkg-config \
  zlib1g-dev libncurses5-dev libtinfo5 cmake libffi-dev libssl-dev openjdk-17-jdk

pip install buildozer cython
buildozer android debug
```

Output: `bin/labhairliom-debug.apk`

### Local build on CachyOS / Arch Linux

```bash
sudo pacman -S base-devel git python-pip autoconf libtool pkgconf zlib \
  ncurses cmake libffi openssl jdk17-openjdk

pip install buildozer cython
buildozer android debug
```

### Local build on Windows

Buildozer requires Linux. On Windows you have two options:

**Option A — WSL2 (recommended)**

```powershell
wsl --install -d Ubuntu-22.04
# Inside WSL:
sudo apt install build-essential git python3-pip autoconf libtool pkg-config \
  zlib1g-dev libncurses5-dev libtinfo5 cmake libffi-dev libssl-dev openjdk-17-jdk
pip install buildozer cython
buildozer android debug
```

The APK will be in `~/labhair-liom/bin/`. Copy it out with:

```powershell
wsl cat ~/labhair-liom/bin/labhairliom-debug.apk > labhairliom-debug.apk
```

**Option B — Docker**

```powershell
docker run --rm -v "%CD%:/app" -w /app \
  cython3/buildozer:latest android debug
```

### Build via GitHub Actions (any OS)

Pushing a tag starting with `v` (e.g. `v1.0.0`) triggers an automated build — no local toolchain needed:

```bash
git tag v1.0.0
git push --tags
```

The workflow builds a debug APK on `ubuntu-latest` and attaches it to a GitHub Release.

### What it includes

The Android app reuses the same crypto, protocol, and codec layers as the desktop client. It features:

- Connection screen with host/port/room/name fields
- Chat with inline message display
- Mic / Camera / Screen toggle buttons
- Image and file sharing via Android file picker
- E2E encryption (X25519 + ChaCha20-Poly1305)
- Camera via Camera1 API (front-facing, 320x240 preview)
- Screen capture via MediaProjection API with foreground service (Android 14+)
- Mic/speaker via AudioRecord/AudioTrack (16 kHz ADPCM)

## Canvas viewer

The Canvas viewer renders screen share as JPEG in a browser with system audio playback. In GUI mode, the viewer opens as a separate tkinter popup window instead.

```bash
# Start with viewer
python client/main.py --user alice --room demo --screen --viewer

# Or open viewer later
/viewer
/viewer off
```

The viewer captures system audio (what plays through your speakers) from the sharing PC via PipeWire/PulseAudio monitor source and streams it to the browser. Click **Enable Sound** in the browser to start audio playback (required by browser autoplay policy).

**System dependencies for audio capture** (Linux only):
- `pactl` (PulseAudio/PipeWire) — for finding the audio monitor source
- `pw-record` (PipeWire) — for capturing system audio

## Architecture

```
┌────────────┐     ciphertext      ┌─────────────┐     ciphertext    ┌────────────┐
│  Client A  │ ───────────────────►│ Blind relay │──────────────────►│  Client B  │
│            │◄─────────────────── │  (no keys)  │◄──────────────────│            │
└─────┬──────┘                     └─────────────┘                   └─────┬──────┘
      │                                                                    │
      ├─ X25519 identity + ephemeral (triple-DH style) ────────────────────┤
      ├─ HKDF-SHA256 → directional ChaCha20-Poly1305 ──────────────────────┤
      ├─ Chat: JSON text ──────────────────────────────────────────────────┤
      ├─ Voice: ADPCM/ima-v1 frames (20 ms, 8 kHz) ────────────────────────┤
      ├─ Video: LABHAIR-LIOM/1.0 frames ───────────────────────────────────┤
      ├─ Image: WebP + ASCII preview ──────────────────────────────────────┤
      ├─ File: raw bytes + metadata ───────────────────────────────────────┤
      └─ Control: key exchange, media presence, peer info ─────────────────┘
```

### E2E crypto

1. Each client has a long-term **X25519 identity** key.
2. On peer join, both send **ephemeral** public keys.
3. Session material = `ECDH(eph,peer_eph) || ECDH(id,peer_eph) || ECDH(eph,peer_id)`.
4. HKDF derives two directional AEAD keys (initiator/responder ordered by identity).
5. Nonces are counters with replay detection. AAD binds `from|to|msg_type`.

### Database encryption

The relay supports optional AES-256-GCM field-level encryption for the SQLite database:

```bash
python server/relay.py --encrypt-db --port 9473
```

Encrypted fields include: user passwords, messages, DMs, attachments, channel encryption keys, and invite codes. Encryption keys are stored in `.labhairliom_key`.

### Voice channels

Voice channels track connected members. Click a voice channel to join; click another to switch (with confirmation dialog). Voice members are displayed under each voice channel with mic icons.

### Screen capture backends (Wayland-safe)

`mss` often returns **black frames on Wayland**. The client probes backends in order and keeps the first that yields a real image:

| Backend | When it works | FPS |
|---------|---------------|-----|
| **gpu-screen-recorder** | Wayland (GPU-accelerated, persistent pipe mode) | ~27 |
| **grim** | wlroots (Sway, Hyprland, ...) | ~15 |
| **spectacle** | KDE Plasma / kwin_wayland | ~2 |
| **mss** | X11 (fast) | ~30 |
| **ImageMagick** | `magick import` / `import` fallback | ~3 |

`gpu-screen-recorder` uses a **persistent streaming mode**: one long-lived process encodes H264/MPEG-TS to a pipe, decoded in real-time by ffmpeg. This achieves ~27 fps vs ~2 fps with per-frame subprocess spawning.

`/monitors` prints the active backend and a grab timing sample.

```bash
# share primary monitor only
/screen on
/monitors
/monitor 1

# share a window-ish crop (global pixel coords)
/region 100 100 1280 720

# toggle remote screen display in terminal
/screen show off
```

### ADPCM voice

| Property | Value |
|----------|--------|
| Sample rate | 8 kHz mono (resampled from 48 kHz device rate) |
| Frame | 20 ms (160 samples) |
| Bitrate | 64 kb/s active |
| DTX | silence suppression with SID frames |
| Payload tag | `ADPCM/ima-v1` |

IMA/DVI ADPCM is a public-domain algorithm with no patents. Ultra-low CPU cost.

### System audio (viewer)

The Canvas viewer captures system audio from the screen-sharing PC via PipeWire/PulseAudio's monitor source:

- Uses `pactl info` to find the default output sink
- Constructs `<sink>.monitor` source name
- Captures via `pw-record` at 16 kHz mono
- Streams to browser via HTTP polling (`GET /audio`)
- Browser decodes PCM and plays via Web Audio API

This captures everything playing through the speakers (browser audio, videos, music, games, system sounds).

### Image sharing

Images are converted to WebP on send (quality 80) to save bandwidth. A small ASCII preview is included in the payload so receivers can display it without decoding the full image. Images are stored in memory only — use `/download <id>` to save to disk. Received files are saved to `~/.local/share/labhairliom/images/` on Linux (or `$XDG_DATA_HOME/labhairliom/images/`) or `%LOCALAPPDATA%\labhairliom\images` on Windows.

### File sharing

Send any file up to 1 MiB with `/sendfile <path>`. Files are E2E encrypted like all other traffic. Metadata (name, MIME type, size, SHA-256) is visible to receivers before download. Use `/files` to list and `/download <id>` to save.

Channel attachments use per-channel AES-256-GCM encryption keys, distributed to members via `CHANNEL_LIST`/`CHANNEL_JOIN` responses.

## Tests

```bash
# Run all tests
.venv/bin/python -m pytest tests/ -v

# Run specific test suites
.venv/bin/python -m pytest tests/test_message_manager.py -v    # Message tests
.venv/bin/python -m pytest tests/test_dm_friend.py -v          # DM & friend tests
.venv/bin/python -m pytest tests/test_member_manager.py -v     # Member management tests
.venv/bin/python -m pytest tests/test_codecs_crypto.py -v      # Crypto & codec tests

# Legacy test runner
.venv/bin/python tests/test_codecs_crypto.py
```

## Layout

```
Labhair-liom/
  server/
    relay.py                     # stateful relay with auth, servers, channels, DMs
    auth_handler.py              # register, login, password management
    server_manager.py            # server CRUD, join/leave, search, invite-only enforcement
    channel_manager.py           # channel CRUD with permission checks
    message_manager.py           # persistent message send/history/edit/delete/reactions
    dm_manager.py                # DM send/history/conversations/mark-read
    friend_manager.py            # friend add/accept/remove/list/pending
    member_manager.py            # kick/ban/unban/member list with permission checks
    role_manager.py              # roles, permissions, assign/remove
    thread_manager.py            # thread create/join/leave/messages/archive
  client/
    main.py                      # interactive client (terminal + asyncio)
    gui.py                       # tkinter GUI with Discord-like layout
    gui_flet.py                  # Flet GUI entry point (Flutter-based)
    audio_io.py                  # mic/speaker + ADPCM + noise gate/suppression
    video_io.py                  # camera + Labhair-liom + screen loop
    screencap.py                 # desktop capture backends + persistent GSR
    web_viewer.py                # Canvas viewer HTTP server + audio capture
    flet_app/                    # Flet GUI components
      app.py                     # main layout, callbacks, state management
      connect_page.py            # auth page with password hints
      server_bar.py              # server rail with icons, voice controls, viewer
      channel_panel.py           # channel list with search, settings, voice display
      chat_view.py               # messages with role colors, attachments, context menu
      member_panel.py            # member sidebar grouped by role
      dialogs.py                 # server settings, user settings, invite, status dialogs
      audio_settings.py          # mic/speaker device + volume + noise filter dialog
      dm_view.py                 # direct message view
      thread_panel.py            # thread sidebar
      viewer.py                  # video viewer with JPEG frame switching
      theme.py                   # Discord dark color constants
    android_app/
      __init__.py
      main.py                    # Kivy mobile UI (connection + chat screens)
      android_audio.py           # mic/speaker via Java AudioRecord/AudioTrack
      android_video.py           # camera (Camera1) + screen (MediaProjection)
      foreground_service.py      # Android 14+ MediaProjection foreground service
  shared/
    crypto.py                    # X25519 + ChaCha20-Poly1305
    protocol.py                  # length-prefixed packets + MsgType enums
    adpcm.py                     # IMA/DVI ADPCM voice codec (8 kHz)
    labhair_liom.py              # Labhair-liom codec (PIL, no cv2 required)
    image_share.py               # WebP image sharing
    file_share.py                # generic file transfer
    database.py                  # async SQLite (users, servers, channels, messages, etc.)
    encryption.py                # AES-256-GCM field-level encryption for database
    auth.py                      # bcrypt password hashing, session manager
    settings.py                  # client settings (camera, screen, audio preferences)
    upnp.py                      # UPnP IGD port mapping
    privacy.py                   # metadata scrubbing for shared files
  tests/
  requirements.txt
  buildozer.spec                 # Android APK build config (API 35)
  build.py                       # Windows .exe build script
  labhairliom-relay.spec          # PyInstaller spec (relay)
  labhairliom-client.spec         # PyInstaller spec (GUI client)
```

## Notes

- **Discord-like features**: The relay maintains persistent state in SQLite (users, servers, channels, messages, roles, DMs, friendships). Users register accounts and authenticate with bcrypt-hashed passwords. Messages are stored and can be retrieved with history.
- **Invite-only**: All servers require an invite code to join. Direct server joins are disabled. Server creators can generate invite codes via the GUI or `/invite create` command.
- **Server limit**: Each user can own a maximum of 5 servers. Delete a server before creating a new one if at the limit.
- **Permissions**: Discord-style role-based permissions with 30+ granular permissions (KICK_MEMBERS, BAN_MEMBERS, MANAGE_SERVER, etc.). Default @everyone role cannot kick/ban.
- **Noise filtering**: The VoiceEngine supports three mic modes: none, noise gate (RMS threshold), and noise suppression (adaptive noise floor estimation).
- **Security**: No forward secrecy ratchet beyond the ephemeral exchange; no authentication of identity keys out-of-band beyond fingerprint display. Compare `/peers` fingerprints on a second channel for MITM resistance. TLS (`--tls`) encrypts all transport traffic including authentication.
- **Headless**: Without a camera, video still streams an animated ASCII test pattern. Without a mic/speaker, `/voice on` will error with a sounddevice message.
- **Audio capture**: System audio in the viewer requires PipeWire or PulseAudio with monitor/loopback support. On PipeWire, `pw-record` and `pactl` must be installed. On PulseAudio, `parec` may be used instead. On Windows, WASAPI loopback is used automatically.
- **UPnP**: Both the relay and viewer can auto-map ports via UPnP IGD when `--upnp` is set (relay does this by default). Requires `miniupnpc` (included in `requirements.txt`). Falls back gracefully if no UPnP gateway is found.
- **Tor**: The relay can create an ephemeral hidden service with `--tor` (requires Tor with ControlPort enabled and the `stem` library). Clients connect via `--tor` which routes through a local SOCKS5 proxy.
- **Flet GUI**: Run `python client/gui_flet.py` for the modern Flutter-based interface. Supports all features including voice, video, screen share, noise filtering, avatars, server icons, invites, and server settings.
- **tkinter GUI**: Run with `--gui` for the legacy interface. The tkinter GUI features a Discord-like layout with server bar, channel sidebar, chat area, and member list.
- **Android**: Built with Buildozer + python-for-android. Camera uses Camera1 API (pyjnius cannot proxy Camera2's abstract StateCallback). Screen capture uses MediaProjection API with a foreground service (required on Android 14+). The Java `ScreenCaptureHelper` class is compiled into the APK via `android.add_src = src`.

## Licenses

### Third-party dependencies

| Dependency | License |
|------------|---------|
| [cryptography](https://github.com/pyca/cryptography) | Apache-2.0 / BSD-3-Clause (dual) |
| [numpy](https://github.com/numpy/numpy) | BSD-3-Clause |
| [Pillow](https://github.com/python-pillow/Pillow) | MIT-CMU |
| [mss](https://github.com/BoboTiG/python-mss) | MIT |
| [python-socks](https://github.com/romis2012/python-socks) | Apache-2.0 |
| [miniupnpc](https://miniupnp.tuxfamily.org/) | BSD-3-Clause |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | MIT |
| [opencv-python-headless](https://github.com/opencv/opencv-python) | Apache-2.0 |
| [aiosqlite](https://github.com/omnilib/aiosqlite) | MIT |
| [bcrypt](https://github.com/pyca/bcrypt) | Apache-2.0 |
| [asyncpg](https://github.com/MagicStack/asyncpg) | Apache-2.0 |
| [flet](https://github.com/flet-dev/flet) / flet-desktop | Apache-2.0 |
| [pyperclip](https://github.com/asweigart/pyperclip) | BSD |
| [pyspellchecker](https://github.com/barrysteyn/pyspellchecker) | MIT |
| [stem](https://gitlab.torproject.org/tpo/core/stem) | LGPL-3.0 |

**Notes:**
- **stem** (LGPL-3.0) is an optional dependency used only for Tor relay control. It is installed separately via `pip install stem` and loaded dynamically — it is not linked into or bundled with this project's code. Bundled Windows/Android builds do not include it.
- The **IMA/DVI ADPCM** codec (`shared/adpcm.py`) implements a public-domain algorithm with no patents.
- No third-party source code is vendored into this repository; all dependencies are installed from PyPI.
