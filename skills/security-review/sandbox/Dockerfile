# Shared sandbox image for the security-review skill: web profile (nuclei, sqlmap,
# curl) and binary-c profile (afl++, clang/gcc + ASan, gdb, frida).
#
# Build: docker build -t security-review-sandbox:local skills/security-review/sandbox
FROM debian:bookworm-slim@sha256:734a72b3d6142a71993b4bc580ca01d8ca687f77a2c422d96a961d3376b179bc

# HOME=/tmp: tools that insist on a config dir (nuclei, frida) write there, which is
# a tmpfs at runtime, never ~/.config. No state survives the container.
ENV DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8 HOME=/tmp

ARG NUCLEI_VERSION=3.11.1
ARG NUCLEI_TEMPLATES_VERSION=10.5.1
# Digest of the templates tarball. GitHub's archive tarball is regenerable, so the
# release's checksums.txt alone does not pin it: the digest is fixed here too, and the
# build fails if either check disagrees. frida-tools' version lives only in
# requirements-frida.txt, where it is hash-pinned.
ARG NUCLEI_TEMPLATES_SHA256=30fe1cfaced4635f886e4a2673641bba86998dceec28e468274524e789aa56eb

# afl++ and sqlmap are pinned to exact Debian bookworm versions. The base toolchain
# (clang/gcc/gdb/curl) floats within bookworm/security updates: pinning those breaks
# the build whenever Debian ships a security revision. See README "Pinned versions".
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl unzip python3 python3-pip \
      clang gcc make gdb libclang-rt-14-dev \
      afl++=4.04c-4 sqlmap=1.7.2-1 \
 && rm -rf /var/lib/apt/lists/*

# nuclei binary, checksum-verified against the release's own checksums file.
RUN set -eux; cd /tmp; \
    curl -fsSLO "https://github.com/projectdiscovery/nuclei/releases/download/v${NUCLEI_VERSION}/nuclei_${NUCLEI_VERSION}_linux_amd64.zip"; \
    curl -fsSLo checksums.txt "https://github.com/projectdiscovery/nuclei/releases/download/v${NUCLEI_VERSION}/nuclei_${NUCLEI_VERSION}_checksums.txt"; \
    grep -E "  nuclei_${NUCLEI_VERSION}_linux_amd64\.zip$" checksums.txt | sha256sum -c -; \
    unzip -q "nuclei_${NUCLEI_VERSION}_linux_amd64.zip" -d /usr/local/bin nuclei; \
    chmod +x /usr/local/bin/nuclei; rm -f "nuclei_${NUCLEI_VERSION}_linux_amd64.zip" checksums.txt

# Templates baked in at build time: runtime uses -t /opt/nuclei-templates -duc (never -nt, which narrows the scan) and
# never downloads anything (no network in the C profile, proxy-only in the web profile).
# Checksum-verified twice: against the digest pinned above and against the release's own
# checksums file.
RUN set -eux; cd /tmp; \
    curl -fsSLo "nuclei-templates-${NUCLEI_TEMPLATES_VERSION}.tar.gz" \
      "https://github.com/projectdiscovery/nuclei-templates/archive/refs/tags/v${NUCLEI_TEMPLATES_VERSION}.tar.gz"; \
    echo "${NUCLEI_TEMPLATES_SHA256}  nuclei-templates-${NUCLEI_TEMPLATES_VERSION}.tar.gz" | sha256sum -c -; \
    curl -fsSLo checksums-templates.txt \
      "https://github.com/projectdiscovery/nuclei-templates/releases/download/v${NUCLEI_TEMPLATES_VERSION}/nuclei-templates-${NUCLEI_TEMPLATES_VERSION}_checksums.txt"; \
    grep -E "  nuclei-templates-${NUCLEI_TEMPLATES_VERSION}\.tar\.gz$" checksums-templates.txt | sha256sum -c -; \
    tar -xzf "nuclei-templates-${NUCLEI_TEMPLATES_VERSION}.tar.gz" -C /opt; \
    mv "/opt/nuclei-templates-${NUCLEI_TEMPLATES_VERSION}" /opt/nuclei-templates; \
    rm -f "nuclei-templates-${NUCLEI_TEMPLATES_VERSION}.tar.gz" checksums-templates.txt

# frida-tools and its dependencies are hash-pinned (see requirements-frida.txt).
COPY requirements-frida.txt /tmp/requirements-frida.txt
RUN pip3 install --no-cache-dir --break-system-packages --require-hashes \
      -r /tmp/requirements-frida.txt \
 && rm -f /tmp/requirements-frida.txt

COPY gen-proxy-conf.py egress_proxy.py /opt/sandbox/

WORKDIR /work
