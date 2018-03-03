import json
import os
import re
import shutil
import subprocess

import dcos_launch.config
import yaml
from dcos_launch import gcp, util
from dcos_test_utils import helpers
# from dcos_launch.platforms import aws

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
        self.config = config
        self.init_dir = dcos_launch.config.expand_path('', self.config['init_dir'])
        self.cluster_profile_path = os.path.join(self.init_dir, 'desired_cluster_profile.tfvars')

    def create(self):
        self.key_helper()
        # create terraform directory
        if os.path.exists(self.init_dir):
            raise util.LauncherError('ClusterAlreadyExists', "Either the cluster you are trying to create is already "
                                                             "running or the init_dir you specified in your config is "
                                                             "already used by another active cluster.")
        os.makedirs(self.init_dir)
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

        subprocess.run(['terraform', 'init', '-from-module', module], cwd=self.init_dir, check=True,
                       stderr=subprocess.STDOUT)
        subprocess.run(['terraform', 'apply', '-auto-approve', '-var-file', self.cluster_profile_path],
                       cwd=self.init_dir, check=True, stderr=subprocess.STDOUT)

        return self.config

    def wait(self):
        """ Nothing to do here because unlike the other launchers, create() runs and also waits for a subprocess to
        finish instead of just sending an http request to a provider.
        """
        pass

    def delete(self):
        subprocess.run(['terraform', 'destroy', '-force', '-var-file', self.cluster_profile_path], cwd=self.init_dir,
                       check=True, stderr=subprocess.STDOUT)
        shutil.rmtree(self.init_dir, ignore_errors=True)

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
        result = subprocess.run(['terraform', 'show'], cwd=self.init_dir, check=True, stdout=subprocess.PIPE)
        # unescape line endings
        info = result.stdout.decode('unicode_escape')
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


class GcpLauncher(TerraformLauncher):
    def __init__(self, config: dict, env=None):
        super().__init__(config, env)
        creds_string, creds_path = gcp.get_credentials(env)
        if not creds_path:
            creds_path = helpers.session_tempfile(creds_string)
        config['terraform_config']['gcp_credentials_key_file'] = creds_path
        if 'gcp_project' not in config['terraform_config']:
            config['terraform_config']['gcp_project'] = json.loads(creds_string)['project_id']

    def key_helper(self):
        if 'gcp_ssh_pub_key_file' not in self.config['terraform_config']:
            private_key, public_key = util.generate_rsa_keypair()
            priv_key_file = helpers.session_tempfile(private_key)
            os.chmod(priv_key_file, 0o600)
            pub_key_file = helpers.session_tempfile(public_key)
            subprocess.run(['ssh-add', priv_key_file], check=True, stderr=subprocess.STDOUT)
            self.config['terraform_config']['gcp_ssh_pub_key_file'] = pub_key_file


class AzureLauncher(TerraformLauncher):
    def __init__(self, config: dict, env=None):
        super().__init__(config, env)

    def key_helper(self):
        # TODO
        pass


class AwsLauncher(TerraformLauncher):
    def __init__(self, config: dict, env=None):
        super().__init__(config, env)

    def key_helper(self):
        # TODO
        # self.boto_wrapper = aws.BotoWrapper()
        # private_key = self.boto_wrapper.create_key_pair(key_name)
        pass
