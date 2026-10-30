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
COPY promo_video_mcp ./promo_video_mcp
COPY NOTICE ./

# Playwright's own chromium instead of the distro package: every launch here (capture, stills,
# preflight) is headless, so Playwright picks the --only-shell build — the exact browser the pinned
# playwright version was tested against, and 382 MB of Debian chromium + chromium-common (plus gtk3, adwaita, systemd) go away.
# Mesa/LLVM stays: the shell needs libgbm1, same as before.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install --no-cache-dir . \
 && playwright install --only-shell --with-deps chromium \
 && rm -rf /var/lib/apt/lists/*

# Offline narration: Kokoro-82M (Apache-2.0 weights, MIT wrapper) + the 54-voice pack, baked in at
# build time and sha256-checked, so the container never reaches the network. espeak-ng (bundled by
# espeakng-loader) does the G2P for both en and pt-BR, which is why misaki/torch is not installed.
ENV KOKORO_DIR=/opt/kokoro
RUN pip install --no-cache-dir kokoro-onnx==0.6.1 onnxruntime==1.31.1 \
 && mkdir -p $KOKORO_DIR && cd $KOKORO_DIR \
 && curl -fsSL -O https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/kokoro-v1.0.fp16.onnx \
 && curl -fsSL -O https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/voices-v1.0.bin \
 && echo "f3a290d384fbb27966d462905c71a46cef9e5fd00516b40df32a0b4afe77ac96  kokoro-v1.0.fp16.onnx" | sha256sum -c - \
 && echo "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d  voices-v1.0.bin" | sha256sum -c -

ENV PROMO_WORK=/work PROMO_REPO=/repo \
    PROMO_KOKORO_MODEL=$KOKORO_DIR/kokoro-v1.0.fp16.onnx \
    PROMO_KOKORO_VOICES=$KOKORO_DIR/voices-v1.0.bin
VOLUME ["/work"]
ENTRYPOINT ["promo-video-mcp"]
