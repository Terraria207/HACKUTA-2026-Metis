# Build only from an operator-provided immutable image containing this pinned
# Lean toolchain and lake. No unpinned default base image is silently selected.
ARG LEAN_BASE_IMAGE
FROM ${LEAN_BASE_IMAGE}
USER root
# Lake reads dependency Git metadata even for `lake env`. The trusted project is
# mounted read-only and owned by the host, while compilation runs as nobody.
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory '*'
COPY toolchain/ /opt/lean/
ENV PATH="/opt/lean/bin:${PATH}"
WORKDIR /project
ENTRYPOINT []
CMD ["lake", "env", "lean", "--version"]
