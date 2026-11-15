# Build only from an operator-provided immutable image containing this pinned
# Lean toolchain and lake. No unpinned default base image is silently selected.
ARG LEAN_BASE_IMAGE
FROM ${LEAN_BASE_IMAGE}
USER root
COPY toolchain/ /opt/lean/
ENV PATH="/opt/lean/bin:${PATH}"
WORKDIR /project
ENTRYPOINT []
CMD ["lake", "env", "lean", "--version"]
