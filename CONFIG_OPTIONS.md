# dcos-launch configuration YAML

To see sample config files, see the [sample_configs](dcos_launch/sample_configs/) directory.

This is a WIP to more thoroughly document all the parameters. The code this is based off of is in [dcos_launch/config.py](https://github.com/dcos/dcos-launch/tree/master/dcos_launch/config.py). Please report any errors or unclear items.

TODO: blank template for each of the deployment types that contained all the possible params with blank values.

Here `optional` means you don't have to manually provide it in the config.yaml file, and that it will be set to the default value if not provided.

## Design Intention
The intention of this configuration file is to provide an interface by which
all deployments of DC/OS, regardless of provider, have a similar format, thus
complementing the goal of dcos-launch to provide a single tool for launching
across a variety of provider APIs.

## Supported Deployments and Examples

See [sample_configs](dcos_launch/sample_configs/) for a full list.

- [Simple AWS Cloudformation](dcos_launch/sample_configs/aws-cf.yaml)
- [Zen AWS Cloudformation](dcos_launch/sample_configs/aws-zen-cf.yaml)
- [Onprem Install on AWS Bare Cluster](dcos_launch/sample_configs/aws-onprem.yaml)
- [Azure Template Deployment](dcos_launch/sample_configs/azure.yaml)
- [Onprem Installation on Google Cloud Platform](dcos_launch/sample_configs/gcp-onprem-with-helper.yaml)
- [GCP Onprem with fault-domain helper](dcos_launch/sample_configs/gcp-onprem-with-fd-helper.yaml)

* `onprem` can only be provisioned via `aws` and `gcp` platforms
* DC/OS deployed from aws or azure provider do not technically need `ssh_user` or `ssh_private_key_filename`. However, without this additional data, the integration tests will not be trigger-able from dcos-launch. Thus, it is not recommended, but allowable, to omit these fields when not using the onprem provider

## Universal params

These options are for any config

### `provider`

string, required

Which provider you will deploy a cluster to.

* `aws`: Uses Amazon Web Services (AWS) CloudFormation console. Supports both zen and simple templates. (Can only be used with `platform: aws`. Requires: `template_url`, `template_parameters`
* `azure`: Uses Azure Resource Manager deployment templates. Supports both ACS (Azure Container Service) and DC/OS templates. (Can only be used with `platform: azure`. Requires `template_url`, and `template_parameters`
* `onprem`: Uses the DC/OS bash installer to orchestrate a deployment on arbitrary hosts of a bare cluster. Requires `num_masters`, `num_private_agents`, `num_public_agents`, `installer_url`, `instance_type`, `os_name`, and `dcos_config`


Allowed: aws, azure, acs-engine, onprem, gcp, terraform.

### `launch_config_version`

integer, required

This is still a tool under active development and as such a strict version specifier must be included. (Right now there is only v1.)

Allowed: 1

### `ssh_port`

integer, optional

What port to use on SSH.

Default: 22


### `ssh_private_key_filename`

string, optional (required if you are doing an onprem deploy)

This is required if you don't use `key_helper` or `ssh_private_key`.

If `key_helper: true` then this field cannot be supplied.

### `ssh_private_key`

string, optional

If this is not set and you are not using `key_helper`, you must provide `ssh_private_key_filename`.


### `ssh_user`

string, optional

Username to log into cluster with. If `provider: onprem` then the host VM configuraiton is known to dcos-launch and this value will be calculated based on `os_name`.

Default: core

### `key_helper`

boolean, optional

Generate private SSH keys for the underlying hosts if `true`. In `platform: aws`, this means the user does not have to supply `KeyName` in the template parameters and dcos-launch will fill it in. Similarly, in `platform: azure`, `sshRSAPublicKey` is populated automatically. In the aws case, this key will be deleted from EC2 when the deployment is deleted with dcos-launch

Default: false

### `zen_helper`

boolean, optional

Only to be used with `provider: aws` and zen templates. If `true`, then the network prerequisites for launching a zen cluster will be provided if missing. The resources potentially covered are: Vpc, InternetGateway, PrivateSubnet, and PublicSubnet. As with `key_helper`, these resources will be deleted if dcos-launch is used for destroying the deployment.

Default: false

### `tags`

dict, optional

Arbitrary tags to set on your deployment. This can be anything (subject to tag length restrictions according to which provider you're deploying on) as dcos-launch does not do anything with these other than pass them through.

One example on how to use this would be setting `KubernetesCluster` tags when deploying via AWS CloudFormation templates (these are [required](https://github.com/kubernetes/kubernetes/blob/70a8ea5817ec412ae9f647a060cb93c55ac0e311/docs/design/aws_under_the_hood.md#tagging) if the cluster is running k8s).

Note that the `expiration` tags in some of the example configurations are something meant to run with internal Mesosphere services that garbage collect clusters (e.g. `expiration: 4h` creates a cluster that will be deleted after 4 hours, whereas leaving this blank will default to the cluster being deleted after 2 hours). An option to update tags after a cluster has been deployed is in the backlog.

## Template-based deploy params

These params should be present if you are deploying with a template.

### `template_url`

string, required

URL of template to use. E.g. should resolve to a page with a CloudFormation template if you are deploying on AWS.

### `template_parameters`

dict, required

Parameters that should be injected into the template you are using. Example params for an AWS template:

```
template_parameters:
    AdminLocation: 0.0.0.0/0
    PublicSlaveInstanceCount: 1
    SlaveInstanceCount: 2
    DefaultInstanceType: m4.large
```

## Onprem deploy params

### `deployment_name`

string, required

The name of the cloud resource that will be provided by `dcos-launch`. E.g. if you are deploying with an AWS CloudFormation template, then this will be the name of your stack.

### `platform`

string, required

Allowed: aws, gcp, gce

### `installer_url`

string, required

URL to the DC/OS installer for the version of DC/OS you want to use. For latest stable open source DC/OS, this would be `https://downloads.dcos.io/dcos/stable/dcos_generate_config.sh`.

### `installer_port`

integer, optional

Default: 9000

### `num_private_agents`

integer, optional

How many private agents the cluster should have.

Default: 0

### `num_public_agents`

integer, optional

Default: 0

### `num_masters`

integer, required

Number of DC/OS masters

Allowed: 1, 3, 5, 7, 9

### `dcos_config`

dict, required

Config options for DC/OS itself (not options about resources for the provider).

Params that can be nested include:

- `ip_detect_filename`
- `ip_detect_public_filename`
- `fault_domain_detect_filename`
- `license_key_filename`

but it will also accept other options (TODO: Where are these defined?)

```
dcos_config:
    cluster_name: My Awesome DC/OS
    resolvers:
        - 8.8.4.4
        - 8.8.8.8
    dns_search: mesos
    master_discovery: static
```

### `genconf_dir`

string, optional

Default: genconf

### `fault_domain_helper`

dict, optional

Items in the dict should have dicts containing:

- `num_zones` int, required, default true
- `num_private_agents`, int, required, default 0
- `num_public_agents`, int, required, default 0
- `local`, boolean, required, default false

Only to be used with `provider: onprem`. This option allows defining an arbitrary number of named regions by creating a spoofed fault-domain-detect script. Each region can configure the number of private agents, public agents, and sub-zones. One region *must* declared with `local: true` to designate it as the region which will host the masters. Agents are assigned distributed evenly amongst the zones within a region per a given role (master/private/public). Do not set the `num_private_agents` and `num_public_agents` in the top-level config. These values will computed automatically from the numbers you provide in the fault_domain_helper.
For example consider this fault domain helper:
```
num_masters: 3
fault_domain_helper:
    USA:
        num_zones: 2
        num_private_agents: 3
        local: true
    Germany:
        num_zones: 3
        num_public_agents: 2
        num_private_agents: 4
    Europe:
        num_private_agents: 1
```
will produce the following region/zones:
```
USA-1:
    masters: 2
    private_agents: 1
USA-2:
    masters: 1
    private_agents: 2
Germany-1:
    public_agents: 1
    private_agents: 1
Germany-2:
    public_agents: 1
    private_agents: 1
Germany-3:
    public_agents: 0
    private_agents: 2
Europe-1:
    private_agents: 1
```

### `prereqs_script_filename`

string, required if `install_rereqs` is true

If the image you are going to be installing DC/OS on needs requirements (e.g. Docker) installed before running the installer script, provide a file to run to install those here.

Default: dcos_launch/scripts/install_prereqs.sh

### `install_prereqs`

boolean, optional

Do DC/OS [system requirements](https://docs.mesosphere.com/1.11/installing-upgrading/custom/system-requirements/) need to be installed before installing DC/OS? 

Default: false

### `onprem_install_parallelism`

integer, optional

Default: 10


## AWS onprem params

### `aws_key_name`

string, required if `key_helper:false` and `provider:aws` and `platform:aws`

Pre-existing EC2 SSH KeyPair to be supplied for launching the VPC

### `os_name`

string, optional (you can set the machine image directly with `instance_ami`)

Default: `cent-os-7-dcos-prereqs`

Allowed: see `OS_AMIS` in dcos_launch/aws.py

### `instance_type`

string, required

E.g. m4.large

### `instance_device_name`

string, required

Default: `/dev/xvda` if coreos else `/dev/sda1`

### `admin_location`

string, required

Default: `0.0.0.0/0`

### `bootstrap_ssh_user`

string, required (if not set, this will be set based on `bootstrap_os_name`)

### `ssh_user`

string, required (if not set, will be set based on `os_name`)

### `aws_block_device_mappings`

list of dicts, optional

### `iam_role_permissions`

list of dict with keys `Resource`, `Action`, `Effect`, optional



## ACS (Azure) deploy params 

:warning: TODO: descriptions

### `deployment_name`

string, required

### `acs_engine_tarball_url`

string, optional

Default: 'https://github.com/Azure/acs-engine/releases/download/v0.12.1/acs-engine-v0.12.1-<sys.platform>-amd64.tar.gz'

### `acs_tempalte_filename`

string, optional

### `platform`
string, optional

Default: Azure

### `ssh_public_key`

string, optional

### `num_masters`

integer, required

Allowed: 1, 3, 5, 7, 9

### `master_vm_size`

string, optional

Default: Standard_D2_v2

### `num_windows_private_agents`

integer, optional

Default: 0

### `windows_private_vm_size`

string, optional

Default: Standard_D2_v2

### `num_windows_public_agents`

integer, optional

Default: 0

### `windows_public_vm_size`

string, optional

Default: Standard_D2_v2

### `num_linux_private_agents`

integer, optional

Default: 0

### `linux_private_vm_size`

string, optional

Default: Standard_D2_v2

### `num_linux_public_agents`

integer, optional

Default: 0

### `linux_public_vm_size`

string, optional

Default: Standard_D2_v2

### `windows_admin_user`

string, optional

Default azureuser

### `windows_admin_password`

string, optional

Default: Replacepassword123

### `linux_admin_user`

string, optional

Default: azureuser

### `template_parameters`

dict, optional?

### `dcos_linux_bootstrap_url`

string, optional

### `windows_image_source_url`

string, optional

### `dcos_linux_repository_url`

string, optional

### `dcos_linux_cluster_package_list_id`

string, optional

### `provider_package_id`

string, optional


## GCP (Google Cloud Platform) deploy params

:warning: TODO: descriptions

### `machine_type`

string, optional

Default: n1-standard-4

### `os_name`

string, optional

To see all image families: https://cloud.google.com/compute/docs/images

Default: coreos

### `source_image`

string, optional

Default: family/<os_name>

### `image_project`

string, optional

### `ssh_public_key`

string, optional

### `disk_size`

integer, optional

Default: 42

### `disk_type`

string, optional

Default: pd-ssd

### `disable_updates`

boolean, optional

Default: false

### `use_preemptible_vms`

boolean, optional

Default: False

## Terraform params

### `dcos-enterprise`

boolean

Are you installing Enterprise DC/OS (not open source DC/OS)?

Default: false

### `terraform_version`

string, optional

Default: latest Terraform

### `terraform_tarball_url`

string, optional

Defaults: `htts://releases.hashicorp.com/terraform/<terraform_version>/terraform_<terraform_version>_<system platform>_amd64.zip`

### `platform`

string, required

Allowed: aws, gcp, gce, azure

### `terraform_config`

dict, optional

Default: empty dict

### `init_dir`

string, optional

Default: `terraform-init-<uuid4>`

### `terraform_dcos_version`

string, optional

Default: master

### `terraform_dcos_enterprise_version`

string, optional

Default: master

### `key_helper`

boolean, optional

