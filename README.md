# dcos-test-utils
This library contains two major modules:
## `dcos_launch`
`dcos-launch` provides the capability to launch DC/OS with the three native providers:
* AWS Cloudformatiom
* Azure Resource Manager
* Onprem Installer

In the case of the onprem provider, `dcos-launch` provides the capability to create a simple, homogeneous cluster of hosts of a given OS on which to perform an "onprem" installation.

The primary purpose of `dcos-launch` is to provide a turn-key deployment experience across a wide variety of configurations without having to handle any of the lower-level cloud APIs. As such, `dcos-launch` includes a [command line interface](dcos_launch/README.md) and is packaged as a pyinstaller binary for easy portability.

## `dcos_test_utils`
This module is the backend for the `dcos_api_session` object used as a test harness in the [DC/OS integration tests](http://github.com/dcos/dcos/tree/master/packages/dcos-integration-test/extra). More specifically, this module provides utilities that allow:
* Storing common URL elements repeated between requests to the same service
* Providing a DC/OS-authenticated API Client that can be wrapped and composed with API Mixins
* Wrappers for lower-level cloud-provider interactions on AWS and Azure
* Helper methods for managing Marathon and other DC/OS services

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
docker build -t dcos-test-utils-dev:latest .
```
and to then work in the environment:
```
docker run -it -v `pwd`:/dcos-test-utils dcos-test-utils-dev:latest /bin/bash
```

### Using the library interactively
```
python3.5 -m venv env
. env/bin/activate
pip3 install -r requirements.txt
python setup.py develop
```

## Running Tests with tox
Simply run `tox` and the following will be executed:
* flake8 for style errors
* pytest for unit tests
* pyinstaller for packaging dcos-launch

Note: these can be triggered individually by supplying the `-e` option to `tox`
