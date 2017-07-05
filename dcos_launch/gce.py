""" Launcher functionality for the Google Compute Engine (GCE)
"""
import json
import logging

from dcos_launch import util
from dcos_test_utils import gce
from dcos_test_utils.helpers import Host

from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)


class BareClusterLauncher(util.AbstractLauncher):
    # Launches a homogeneous cluster of plain GMIs intended for onprem DC/OS
    def __init__(self, config: dict):
        """ For this to work, you must set the GOOGLE_APPLICATION_CREDENTIALS environment variable to the path of your
        json file that contains the credentials for your Google service account
        """
        credentials_path = util.set_from_env('GOOGLE_APPLICATION_CREDENTIALS')
        credentials = util.read_file(credentials_path)
        self.gce_wrapper = gce.GceWrapper(json.loads(credentials), credentials_path)
        self.config = config

    @property
    def deployment(self):
        """ Builds a BareClusterDeployment instance with self.config, but only returns it successfully if the
        corresponding real deployment (active machines) exists and doesn't contain any errors.
        """
        try:
            deployment = gce.BareClusterDeployment(self.gce_wrapper, self.config['deployment_name'],
                                                   self.config['gce_zone'])
            info = deployment.get_info()
            errors = info['operation'].get('error')
            if errors:
                raise util.LauncherError('DeploymentContainsErrors', str(errors))
            return deployment
        except HttpError as e:
            if e.resp.status == 404:
                raise util.LauncherError('DeploymentNotFound',
                                         "The deployment you are trying to access doesn't exist") from e
            raise e

    def create(self) -> dict:
        self.key_helper()
        node_count = 1 + (self.config['num_masters'] + self.config['num_public_agents']
                          + self.config['num_private_agents'])
        gce.BareClusterDeployment.create(
            self.gce_wrapper,
            self.config['deployment_name'],
            self.config['gce_zone'],
            node_count,
            self.config['source_image'],
            self.config['machine_type'],
            self.config['image_project'],
            self.config['ssh_user'],
            self.config['ssh_public_key'])
        return self.config

    def key_helper(self):
        """ Generates a public key and a private key and stores them in the config. The public key will be applied to
        all the instances in the deployment later on when wait() is called.
        """
        if self.config['key_helper']:
            private_key, public_key = util.generate_rsa_keypair()
            self.config['ssh_private_key'] = private_key.decode()
            self.config['ssh_public_key'] = public_key.decode()

    def get_hosts(self) -> [Host]:
        return list(self.deployment.hosts)

    def wait(self):
        """ Waits for the deployment to complete: first, the network that will contain the cluster is deployed. Once
        the network is deployed, a firewall for the network and an instance template are deployed. Finally,
        once the instance template is deployed, an instance group manager and all its instances are deployed.
        """
        self.deployment.wait_for_completion()

    def delete(self):
        """ Deletes all the resources associated with the deployment (instance template, network, firewall, instance
        group manager and all its instances.
        """
        self.deployment.delete()

    def test(self, args, env_dict, test_host=None, test_port=22):
        raise NotImplementedError('Bare clusters cannot be tested!')
