#!/bin/bash
docker run -it -v `pwd`:/dcos-launch mesosphere/dcos-launch $@
