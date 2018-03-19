import json
import logging
import os
import re
import shutil
import subprocess
import uuid
import zipfile

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


class TerraformLauncher(util.AbstractLauncher):
    def __init__(self, config: dict, env=None):
        if env:
            os.environ.update(env)
        self.config = config
        self.init_dir = dcos_launch.config.expand_path('', self.config['init_dir'])
        self.cluster_profile_path = os.path.join(self.init_dir, 'desired_cluster_profile.tfvars')
        self.dcos_launch_root_dir = os.path.abspath(os.path.join(__file__, '..'))
        self.terraform_binary = os.path.join(self.dcos_launch_root_dir, 'terraform')
        self.default_priv_key_path = os.path.join(self.init_dir, 'key.pem')

    def terraform_cmd(self):
        """ Returns the right Terraform invocation command depending on whether it was installed by the user or by
        dcos-launch.
        """
        binary = self.terraform_binary
        if not os.path.exists(binary):
            binary = 'terraform'
        return binary

    def create(self):
        if os.path.exists(self.init_dir):
            raise util.LauncherError('ClusterAlreadyExists', "Either the cluster you are trying to create is already "
                                                             "running or the init_dir you specified in your config is "
                                                             "already used by another active cluster.")
        try:
            os.makedirs(self.init_dir)
            # Check if Terraform is installed by running 'terraform version'. If that fails, install Terraform.
            try:
                subprocess.run([self.terraform_cmd(), 'version'], check=True, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT)
            except FileNotFoundError:
                log.info('No Terraform installation detected. Terraform is now being installed.')
                self._install_terraform()

            try:
                if self.config['key_helper']:
                    self.key_helper()
                module = 'github.com/dcos/{}?ref={}/{}'.format(
                    'terraform-dcos-enterprise' if self.config['dcos-enterprise'] else 'terraform-dcos',
                    self.config['terraform_dcos_enterprise_version'] if self.config['dcos-enterprise'] else
                    self.config['terraform_dcos_version'], self.config['platform'])

                # Converting our YAML config to the required format. You can find an example of that format in the
                # Advance YAML Configuration" section here:
                # https://github.com/mesosphere/terraform-dcos-enterprise/tree/master/aws
                with open(self.cluster_profile_path, 'w') as file:
                    for k, v in self.config['terraform_config'].items():
                        file.write(k + ' = ')
                        if type(k) is dict:
                            file.write('<<EOF\n{}\nEOF\n'.format(yaml.dump(v)))
                        else:
                            file.write('"{}"\n'.format(v))
                try:
                    subprocess.run([self.terraform_cmd(), 'init', '-from-module', module], cwd=self.init_dir,
                                   check=True, stderr=subprocess.STDOUT)
                    ssh_cmd, shell = self._ssh_agent_setup()
                    subprocess.run(ssh_cmd + [self.terraform_cmd(), 'apply', '-auto-approve', '-var-file',
                                   self.cluster_profile_path], cwd=self.init_dir, check=True,
                                   stderr=subprocess.STDOUT, shell=shell)
                except Exception as e:
                    self._delete_cluster()
                    raise e
            except Exception as e:
                self._remove_ssh_key_from_agent()
                raise e
        except Exception as e:
            self._remove_init_dir()
            raise e

        return self.config

    def _ssh_agent_setup(self):
        if not self.config['key_helper']:
            return [], False
        shell = False
        cmd = ['ssh-add', self.config['ssh_private_key_filename'], '&&']
        if 'SSH_AUTH_SOCK' not in os.environ:
            cmd = ['eval', '`ssh-agent -s`', '&&'] + cmd
            shell = True
            log.info('No ssh-agent running. Starting one...')
        return cmd, shell

    def _install_terraform(self):
        download_path = os.path.join(self.dcos_launch_root_dir, 'terraform.zip')
        try:
            with open(download_path, 'wb') as f:
                log.info('Downloading...')
                r = requests.get(self.config['terraform_tarball_url'])
                for chunk in r.iter_content(1024):
                    f.write(chunk)
            with zipfile.ZipFile(download_path, 'r') as tfm_zip:
                tfm_zip.extractall(self.dcos_launch_root_dir)
            os.chmod(self.terraform_binary, 0o100)
        finally:
            os.remove(download_path)
        log.info('Terraform installation complete.')

    def wait(self):
        """ Nothing to do here because unlike the other launchers, create() runs and also waits for a subprocess to
        finish instead of just sending an http request to a provider.
        """
        pass

    def delete(self):
        self._delete_cluster()
        self._remove_ssh_key_from_agent()
        self._remove_init_dir()

    def _delete_cluster(self):
        subprocess.run([self.terraform_cmd(), 'destroy', '-force', '-var-file', self.cluster_profile_path],
                       cwd=self.init_dir, check=True, stderr=subprocess.STDOUT)

    def _remove_init_dir(self):
        shutil.rmtree(self.init_dir, ignore_errors=True)

    def _remove_ssh_key_from_agent(self):
        if 'SSH_AUTH_SOCK' in os.environ:
            subprocess.run(['ssh-add', '-d', self.config['ssh_private_key_filename']], check=False,
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

    def key_helper(self):
        private_key, public_key = util.generate_rsa_keypair()
        with open(self.default_priv_key_path, 'wb') as f:
            f.write(private_key)
        os.chmod(self.default_priv_key_path, 0o600)
        self.config['ssh_private_key_filename'] = self.default_priv_key_path
        return public_key


class GcpLauncher(TerraformLauncher):
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
        if 'gcp_ssh_pub_key_file' not in self.config['terraform_config'] or \
                'ssh_private_key_filename' not in self.config:
            pub_key = super().key_helper()
            pub_key_file = os.path.join(self.init_dir, 'key.pub')
            with open(pub_key_file, 'wb') as f:
                f.write(pub_key)
            self.config['terraform_config']['gcp_ssh_pub_key_file'] = pub_key_file


class AzureLauncher(TerraformLauncher):
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
        if 'ssh_pub_key' not in self.config['terraform_config'] or \
                'ssh_private_key_filename' not in self.config:
            pub_key = super().key_helper()
            self.config['terraform_config']['ssh_pub_key'] = pub_key.decode('utf-8')


class AwsLauncher(TerraformLauncher):
    def key_helper(self):
        if 'ssh_key_name' not in self.config['terraform_config'] or \
                'ssh_private_key_filename' not in self.config:
            bw = aws.BotoWrapper(self.config['aws_region'])
            key_name = 'terraform-dcos-launch-' + str(uuid.uuid4())
            private_key = bw.create_key_pair(key_name)
            with open(self.default_priv_key_path, 'wb') as f:
                f.write(private_key)
            self.config['ssh_private_key_filename'] = self.default_priv_key_path
            self.config['terraform_config']['ssh_key_name'] = key_name
