FROM debian:stretch
LABEL maintainer="Yerbas Developers <yerbascore@gmail.com>"
LABEL description="Dockerised YerbasCore, built from Travis"

RUN apt-get update && apt-get -y upgrade && apt-get clean && rm -fr /var/cache/apt/*

COPY bin/* /usr/bin/
