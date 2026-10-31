FROM python:3.12-slim

# ffmpeg (libx264) + Xvfb/xterm for GUI capture + fonts for the renderer. No Debian `chromium`:
# see the Playwright block below.
# xdotool/x11-utils drive real keystrokes into xterm for capture_terminal_session (no WM needed,
# but xterm needs CAP_SETGID: run the exec entry with --cap-drop ALL --cap-add SETGID).
# gcc/libc6-dev so a CLI demo can compile its sample program inside the container instead of
# shipping a binary, and the capture shows the real compile.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg xvfb xterm xdotool x11-utils fonts-dejavu-core fonts-inter \
      curl ca-certificates gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY storyboard_video_mcp ./storyboard_video_mcp
COPY NOTICE ./

# Playwright's own chromium instead of the distro package: every launch here (capture, stills,
# preflight) is headless, so Playwright picks the --only-shell build — the exact browser the pinned
# playwright version was tested against, and 382 MB of Debian chromium + chromium-common (plus gtk3, adwaita, systemd) go away.
# Mesa/LLVM stays: the shell needs libgbm1, same as before.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install --no-cache-dir . \
 && playwright install --only-shell --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

# Offline narration: Pocket TTS (Kyutai), a standalone CPU-only Rust binary (no Python, no torch, no G2P
# library). The binary is sha256-checked per arch; the weights of both languages and of every catalogue
# voice (voices.py) are pulled into /opt/hf once, at build time, by synthesizing a word with each: the
# container then runs with HF_HUB_OFFLINE=1 and never reaches the network. Needs a CPU with AVX2 (x86_64).
ARG TARGETARCH
ARG POCKET_TTS=v4.0.1
# the asset name carries the crate version, not the release tag; the sha256 below pins both
ARG POCKET_TTS_CRATE=3.3.0
ENV STORYBOARD_TTS_BIN=/opt/pocket-tts/pocket-tts STORYBOARD_TTS_HOME=/opt/hf
RUN case "$TARGETARCH" in \
      amd64) T=x86_64-unknown-linux-gnu; SUM=9abff0aa138a804e44052952d8c3bdaae247fb267ca8f4b83fe178897d1a0559 ;; \
      arm64) T=aarch64-unknown-linux-gnu; SUM=2b9a727bffd86ea6d73370d675cbd91a7db118f11b7f5a60343c2d5da12b187a ;; \
      *) echo "unsupported arch: $TARGETARCH" >&2; exit 1 ;; \
    esac \
 && F=pocket-tts-$POCKET_TTS_CRATE-$T.tar.gz \
 && curl -fsSL -O https://github.com/kyutai-labs/pocket-tts/releases/download/$POCKET_TTS/$F \
 && echo "$SUM  $F" | sha256sum -c - \
 && mkdir -p /opt/pocket-tts && tar xzf $F -C /opt/pocket-tts --strip-components=1 && rm $F \
 && for L in english portuguese; do \
      for V in $(python -c "from storyboard_video_mcp import voices; print(*voices.names('en' if '$L' == 'english' else 'pt-BR'))"); do \
        HF_HOME=/opt/hf /opt/pocket-tts/pocket-tts generate -q --language $L --voice $V --text "Ok." --output-path /tmp/warm.wav || exit 1; \
      done; \
    done; rm -f /tmp/warm.wav

ENV STORYBOARD_WORK=/work STORYBOARD_REPO=/repo
VOLUME ["/work"]
ENTRYPOINT ["storyboard-video-mcp"]
