#!/bin/bash
docker build -t reflexer/auction-keeper .
echo "$DOCKER_PASSWORD" | docker login -u "$DOCKER_USERNAME" --password-stdin
docker push reflexer/auction-keeper
