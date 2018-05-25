# dcos-launch

`dcos-launch` is a portable linux executable that provides the capability to create, wait for provisioning, describe, test/validate, and destroy an arbitrary DC/OS cluster with the three native providers:

* AWS Cloudformatiom
* Azure Resource Manager
* Onprem Installer

In the case of the onprem provider, `dcos-launch` provides the capability to create a simple, homogeneous cluster of hosts of a given OS on which to perform an "onprem" installation.

The primary purpose of `dcos-launch` is to provide a turn-key deployment experience across a wide variety of configurations without having to handle any of the lower-level cloud APIs.

# Usage

`dcos-launch` is backwards compatible to older verions of DC/OS. Thus, it can be used as a development or CI tool for deploying clusters into your workflow.

## Requirements
* Linux operating system
* SSH client installed on localhost

### Credentials

You must set environment variables depending on the platform and provider your clusters will be running on. Credentials should be kept secure and as such, they are read exclusively through the environment.

#### AWS

If you are part of the Mesosphere org:

1. Install [maws]() (download the binary, run through all the steps in the installation section of the README)
2. Verify that maws is installed
    a. `which maws`
    b. `maws ls`
3. Log into your AWS account via maws
    a. `eval $(maws li <AWS-ACCOUNT>)` Where `<AWS-ACCOUNT>` is one of the outputs of `maws li`.
    b. It should automatically redirect you to your browser for auth, then return a confirmation message that it has successfully retrieved your credentials.

Otherwise:

Set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` as environment variables, optionally with `AWS_REGION` in your shell or in `~/.aws/credentials`.

#### GCP

Set either `GCE_CREDENTIALS` to your JSON service account credentials or `GOOGLE_APPLICATION_CREDENTIALS` to the paht of hte file containing those JSON credentials.

#### Azure

Use the `az` CLI or

1. Create an Azure Service Principal
2. Set the following environment variables with the keys from your service principal:

```
AZURE_SUBSCRIPTION_ID
AZURE_CLIENT_ID
AZURE_CLIENT_SECRET
AZURE_TENANT_ID
```

## Config file

dcos-launch takes a YAML file of provisioning options. See [config docs](CONFIG_OPTIONS.md).

## Installation

### Binary installation

`dcos-launch` is packaged as a [PyInstaller](https://www.pyinstaller.org/) binary for easy portability.

* [Linux](https://downloads.dcos.io/dcos-launch/bin/linux/dcos-launch)
* [Mac](https://downloads.dcos.io/dcos-launch/bin/mac/dcos-launch)

See the Developing section for instructions on how to install a development environment locally.

## Features
`dcos-launch` provides the following:
* Consistent interface: launching on Azure or AWS can involve finding a suitable client API and then sifting through hundreds of specific API calls to find the combination that will allow deploying DC/OS. `dcos-launch` has the exact methods required to take a DC/OS build artifact and deploy it to an arbitrary provider with no other tools.
* Turn-key deployment: The only input required by `dcos-launch` is the [launch config](CONFIG_OPTIONS.md). In cases where artifacts are required to deploy DC/OS (e.g. SSH keys), `dcos-launch` provids helpers to automatically create and clean up those extra artifacts.
* Portable shipping: `dcos-launch` is shipped as a frozen python binary so that you never need to be concerned with maintaining an extremely specific development environment or deployment framework.
* Build verification: besides launching clusters, `dcos-launch` can test that the provisioned cluster is healthy through the `pytest` subcommand. `dcos-launch` is capable of describing the cluster topology and verifying that the expected cluster is present. To learn more about the testing suite triggered by this command, see: [dcos-integration-test](http://github.com/dcos/dcos/tree/master/packages/dcos-integration-test/extra)
* Programmatic consumption: all information necessary to interact with a given deployment configuration created by `dcos-launch` is contained in the generated `cluster_info.json` file. This allows dependent CI tasks to run other tests, describe the cluster, or completely delete the cluster

## Commands
### `dcos-launch create`
Consumes a [launch config file](CONFIG_OPTIONS.md) file, performs basic validation on the deployment parameters, and then signals the deployment provider to begin deployment. By default, `dcos-launch` will expect a launch config at `config.yaml` but any arbitrary path can be passed with the `-c` option. If creation is triggered successfully, then a `cluster_info.json` file will be produced for use with other `dcos-launch` commands. This path is also configurable via the `-i` command line option

In the case of third-party provisioning (provider is AWS or Azure), the cluster will eventually finish deploying with no further action. In the case of onprem provisioning, `dcos-launch` needs to partially drive the deployment process, so the `dcos-launch create` command only triggers creation of the underlying bare hosts, while `dcos-launch wait` will step through the DC/OS installer stages.

### `dcos-launch wait`
Reads the cluster info from the create command to see if the deployment is ready and blocks if the cluster is not ready. In the case of third-party providers, this command will query their deployment service and surface any errors that may have derailied the deployment. In the case of onprem provisioning, there are multiple, triggerable stages in deployment, so the wait command *must* be used to complete the deployment.

### `dcos-launch describe`
Reads the cluster info and outputs the essential parameters of the cluster. E.g. master IPs, agent IPs, load balancer addresses. Additionally, the STDOUT stream is formatted in JSON so that the output can be piped into another process or tools like `jq` can be used to pull out specific paramters.

### `dcos-launch pytest`
Reads the cluster info and runs the [dcos-integration-test](http://github.com/dcos/dcos/tree/master/packages/dcos-integration-test/extra) package. This is the same test suite used to validate DC/OS pull requests. Additionally, arbitrary arguments and environment variables may be added to the pytest command. For example, if one only wants to run the cluster composition test to see if the cluster is up: `dcos-launch pytest -- test_composition.py`. Anything input after `--` will be injected after `pytest` (which is naturally run without options).

### `dcos-launch delete`
Reads the cluster info and triggers the destruction of the deployment. In cases where `dcos-launch` provided third-party dependencies via a helper (`zen_helper` or `key_helper` for AWS), `delete` will block until all those resources have been removed.

## Options

### `-c PATH`
Path to your `config.yaml`. By default, `dcos-launch` assumes `config.yaml` in your working directory to be the config file path, but this option allows specifying a specific file. Note: this option is only used for `create`. E.g. `dcos-launch create -c aws_cf_config.yaml`

### `-i PATH`
Path to your `cluster_info.json`. By default, the info path is set as `cluster_info.json`, but this option allows overriding. Thus, a user may have multiple configurations and cluster infos simultaneously. Note: in the case of create, this option indicates where the JSON will be created whereas for the other commands it indicated where the JSON is read from. E.g. `dcos-launch delete -i onprem_cluster_info.json`

### `-L LEVEL`
Log level. By default, the log level is info. By using this option you will also be able to control the test logging level in addition to the provisioning/launch logging level. Choices are: debug, info, warning, error, exception. E.g. `dcos-launch wait -L debug`

### `-e LIST`
Custom environment variables to include. This option allows passing through environment variables from the current environment into the testing environment. The list is comma delimited and any provided environment variables will override the automatically injected ones. Required variables that are automatically injected include `MASTER_HOSTS`, `SLAVE_HOSTS`, `PUBLIC_MASTER_HOSTS`, `PUBLIC_SLAVE_HOSTS`, `DCOS_DNS_ADDRESS`. E.g. `dcos-launch pytest -e MASTER_HOSTS -- test_composition.py`, `ENABLE_RESILIENCY_TESTS=true dcos-launch pytest -e ENABLE_RESILIENCY_TESTS,MASTER_HOSTS -- test_applications.py`

## Quickstart Example


0. Install dcos-launch (see Usage > Installation > Binary Installation).

1. Make a file config.yaml. Here is one based off [aws-cf-with-helper.yaml](dcos_launch/sample_configs/aws-cf-with-helper.yaml) in the sample_configs directory which will deploy a bleeding-edge open-source DC/OS cluster on AWS CloudFormation with 1 private agent and 2 public agents, and one master. Note that `deployment_name` needs to be unique within your AWS account, so you may want to append the date.

```
---
launch_config_version: 1
deployment_name: aws-cf-with-helper-test
template_url: https://s3.amazonaws.com/downloads.dcos.io/dcos/testing/master/cloudformation/single-master.cloudformation.json
provider: aws
aws_region: us-west-2
key_helper: true
template_parameters:
    AdminLocation: 0.0.0.0/0
    PublicSlaveInstanceCount: 2
    SlaveInstanceCount: 1
