ARG PYTHON_BASE_IMAGE=quay.io/ansible/python-base:latest
ARG PYTHON_BUILDER_IMAGE=quay.io/ansible/python-builder:latest

FROM $PYTHON_BUILDER_IMAGE as builder
# =============================================================================
ARG ZUUL_SIBLINGS

# build this library (meaning ansible-builder)
COPY . /tmp/src
RUN assemble
FROM $PYTHON_BASE_IMAGE
# =============================================================================

COPY --from=builder /output/ /output
RUN /output/install-from-bindep && rm -rf /output

# move the assemble scripts themselves into this container
COPY --from=builder /usr/local/bin/assemble /usr/local/bin/assemble
COPY --from=builder /usr/local/bin/get-extras-packages /usr/local/bin/get-extras-packages

# building EEs require the install-from-bindep script, but not the rest of the /output folder
COPY --from=builder /output/install-from-bindep /output/install-from-bindep
