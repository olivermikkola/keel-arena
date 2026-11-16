FROM python:3.12-slim-trixie@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /workspace
COPY workspace/changelogs/v2.4.md /workspace/changelogs/v2.4.md
COPY workspace/checks/verify_deps.py /workspace/checks/verify_deps.py
COPY workspace/deploy/target.env /workspace/deploy/target.env
COPY workspace/manifests/services.json /workspace/manifests/services.json
