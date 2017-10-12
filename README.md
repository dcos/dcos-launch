# dcos-launch

`dcos-launch` provides the capability to launch DC/OS with the three native providers:
* AWS Cloudformatiom
* Azure Resource Manager
* Onprem Installer

In the case of the onprem provider, `dcos-launch` provides the capability to create a simple, homogeneous cluster of hosts of a given OS on which to perform an "onprem" installation.

The primary purpose of `dcos-launch` is to provide a turn-key deployment experience across a wide variety of configurations without having to handle any of the lower-level cloud APIs.

## Installation

### System Requirements

* local SSH client at /usr/bin/ssh

### Linux binary

`dcos-launch` is packaged as a [pyinstaller binary](https://downloads.dcos.io/dcos-launch/bin/linux/dcos-launch) for easy portability on linux-based systems.

### Python-based (development) installation

An OS-agnostic Python-based installation is also possible, and useful for helping develop `dcos-launch`.  To install on any Python 3-based system:
```
python3 -m venv env
. env/bin/activate
pip3 install -r requirements.txt
python3 setup.py develop
```

## Developing

Additional requirements to develop and/or build this library:
* tox
* virtualenv
* OpenSSL 1.0.2g or greater (for exporting the dcos-launch binary)

### Developing in a Docker container

If you do not have a linux environment or for whatever reason your local SSH client is not compatible with this repository, you can simply develop with the included Dockerfile.

To build to development container:
```
docker build -t dcos-launch-dev:latest .
```
and to then work in the environment:
```
docker run -it -v `pwd`:/dcos-launch dcos-launch-dev:latest /bin/bash
```

### Running Tests with tox

Simply run `tox` and the following will be executed:
* flake8 for style errors
* pytest for unit tests
* pyinstaller for packaging dcos-launch

Note: these can be triggered individually by supplying the `-e` option to `tox`
