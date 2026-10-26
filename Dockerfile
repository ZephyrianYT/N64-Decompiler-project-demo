# n64lab toolchain in a box: everything needed to build homebrew ROMs,
# recompile ROMs, cross-compile Windows .exe files and run the tests.
#
#   docker build -t n64lab .
#   docker run --rm -v "$PWD:/work" -u "$(id -u):$(id -g)" n64lab recomp game.z64 --build --target windows
#   docker run --rm -p 8064:8064 -v "$PWD:/work" n64lab ui --host 0.0.0.0     # web UI
#
# Build with --build-arg WITH_WINE=1 to also run the Windows test under Wine.
FROM ubuntu:24.04

ARG WITH_WINE=0
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        python3 clang lld llvm gcc libc6-dev make gcc-mingw-w64-x86-64 \
 && if [ "$WITH_WINE" = "1" ]; then apt-get install -y --no-install-recommends wine64; fi \
 && rm -rf /var/lib/apt/lists/*

COPY n64lab /opt/n64lab/n64lab
COPY tests /opt/n64lab/tests
COPY examples /opt/n64lab/examples

# Python never needs to write next to the code, so the image works as any user.
ENV PYTHONPATH=/opt/n64lab \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    WINEDEBUG=-all

WORKDIR /work
EXPOSE 8064
ENTRYPOINT ["python3", "-m", "n64lab"]
CMD ["--help"]
