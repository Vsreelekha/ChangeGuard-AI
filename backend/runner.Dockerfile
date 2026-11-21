# Build from the repository root:
# docker build -f backend/runner.Dockerfile -t changeguard-runner:latest .
FROM python:3.12-slim

# Match the backend's declared pytest minimum without adding project-specific
# dependencies or copying project files into this image.
RUN python -m pip install --no-cache-dir "pytest>=8.0.0"

# TestRunnerService supplies the read-only /app mount and working directory.
# No ENTRYPOINT is set so Docker can execute its pytest command directly.
