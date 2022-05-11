FROM debian:stretch
LABEL maintainer="Yerbas Developers <dev@yerbas.org>"
LABEL description="Dockerised YerbasCore, built from Travis"

RUN apt-get update && apt-get -y upgrade && apt-get clean && rm -fr /var/cache/apt/*

COPY bin/* /usr/bin/
