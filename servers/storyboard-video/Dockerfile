# Build stage: everything that downloads or compiles (pip, Playwright's browser, Pocket TTS + its weights,
# static ffmpeg). Only the results are copied into the runtime stage, so no curl/xz/pip cache or apt lists land there.
FROM python:3.12-slim AS build

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates xz-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml ./
COPY storyboard_video_mcp ./storyboard_video_mcp
# cryptography/cffi/pycparser arrive only through mcp -> pyjwt[crypto]; this stdio server signs nothing.
# Playwright's own chromium shell (--only-shell: every launch here is headless); the system libraries it
# links are apt-installed in the runtime stage, so no --with-deps here.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install --no-cache-dir --no-compile --prefix=/install . \
 && SP=/install/lib/python3.12/site-packages \
 && rm -rf $SP/cryptography* $SP/cffi* $SP/_cffi_backend* $SP/pycparser* \
 && find /install -name __pycache__ -prune -exec rm -rf {} + \
 && find /install -name '*.pyi' -delete \
 && PYTHONPATH=$SP python -m playwright install --only-shell chromium

# Static ffmpeg + ffprobe (libx264, libass, loudnorm, x11grab via xcb): ~150 MB instead of Debian's ffmpeg
# and its Mesa/LLVM/GL dependency tree. Pinned by sha256; when upstream publishes a new release the
# build fails loudly here -- bump both sums together.
ARG TARGETARCH
RUN case "$TARGETARCH" in \
      amd64) A=amd64; SUM=abda8d77ce8309141f83ab8edf0596834087c52467f6badf376a6a2a4c87cf67 ;; \
      arm64) A=arm64; SUM=f4149bb2b0784e30e99bdda85471c9b5930d3402014e934a5098b41d0f7201b1 ;; \
      *) echo "unsupported arch: $TARGETARCH" >&2; exit 1 ;; \
    esac \
 && curl -fsSL -o /tmp/ff.txz https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-$A-static.tar.xz \
 && echo "$SUM  /tmp/ff.txz" | sha256sum -c - \
 && mkdir -p /ff && tar -xJf /tmp/ff.txz -C /ff --strip-components=1 --wildcards '*/ffmpeg' '*/ffprobe' \
 && rm /tmp/ff.txz

# Offline narration: Pocket TTS (Kyutai), a standalone CPU-only Rust binary (no Python, no torch, no G2P
# library). The binary is sha256-checked per arch; the weights of both languages and of every catalogue
# voice (voices.py) are pulled into /opt/hf once, at build time, by synthesizing a word with each: the
# container then runs with HF_HUB_OFFLINE=1 and never reaches the network. Needs a CPU with AVX2 (x86_64).
ARG POCKET_TTS=v4.0.1
# the asset name carries the crate version, not the release tag; the sha256 below pins both
ARG POCKET_TTS_CRATE=3.3.0
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
      for V in $(PYTHONPATH=/install/lib/python3.12/site-packages python -c "from storyboard_video_mcp import voices; print(*voices.names('en' if '$L' == 'english' else 'pt-BR'))"); do \
        HF_HOME=/opt/hf /opt/pocket-tts/pocket-tts generate -q --language $L --voice $V --text "Ok." --output-path /tmp/warm.wav || exit 1; \
      done; \
    done; rm -f /tmp/warm.wav

FROM python:3.12-slim

# Runtime packages only. Xvfb/xterm/xdotool/x11-utils drive capture_terminal_session; gcc/libc6-dev let a
# CLI demo compile its sample program inside the container (xterm needs CAP_SETGID: run the exec entry
# with --cap-drop ALL --cap-add SETGID). The rest are the shared libraries chrome-headless-shell links
# (what `playwright install-deps` lists, minus Mesa/LLVM/GL: the shell renders with its bundled SwiftShader).
# Mesa is the weight: xvfb -> libgl1 -> libglx0 -> libglx-mesa0 -> mesa-libgallium -> LLVM + z3 (~200 MB),
# and libgbm1 -> mesa-libgallium. Xvfb and chromium never open a GL/GBM device here, so x11-utils/xvfb/libgl1/libglx0
# and libgbm1 are unpacked with dpkg --force-depends and the Mesa driver stack is left out.
# Fonts: DejaVu + Inter for the renderer, Noto Color Emoji for emoji in captured pages; CJK fonts are left out.
RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc libc6-dev \
      xterm xdotool ca-certificates \
      xserver-common libglvnd0 libxcb-glx0 libxcb-shm0 libxxf86vm1 libpixman-1-0 libunwind8 libxfont2 \
      fontconfig fonts-dejavu-core fonts-inter fonts-noto-color-emoji \
      libnss3 libnspr4 libatk1.0-0t64 libatk-bridge2.0-0t64 libcups2t64 libdrm2 libxkbcommon0 \
      libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libasound2t64 libpango-1.0-0 libcairo2 \
      libx11-6 libxcb1 libxext6 libwayland-server0 \
      libfontconfig1 libx11-xcb1 libxaw7 libxcb-shape0 libxft2 libxi6 libxinerama1 libxkbfile1 libxmu6 \
      libxmuu1 libxtst6 libxv1 libxxf86dga1 libxt6t64 libxrender1 \
 && cd /tmp && apt-get download x11-utils xvfb libgl1 libglx0 libgbm1 \
 && dpkg --force-depends -i x11-utils_*.deb xvfb_*.deb libgl1_*.deb libglx0_*.deb libgbm1_*.deb \
 && rm -f /tmp/*.deb && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man

COPY --from=build /ff/ffmpeg /ff/ffprobe /usr/local/bin/
COPY --from=build /install /usr/local
COPY --from=build /ms-playwright /ms-playwright
COPY --from=build /opt/pocket-tts /opt/pocket-tts
COPY --from=build /opt/hf /opt/hf
COPY NOTICE /app/NOTICE

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    STORYBOARD_TTS_BIN=/opt/pocket-tts/pocket-tts STORYBOARD_TTS_HOME=/opt/hf
ENV STORYBOARD_WORK=/work STORYBOARD_REPO=/repo
WORKDIR /app
VOLUME ["/work"]
ENTRYPOINT ["storyboard-video-mcp"]
