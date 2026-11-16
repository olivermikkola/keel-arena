#!/bin/sh
set -eu
cp /solution/services.json /workspace/manifests/services.json
cp /solution/target.env /workspace/deploy/target.env
cp /solution/release_bundle.json /workspace/release_bundle.json