ssh_user: core

```

2. Make sure you have your AWS credentials set in your environment (see Usage > Requirements > Credentials).

3. `dcos-launch create` (config.yaml is the default config file name, so you don't have to provide it). This will send the command to deploy your cluster.

4. `dcos-launch wait`. This will loop until your cluster is finished deploying. If you are doing an onprem install (not the case in the config used here) then this step will also install DC/OS. 

5. Try running the pytests in `dcos-integration-test` package that comes with DC/OS on your cluster. `dcos-launch -L error pytest -- test_composition.py` will run a test that checks that the cluster is up in verbose mode (-vv), including printing (-s) stdout. Note that if you are deploying an enterprise cluster, you will need to inject environment variables like `DCOS_LOGIN_UNAME=thelogin DCOS_LOGIN_PW=thepassword dcos-launch pytest -e DCOS_LOGIN_UNAME,DCOS_LOGIN_PW -- -vv`.

6. If you have `jq` (CLI JSON parser) installed, you can grab the master node's IP with `dcos-launch describe | jq -r .masters[0].public_ip`. `describe` will get the node IP addresses of the cluster. To get the ssh_key  generated by the key_helper, use `cat cluster_info.json | jq -r .ssh_private_key > ssh_key; chmod 600 ssh_key`. SSH in with `ssh -i ssh_key core@<master_ip>`.

7. Run `dcos-launch delete` to delete your cluster.


# Developing

### Python-based (development) installation

An OS-agnostic Python-based installation is also possible, and useful for helping develop `dcos-launch`.  To install on any Python 3-based system:
```
python3 -m venv env
. env/bin/activate
pip3 install -r requirements.txt
python3 setup.py develop
```

## Requirements

Additional requirements to develop and/or build this library:
* tox
* virtualenv
* OpenSSL 1.0.2g or greater (for exporting the dcos-launch binary)

## Developing in a Docker container

If you do not have a linux environment or for whatever reason your local SSH client is not compatible with this repository, you can simply develop with the included Dockerfile.

To build to development container:
```
docker build -t dcos-launch-dev:latest .
```
and to then work in the environment:
```
docker run -it -v `pwd`:/dcos-launch dcos-launch-dev:latest /bin/bash
```

## Running Tests with tox

Simply run `tox` and the following will be executed:
* flake8 for style errors
* pytest for unit tests
* pyinstaller for packaging dcos-launch

Note: these can be triggered individually by supplying the `-e` option to `tox`

<details>
    This should be hidden!
</details>

:snake:

- [ ] check one
- [ ] check two