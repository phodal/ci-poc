FROM scratch
COPY demo /demo
USER 65532:65532
ENV PATH=/usr/bin:/bin LISTEN_ADDR=0.0.0.0:8080
ENTRYPOINT ["/demo"]
