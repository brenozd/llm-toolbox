# The runtime base, referenced twice: as the final image and as the source of its own /etc/passwd.
FROM gcr.io/distroless/python3-debian12@sha256:2fdb05402a2cf21cf78fdb3ba4c5db167241e9e498140f5bf689d7efb773731f AS distro

# Build stage on the Python the runtime ships: distroless python3-debian12 is CPython 3.11, so
# everything collected here matches the interpreter that loads it.
FROM python:3.11-slim-bookworm AS build

# The only ffmpeg use in this server is the voice-note encode in audio.py (Opus/Ogg, 24 kHz), so a
# ~2.5 MB static ffmpeg comes from the pinned source instead of apt-installing Debian's ffmpeg,
# which drags in the whole Mesa/LLVM GL stack and every codec. Same source and flags on every
# architecture (CI builds amd64 only), so there is no per-arch binary to pin.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential pkg-config libopus-dev curl xz-utils \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL -o /tmp/ffmpeg.tar.xz https://ffmpeg.org/releases/ffmpeg-7.1.1.tar.xz \
 && echo "733984395e0dbbe5c046abda2dc49a5544e7e0e1e2366bba849222ae9e3a03b1  /tmp/ffmpeg.tar.xz" | sha256sum -c - \
 && mkdir -p /src && tar -xJf /tmp/ffmpeg.tar.xz -C /src --strip-components=1
RUN cd /src && ./configure \
      --disable-everything --disable-autodetect --disable-network --disable-doc --disable-debug \
      --disable-htmlpages --disable-manpages --disable-podpages --disable-txtpages \
      --disable-avdevice --disable-postproc --disable-ffplay \
      --disable-shared --enable-static --enable-small --disable-x86asm \
      --enable-libopus --enable-ffprobe \
      --enable-protocol='file,pipe' \
      --enable-demuxer='aac,ac3,aiff,amr,asf,flac,matroska,mp3,mov,ogg,wav' \
      --enable-muxer='ipod,ogg,opus' \
      --enable-decoder='aac,ac3,alac,amrnb,amrwb,flac,mp3,opus,vorbis,wmav1,wmav2,pcm_alaw,pcm_mulaw,pcm_s16be,pcm_s16le,pcm_s24le,pcm_s32le,pcm_f32le,pcm_u8' \
      --enable-encoder='libopus' \
      --enable-parser='aac,ac3,flac,mpegaudio,opus,vorbis' \
      --enable-filter='aformat,amerge,anull,anullsrc,apad,aresample,asetnsamples,atrim,channelmap,concat,format,null,pan,volume' \
 && make -j"$(nproc)" ffmpeg ffprobe \
 && install -m 0755 ffmpeg ffprobe /usr/local/bin/

# libmagic: neonize imports python-magic at import time. uid 10001 owns /data (the WhatsApp session).
# The two shared objects ffmpeg's build links against are staged under the names dlopen() asks for.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libmagic1 busybox-static \
 && rm -rf /var/lib/apt/lists/* \
 && install -d -o 10001 -g 10001 -m 0700 /data \
 && install -d -m 0755 /media \
 && install -d /stage/lib /stage/bin \
 && install -m 0644 /usr/lib/*-linux-gnu/libmagic.so.1.* /stage/lib/libmagic.so.1 \
 && install -m 0644 /usr/lib/*-linux-gnu/libopus.so.0.* /stage/lib/libopus.so.0 \
 && install -m 0755 /bin/busybox /stage/bin/sh \
 && install -m 0755 /bin/busybox /stage/bin/uname
# uid 10001 has no name on distroless, so pwd.getpwuid(10001) raises and expanduser("~") gives
# "/" (the old image had `wa`). Start from the base's own lists and append the entry rather than
# hard-coding them.
COPY --from=distro /etc/passwd /etc/group /stage/etc/
RUN echo 'wa:x:10001:10001::/home/wa:/usr/sbin/nologin' >> /stage/etc/passwd \
 && echo 'wa:x:10001:' >> /stage/etc/group

WORKDIR /app
COPY pyproject.toml ./
COPY whatsapp_mcp ./whatsapp_mcp
RUN pip install --no-cache-dir --no-compile --prefix=/install . \
 && rm -rf /install/lib/python3.11/site-packages/cryptography* /install/lib/python3.11/site-packages/cffi* /install/lib/python3.11/site-packages/_cffi_backend* /install/lib/python3.11/site-packages/pycparser* \
 && rm -rf /install/lib/python3.11/site-packages/phonenumbers/geodata /install/lib/python3.11/site-packages/phonenumbers/carrierdata \
 && find /install -name __pycache__ -prune -exec rm -rf {} + \
 && find /install -name '*.pyi' -delete

# Runtime: distroless python3 instead of python:3.12-slim — 53 MB vs 120 MB, and no shell or
# compiler in the image. chown is kept because `--entrypoint chown` is the documented way to fix
# ownership of an old /data volume.
FROM distro

COPY --from=build /install/lib/python3.11/site-packages /usr/lib/python3/dist-packages
COPY --from=build /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=build /usr/local/bin/ffprobe /usr/local/bin/ffprobe
# arch-suffixed source paths: the wildcards keep these lines valid on amd64 and arm64 alike.
COPY --from=build /stage/lib/ /usr/local/lib/
COPY --from=build /usr/share/misc/magic.mgc /usr/share/misc/magic.mgc
COPY --from=build /usr/bin/chown /usr/bin/chown
# neonize shells out to `uname -a` at import time, so a static busybox provides /bin/sh and
# /bin/uname without dragging in coreutils or bash.
COPY --from=build /stage/bin/ /bin/
COPY --from=build --chown=10001:10001 --chmod=0700 /data /data
COPY --from=build /media /media
COPY --from=build /stage/etc/passwd /stage/etc/group /etc/

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
# Same HOME the old image's useradd gave the `wa` user; /home/wa stays absent as it did there.
ENV HOME=/home/wa
# libmagic lives outside the distroless loader path; python-magic resolves the soname through it.
ENV LD_LIBRARY_PATH=/usr/local/lib

USER 10001:10001
VOLUME ["/data"]
ENV WHATSAPP_MCP_CONFIG=/config/config.json

ENTRYPOINT ["/usr/bin/python3", "-m", "whatsapp_mcp.cli"]
