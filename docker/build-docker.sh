#!/usr/bin/env bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd $DIR/..

DOCKER_IMAGE=${DOCKER_IMAGE:-yerbas/yerbasd-develop}
DOCKER_TAG=${DOCKER_TAG:-latest}

BUILD_DIR=${BUILD_DIR:-.}

rm docker/bin/*
mkdir docker/bin
cp $BUILD_DIR/src/yerbasd docker/bin/
cp $BUILD_DIR/src/yerbas-cli docker/bin/
cp $BUILD_DIR/src/yerbas-tx docker/bin/
strip docker/bin/yerbasd
strip docker/bin/yerbas-cli
strip docker/bin/yerbas-tx

docker build --pull -t $DOCKER_IMAGE:$DOCKER_TAG -f docker/Dockerfile docker
