from dcos_launch import util
import subprocess
import os
import json
import sys

# TODO pinning terraform-dcos is not enough because its tf_dcos_core dependency is not pinned. Create a branch on
# terraform-dcos that pins tf_dcos_core and replace TERRAFORM_DCOS_VERSION here by that branch name. Regularly update
# that branch with master.
TERRAFORM_DCOS_VERSION = 'cprovencher:max_owner_length'
TERRAFORM_DCOS_EE_VERSION = 'service_credentials_gcp2'
TERRAFORM_INIT_DIR = 'terraform-temp'
TERRAFORM_CONFIG_FILE = 'desired_cluster_profile.tfvars'
SAMPLE_OUTPUT = """
Outputs:

Bootstrap Public IP Address = 35.230.27.229
Master ELB Address = 35.230.34.40
Mesos Agent Public IP = [
    35.230.112.212,
    35.230.68.63
]
Mesos Master Public IP = [
    35.230.48.204
]
Mesos Public Agent Public IP = [
    35.197.122.209
]
Public Agent ELB Address = 35.230.52.188"""


class TerraformLauncher(util.AbstractLauncher):
    def __init__(self, config: dict, env=None):
        if env is None:
            env = os.environ.copy()

        if config['platform'] == 'azure':
            # TODO
            pass
        elif config['platform'] == 'aws':
            # TODO
            pass
        elif config['platform'] == 'gcp':
            if 'GCE_CREDENTIALS' in env:
                with open('gcp_service_creds.json', 'w') as file:
                    file.write(env['GCE_CREDENTIALS'])
                config['terraform']['gcp_credentials_key_file'] = os.path.abspath('gcp_service_creds.json')
            elif 'GOOGLE_APPLICATION_CREDENTIALS' in env:
                config['terraform']['gcp_credentials_key_file'] = env['GOOGLE_APPLICATION_CREDENTIALS']
            else:
                raise util.LauncherError(
                    'MissingParameter', 'Either GCE_CREDENTIALS or GOOGLE_APPLICATION_CREDENTIALS must be set in env')

            if 'gcp_project' not in config['terraform']:
                config['terraform']['gcp_project'] = json.load(
                    config['terraform']['gcp_credentials_key_file'])['project_id']
        else:
            raise util.LauncherError('InvalidPlatform', "allowed values: 'gcp', 'aws' and 'azure'")

        os.makedirs('tmp-terraform')
        module = 'github.com/dcos/{}?ref={}/{}'.format(
            'terraform-dcos-enterprise' if config['dcos-enterprise'] else 'terraform-dcos',
            TERRAFORM_DCOS_EE_VERSION if config['dcos-enterprise'] else TERRAFORM_DCOS_VERSION,
            config['platform'])
        util.run_subprocess_and_stream_output('terraform init -from-module {} {}'.format(module, TERRAFORM_INIT_DIR))

        with open(os.path.join(TERRAFORM_INIT_DIR, TERRAFORM_CONFIG_FILE)) as file:
            # TODO parse self.config['terraform'] and rewrite in appropriate format in 'file'
            pass

    def create(self):
        util.run_subprocess_and_stream_output(
            'terraform apply -auto-approve -var-file {} {}'.format(TERRAFORM_CONFIG_FILE, TERRAFORM_INIT_DIR))

    def wait(self):
        pass

    def delete(self):
        util.run_subprocess_and_stream_output(
            'terraform destroy -var-file {} {}'.format(TERRAFORM_CONFIG_FILE, TERRAFORM_INIT_DIR))

    def describe(self) -> dict:
        util.run_subprocess_and_stream_output(
            'terraform apply -auto-approve -var-file {} {}'.format(TERRAFORM_CONFIG_FILE, TERRAFORM_INIT_DIR))
        # TODO: parse output (see SAMPLE_OUTPUT) and return appropriate container
        return {}