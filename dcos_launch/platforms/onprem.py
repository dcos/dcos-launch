""" Methods for facilitating installation with the onprem installer

    def wait(self):
        log.info('Waiting for bare cluster provisioning status..')
        self.get_bare_cluster_launcher().wait()
        cluster = self.get_onprem_cluster()
        self.bootstrap_host = cluster.bootstrap_host.public_ip
        log.info('Waiting for SSH connectivity to cluster host...')
        self.get_ssh_client(user='bootstrap_ssh_user').wait_for_ssh_connection(
            self.bootstrap_host, self.config['ssh_port'])
        host_ssh_client = self.get_ssh_client()
        for host in cluster.hosts:
            # bootstrap host might have a separate SSH user and therefore has
            # already been checked
            if host == cluster.bootstrap_host:
                continue
            host_ssh_client.wait_for_ssh_connection(host.public_ip, self.config['ssh_port'])
        # print the IPs for use in live-debugging the installation
        log.info('Cluster master IP(s): {}'.format(cluster.masters))
        log.info('Cluster public agent IP(s): {}'.format(cluster.public_agents))
        log.info('Cluster private agent IP(s): {}'.format(cluster.private_agents))
        log.info('Cluster bootstrap IP: {}'.format(cluster.bootstrap_host))
        try:
            self.get_ssh_client(user='bootstrap_ssh_user').command(self.bootstrap_host, ['test', '-f', STATE_FILE])
            last_complete = self.get_last_state()
            log.info('Detected previous launch state, continuing '
                     'from last complete stage ({})'.format(last_complete))
        except subprocess.CalledProcessError:
            log.info('No installation state file detected; beginning fresh install...')
            last_complete = None

        if last_complete is None:
            cluster.setup_installer_server(self.config['installer_url'], False)
            last_complete = 'SETUP'
            self.post_state(last_complete)

        installer = dcos_test_utils.onprem.DcosInstallerApiSession(Url(
            'http', self.bootstrap_host, '', '', '', self.config['installer_port']))
        if last_complete == 'SETUP':
            last_complete = 'GENCONF'
            installer.genconf(self.get_completed_onprem_config(cluster))
            self.post_state(last_complete)
        if last_complete == 'GENCONF':
            installer.preflight()
            last_complete = 'PREFLIGHT'
            self.post_state(last_complete)
        if last_complete == 'PREFLIGHT':
            installer.deploy()
            last_complete = 'DEPLOY'
            self.post_state(last_complete)
        if last_complete == 'DEPLOY':
            installer.postflight()
            last_complete = 'POSTFLIGHT'
            self.post_state(last_complete)
        if last_complete != 'POSTFLIGHT':
            raise dcos_launch.util.LauncherError('InconsistentState', 'State on bootstrap host is: ' + last_complete)

"""
import logging
import os

import retrying

log = logging.getLogger(__name__)


def do_install():
    """ Procedure:
    1. Veryify SSH connectivity to all hosts that will be SSHd to
    2. open a tunnel to bootstrap host
    3. setup bootstrap host (download installer, optionally start ZK, start nginx)
    4. for each node type, trigger an installation, logging the output locally (if desired?)
    """
    pass


@retrying.retry(wait_fixed=3000, stop_max_delay=300 * 1000)
def download_dcos_installer(ssh_tunnel, installer_path, download_url):
    """Response status 403 is fatal for curl's retry. Additionally, S3 buckets
    have been returning 403 for valid uploads for 10-15 minutes after CI finished build
    Therefore, give a five minute buffer to help stabilize CI
    """
    log.info('Attempting to download installer from: ' + download_url)
    try:
        ssh_tunnel.command(['curl', '-fLsSv', '--retry', '20', '-Y', '100000', '-y', '60',
                            '--create-dirs', '-o', installer_path, download_url])
    except Exception:
        log.exception('Download failed!')
        raise


def setup_bootstrap(ssh_tunnel, zookeeper=False):
    if zookeeper:
        check_or_start_docker_service(
            ssh_tunnel,
            'dcos-bootstrap-zk',
            ['--publish=2181:2181', '--publish=2888:2888', '--publish=3888:3888', 'jplock/zookeeper'])
        zk_host = ssh_tunnel.host + ':2181'
        assert zk_host

    host_share_path = os.path.join(ssh_tunnel.command(['pwd']).decode().strip(), 'genconf/serve')
    volume_mount = host_share_path + ':/usr/share/nginx/html'
    check_or_start_docker_service(
        ssh_tunnel,
        'dcos-bootstrap-nginx',
        ['--publish=80:80', '--volume=' + volume_mount, 'nginx'])
    bootstrap_host_url = ssh_tunnel.host + ':80'
    return bootstrap_host_url


def check_or_start_docker_service(ssh_tunnel, docker_name: str, docker_args: list):
    """ Checks to see if a given docker service is running on the host
    host. If not, the service will be started
    """
    run_status = ssh_tunnel.command(
        ['docker', 'ps', '-q', '--filter', 'name=' + docker_name, '--filter', 'status=running']).decode().strip()
    if run_status != '':
        log.warn('Using currently running {name} container: {status}'.format(
            name=docker_name, status=run_status))
        return
    ssh_tunnel.command(
        ['docker', 'run', '--name', docker_name, '--detach=true'] + docker_args)
