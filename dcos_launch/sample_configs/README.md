# DC/OS Launch Configuration YAML
## Design Intention
The intention of this configuration file is to provide an interface by which
all deployments of DC/OS, regardless of provider, have a similar format, thus
complementing the goal of dcos-launch to provide a single tool for launching
across a variety of provider APIs.

## Supported Deployments and Examples
- [Simple AWS Cloudformation](aws-cf.yaml)
- [Zen AWS Cloudformation](aws-zen-cf.yaml)
- [Onprem Install on AWS Bare Cluster](aws-onprem.yaml)
- [Azure Template Deployment](azure.yaml)

## Keywords and Definitions
### Required Fields
* `launch_config_version`: this is still a tool under active development and as such a strict version specifier must be included
* `deployment_name`: The name of the cloud resource that will be provided by `dcos-launch`
* `provider`: Which of the DC/OS provisioning methods will be used in this deployment. May be one of `aws`, `azure`, or `onprem`
  * `aws`: Uses Amazon Web Services (AWS) CloudFormation console. Supports both zen and simple templates. (Can only be used with `platform: aws`. Requires: `template_url`, `template_parameters`
  * `azure`: Uses Azure Resource Manager deployment templates. Supports both ACS (Azure Container Service) and DC/OS templates. (Can only be used with `platform: azure`. Requires `template_url`, and `template_parameters`
  * `onprem`: Uses the DC/OS bash installer to orchestrate a deployment on arbitrary hosts of a bare cluster. Requires `num_masters`, `num_private_agents`, `num_public_agents`, `installer_url`, `instance_type`, `os_name`, and `dcos_config`

### Credentials
Credentials should be kept secure and as such, they are read exclusively through the environment.
* AWS: Must set `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`. Can optionally provide `AWS_REGION` which can be set as `aws_region` in the config.
* Azure: Must set `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`. Can optionally provide `AZURE_LOCATION` which can be set as `azure_location` in the config
* GCE: Must set either `GCE_CREDENTIALS` to your JSON service account credentials or `GCE_CREDENTIALS_PATH` to the path of the file containing those JSON credentials.

### Conditionally Required Fields
* `ssh_user`: If `provider: onprem` is used, then the host VM configuration is known to dcos-launch and this value will be calculated. Otherwise, it should always be supplied, and must be supplied for `provider: onprem`
* `ssh_private_key_filename`: If `key_helper` is `true` then this field cannot be supplied. Otherwise it should always be specified, and it is absolutely required for `onprem` deploy
* `aws_key_name`: If `key_helper: false` and `provider: onprem` and `platform: aws`, then a pre-existing EC2 SSH KeyPair must be supplied for launching the VPC
_Note_: DC/OS deployed from aws or azure provider do not technically need `ssh_user` or `ssh_private_key_filename`. However, without this additional data, the integration tests will not be trigger-able from dcos-launch. Thus, it is not recommended, but allowable, to omit these fields when not using the onprem provider

### Options
* `key_helper`: generate private SSH keys for the underlying hosts if `true`. In `platform: aws`, this means the user does not have to supply `KeyName` in the template parameters and dcos-launch will fill it in. Similarly, in `platform: azure`, `sshRSAPublicKey` is populated automatically. In the aws case, this key will be deleted from EC2 when the deployment is deleted with dcos-launch
* `zen_helper`: only to be used with `provider: aws` and zen templates. If `true`, then the network prerequisites for launching a zen cluster will be provided if missing. The resources potentially covered are: Vpc, InternetGateway, PrivateSubnet, and PublicSubnet. As with `key_helper`, these resources will be deleted if dcos-launch is used for destroying the deployment
* `disable_rollback` (for AWS clusters): (`true` or `false`) This is false by default if omitted. Disabling rollback will prevent your cluster from being garbage-collected, so make sure you delete it when you are done. See [here](../README.md) for instructions on how to delete the cluster if you have enabled rollback protection.

### Support
* `onprem` can only be provisioned via `aws` platform
