#!/bin/sh
# Opcjonalny sposób pobrania tych samych obrazów przy limicie Docker Hub.
set -eu
for tag in postgres:17-trixie nginx:1.31.6 redis:8.4.2-trixie rabbitmq:4.2.5-management-alpine alpine:3.22.4 eclipse-temurin:21-jre python:3.8.20-bullseye; do
    docker pull "mirror.gcr.io/library/$tag"
    docker tag "mirror.gcr.io/library/$tag" "$tag"
done

