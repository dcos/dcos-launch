# dcos-launch

`dcos-launch` provides the capability to launch DC/OS with the three native providers:
* AWS Cloudformatiom
* Azure Resource Manager
* Onprem Installer

In the case of the onprem provider, `dcos-launch` provides the capability to create a simple, homogeneous cluster of hosts of a given OS on which to perform an "onprem" installation.

The primary purpose of `dcos-launch` is to provide a turn-key deployment experience across a wide variety of configurations without having to handle any of the lower-level cloud APIs. As such, `dcos-launch` includes a [command line interface](dcos_launch/README.md) and is packaged as a pyinstaller [binary](https://downloads.dcos.io/dcos-launch/bin/linux/dcos-launch) for easy portability.

## System Requirements
* linux operating system
* local SSH client at /usr/bin/ssh

## Developing
Additional requirements to develop and/or build this library:
* tox
* virtualenv
* OpenSSL 1.0.2g or greater (for exporting the dcos-launch binary)

### Developing in a Docker container
If you do not have a linux environment or for whatever reason your local SSH client is not compatible with this repository, you can simply develop with the included Dockerfile.

To build to development container:
```
cd tests
docker build -t dcos-launch-dev:latest .
```
and to then work in the environment:
```
docker run -it -v `pwd`:/dcos-launch dcos-launch-dev:latest /bin/bash
```

### Using the library interactively
```
python3.5 -m venv env
. env/bin/activate
pip3 install -r requirements.txt
python setup.py develop
```
Also, a [Docker image](Dockerfile) is used to ship dcos-launch instead of a binary.
Note: dcos-launch requires the use of local file paths, so you will need to volume mount:
```
docker run -it -v /my/home/dir:/dcos-launch create
```
To make this slightly easier, use dcos-launch-docker.sh. Example:
```
mkdir foo
cat <<EOF > foo/config.yaml
---
launch_config_version: 1
provider: aws
...
EOF

./dcos-launch-docker.sh create -c foo/config.yaml
```

## Running Tests with tox
Simply run `tox` and the following will be executed:
* flake8 for style errors
* pytest for unit tests
* pyinstaller for packaging dcos-launch

Note: these can be triggered individually by supplying the `-e` option to `tox`
