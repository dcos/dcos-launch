import json
import logging
import os
import re
import shutil
import subprocess
import uuid
import zipfile
from functools import wraps

import requests

import dcos_launch.config
import yaml
from dcos_launch import gcp, util
from dcos_launch.platforms import aws
from dcos_test_utils import helpers

log = logging.getLogger(__name__)
IP_REGEX = '(\d{1,3}.){3}\d{1,3}'
IP_LIST_REGEX = '\[[^\]]+\]'


def _get_ips(*arg, info: str) -> list:
    ips = []
    for prefix in arg:
        prefix += ' = '
        m = re.search('{}{}'.format(prefix, IP_REGEX), info)
        if m:
            ips.append(m.group(0)[len(prefix):])
        else:
            m = re.search('{}{}'.format(prefix, IP_LIST_REGEX), info)
            if m:
                # remove prefix
                s = m.group(0)[len(prefix):]
                # remove whitespace
                s = "".join(s.split())
                # remove brackets
                s = s[1:-1]
                ips += s.split(',')
    return ips


def _convert_to_describe_format(ips: list) -> list:
    return [{'private_ip': None, 'public_ip': ip} for ip in ips]


def catch_failed_init(f):
    @wraps(f)
    def handle_exception(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as e:
            shutil.rmtree(args[0].init_dir, ignore_errors=True)
            raise e
    return handle_exception


class TerraformLauncher(util.AbstractLauncher):
    def __init__(self, config: dict, env=None):
        if env:
            os.environ.update(env)
        self.config = config
        self.init_dir = dcos_launch.config.expand_path('', self.config['init_dir'])
        self.cluster_profile_path = os.path.join(self.init_dir, 'desired_cluster_profile.tfvars')
        self.priv_key_file = None
        self.dcos_launch_root_dir = os.path.dirname(os.path.join(os.path.abspath(__file__), '..'))
        self.terraform_binary = os.path.join(self.dcos_launch_root_dir, 'terraform')

    def terraform_cmd(self):
        """ Returns the right Terraform invocation command depending on whether it was installed by the user or by
        dcos-launch.
        """
        binary = self.terraform_binary
        if not os.path.exists(binary):
            binary = 'terraform'
        return binary

    def create(self):
        # create terraform directory
        if os.path.exists(self.init_dir):
            raise util.LauncherError('ClusterAlreadyExists', "Either the cluster you are trying to create is already "
                                                             "running or the init_dir you specified in your config is "
                                                             "already used by another active cluster.")
        # TODO if any of the below fails, teardown?
        os.makedirs(self.init_dir)

        # Check if Terraform is installed by running 'terraform version'. If that fails, install Terraform.
        try:
            subprocess.run([self.terraform_cmd(), 'version'], check=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT)
        except FileNotFoundError:
            log.info('No Terraform installation detected. Terraform is now being installed.')
            self._install_terraform()

        # TODO if any of the below fails, ssh-add -d?
        self.key_helper()
        module = 'github.com/dcos/{}?ref={}/{}'.format(
            'terraform-dcos-enterprise' if self.config['dcos-enterprise'] else 'terraform-dcos',
            self.config['terraform_dcos_enterprise_version'] if self.config['dcos-enterprise'] else
            self.config['terraform_dcos_version'], self.config['platform'])

        # Converting our YAML config to the required format. You can find an example of that format in the Advance
        # YAML Configuration" section here: https://github.com/mesosphere/terraform-dcos-enterprise/tree/master/aws
        with open(self.cluster_profile_path, 'w') as file:
            for k, v in self.config['terraform_config'].items():
                file.write(k + ' = ')
                if type(k) is dict:
                    file.write('<<EOF\n{}\nEOF\n'.format(yaml.dump(v)))
                else:
                    file.write('"{}"\n'.format(v))

        # TODO if any of the below fails, terraform destroy?
        subprocess.run([self.terraform_cmd(), 'init', '-from-module', module], cwd=self.init_dir, check=True,
                       stderr=subprocess.STDOUT)
        subprocess.run([self.terraform_cmd(), 'apply', '-auto-approve', '-var-file', self.cluster_profile_path],
                       cwd=self.init_dir, check=True, stderr=subprocess.STDOUT)

        return self.config

    def _install_terraform(self):
        download_path = 'terraform.tar.gz'
        with open(download_path, 'wb') as f:
            log.info('Downloading...')
            r = requests.get(self.config['terraform_tarball_url'])
            for chunk in r.iter_content(1024):
                f.write(chunk)
        with zipfile.ZipFile(download_path, 'r') as tfm_zip:
            tfm_zip.extractall(self.dcos_launch_root_dir)
        os.chmod(self.terraform_binary, 0o100)
        os.remove(download_path)
        log.info('Terraform installation complete.')

    def wait(self):
        """ Nothing to do here because unlike the other launchers, create() runs and also waits for a subprocess to
        finish instead of just sending an http request to a provider.
        """
        pass

    def delete(self):
        subprocess.run([self.terraform_cmd(), 'destroy', '-force', '-var-file', self.cluster_profile_path],
                       cwd=self.init_dir, check=True, stderr=subprocess.STDOUT)
        shutil.rmtree(self.init_dir, ignore_errors=True)
        if self.priv_key_file:
            subprocess.run(['ssh-add', '-d', self.priv_key_file], check=False,
                           stderr=subprocess.STDOUT)

    def describe(self) -> dict:
        """ Output example
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
        result = subprocess.run([self.terraform_cmd(), 'show'], cwd=self.init_dir, check=True, stdout=subprocess.PIPE)
        info = result.stdout.decode('utf-8')
        # crop the output to speed up regex
        info = info[info.find('Outputs:'):]

        private_agents_ips = _convert_to_describe_format(
            _get_ips('Mesos Agent Public IP', 'Private Agent Public IP Address', info=info))
        private_agents_gpu_addresses = _get_ips('GPU Private Public IP Address', info=info)
        for i in range(len(private_agents_gpu_addresses)):
            private_agents_ips[i]['GPU_address'] = private_agents_gpu_addresses[i]

        description = {
            'bootstrap_host': _convert_to_describe_format(_get_ips('Bootstrap Public IP Address', info=info)),
            'masters': _convert_to_describe_format(_get_ips('Mesos Master Public IP', info=info)),
            'private_agents': private_agents_ips,
            'public_agents': _convert_to_describe_format(_get_ips('Public Agent Public IP Address',
                                                                  'Mesos Public Agent Public IP', info=info))}

        master_elb_address = _get_ips('Master ELB Address', info=info)
        public_agent_elb_address = _get_ips('Public Agent ELB Address', info=info)

        if master_elb_address:
            description.update({'master_elb_address': master_elb_address[0]})
        if public_agent_elb_address:
            description.update({'public_agent_elb_address': public_agent_elb_address[0]})

        return description

    def _ssh_add(self, private_key: bytes):
        self.priv_key_file = helpers.session_tempfile(private_key)
        os.chmod(self.priv_key_file, 0o600)
        try:
            if 'SSH_AUTH_SOCK' not in os.environ:
                log.info('No ssh-agent running. Starting one...')
                subprocess.run(['eval', '`ssh-agent -s`'], check=True, stderr=subprocess.STDOUT)
            subprocess.run(['ssh-add', self.priv_key_file], check=True, stderr=subprocess.STDOUT)
        except Exception as e:
            raise util.LauncherError('KeyHelperFailed', "Make sure you have your operating system's keychain package "
                                                        "installed (e.g. 'brew install keychain' or 'apt-get install "
                                                        "keychain').")


class GcpLauncher(TerraformLauncher):
    @catch_failed_init
    def __init__(self, config: dict, env=None):
        super().__init__(config, env)
        # if gcp region is nowhere to be found, the default value in terraform-dcos will be used
        if 'gcp_region' not in self.config['terraform_config'] and 'GCE_ZONE' in os.environ:
            self.config['terraform_config']['gcp_region'] = util.set_from_env('GCE_ZONE')

        creds_string, creds_path = gcp.get_credentials(env)
        if not creds_path:
            creds_path = helpers.session_tempfile(creds_string)
        config['terraform_config']['gcp_credentials_key_file'] = creds_path
        if 'gcp_project' not in config['terraform_config']:
            config['terraform_config']['gcp_project'] = json.loads(creds_string)['project_id']

    def key_helper(self):
        if self.config['key_helper'] or 'gcp_ssh_pub_key_file' not in self.config['terraform_config']:
            private_key, public_key = util.generate_rsa_keypair()
            self._ssh_add(private_key)
            pub_key_file = helpers.session_tempfile(public_key)
            self.config['terraform_config']['gcp_ssh_pub_key_file'] = pub_key_file


class AzureLauncher(TerraformLauncher):
    @catch_failed_init
    def __init__(self, config: dict, env=None):
        super().__init__(config, env)
        dcos_launch.util.set_from_env('AZURE_SUBSCRIPTION_ID')
        dcos_launch.util.set_from_env('AZURE_CLIENT_ID')
        dcos_launch.util.set_from_env('AZURE_CLIENT_SECRET')
        dcos_launch.util.set_from_env('AZURE_TENANT_ID')
        # if azure region is nowhere to be found, the default value in terraform-dcos will be used
        if 'azure_region' not in self.config['terraform_config'] and 'AZURE_LOCATION' in os.environ:
            self.config['terraform_config']['azure_region'] = util.set_from_env('AZURE_LOCATION')

    def key_helper(self):
        if self.config['key_helper'] or 'ssh_pub_key' not in self.config['terraform_config']:
            private_key, public_key = util.generate_rsa_keypair()
            self._ssh_add(private_key)
            self.config['terraform_config']['ssh_pub_key'] = public_key.decode('utf-8')


class AwsLauncher(TerraformLauncher):
    @catch_failed_init
    def __init__(self, config: dict, env=None):
        super().__init__(config, env)
        creds_file = '~/.aws/credentials'
        if not os.path.exists(creds_file):
            if not os.path.exists('~/.aws'):
                os.makedirs('~/.aws')
            with open(creds_file, 'w') as file:
                file.writelines(['aws_access_key_id = ' + util.set_from_env('AWS_ACCESS_KEY_ID'),
                                 'aws_secret_access_key = ' + util.set_from_env('AWS_SECRET_ACCESS_KEY')])

    def key_helper(self):
        if self.config['key_helper'] or 'ssh_key_name' not in self.config['terraform_config']:
            bw = aws.BotoWrapper(self.config['aws_region'])
            key_name = 'terraform-dcos-launch-' + str(uuid.uuid4())
            private_key = bw.create_key_pair(key_name)
            self._ssh_add(private_key)
            self.config['terraform_config']['ssh_key_name'] = key_name
