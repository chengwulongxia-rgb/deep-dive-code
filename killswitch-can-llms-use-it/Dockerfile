# syntax=docker/dockerfile:1
# Upstream source and the Rust build environment are pinned independently.
FROM rust:1.95-slim-bookworm@sha256:d7482085ff5b415f84dba5647ae71606650bdef00db7aeb69f4b3d170c3e4082 AS build
ADD --checksum=sha256:e139acfce70e1d556c386b8d77d72f4a308e7d2c7957bdd3ded3ffb36306791c https://codeload.github.com/dom96/KillSwitch/tar.gz/44eabb04db0e114883da2a60e87d2d53b576b212 /tmp/upstream.tar.gz
WORKDIR /app
RUN tar -xzf /tmp/upstream.tar.gz --strip-components=1 -C /app && cargo build --locked --release

FROM rust:1.95-slim-bookworm@sha256:d7482085ff5b415f84dba5647ae71606650bdef00db7aeb69f4b3d170c3e4082
COPY --from=build /app/target/release/killswitch /usr/local/bin/killswitch
USER 65534:65534
WORKDIR /examples
ENTRYPOINT ["/usr/local/bin/killswitch"]
