""" Tools for facilitating onprem deployments
"""
import asyncio
import logging
import os

import retrying
import yaml

from dcos_test_utils import helpers, onprem, ssh_client

from dcos_launch import util

log = logging.getLogger(__name__)


def get_runner(
        cluster: onprem.OnpremCluster,
        node_type: str,
        ssh: ssh_client.SshClient) -> ssh_client.MultiRunner:
    """ Returns a multi runner for a given Host generator property of cluster
    """
    return ssh_client.MultiRunner(
        ssh.user,
        ssh.key,
        [host.public_ip for host in getattr(cluster, node_type)])


def check_results(results: list):
    """ loops through result dict list and will print the stderr and raise an exception
    for any nonzero return code
    """
    failed = False
    for result in results:
        if result['returncode'] != 0:
            print(result['stderr'])
            failed = True
    # FIXME: have meaningful error handling
    if failed:
        raise Exception('The following results contained an error: {}'.format(str(results)))


@asyncio.coroutine
def run_in_parallel(*coroutines) -> list:
    """ takes coroutines that return lists of futures and waits upon those
    coroutines must be invocations of MultiRunner.start_command_on_hosts
    returns a list of result dicts
    """
    all_tasks = list()
    for coroutine in coroutines:
        sub_tasks = yield from coroutine
        all_tasks.extend(sub_tasks)
    yield from asyncio.wait(all_tasks)
    return [task.result() for task in all_tasks]


def install_dcos(
        cluster: onprem.OnpremCluster,
        node_client: ssh_client.SshClient,
        prereqs_script_path: str,
        bootstrap_script_url: str,
        parallelism: int):
    """ TODO: add ability to copy entire genconf/ dir
    """
    # Check to make sure we can talk to the cluster
    for host in cluster.cluster_hosts:
        node_client.wait_for_ssh_connection(host.public_ip)
    # do genconf and configure bootstrap if necessary
    all_runner = get_runner(cluster, 'cluster_hosts', node_client)
    # install prereqs if enabled
    if prereqs_script_path:
        check_results(all_runner.run_command('run_async', [util.read_file(prereqs_script_path)]))
    # download install script from boostrap host and run it
    remote_script_path = '/tmp/install_dcos.sh'
    do_preflight(all_runner, remote_script_path, bootstrap_script_url)
    do_deploy(cluster, node_client, parallelism, remote_script_path)
    do_postflight(all_runner)


def prepare_bootstrap(
        ssh_tunnel: ssh_client.Tunnelled,
        download_url: str) -> str:
    """ Will setup a host as a 'bootstrap' host. This includes:
    * making the genconf/ dir in the bootstrap home dir
    * downloading dcos_generate_config.sh
    will return the installer path on the bootstrap host
    """
    ssh_tunnel.command(['mkdir', '-p', 'genconf'])
    bootstrap_home = ssh_tunnel.command(['pwd']).decode().strip()
    installer_path = os.path.join(bootstrap_home, 'dcos_generate_config.sh')
    download_dcos_installer(ssh_tunnel, installer_path, download_url)
    return installer_path


def do_genconf(
        ssh_tunnel: ssh_client.Tunnelled,
        config: dict,
        installer_path: str) -> str:
    """ runs --genconf with the installer
    if an nginx is running, kill it and restart the nginx to host the files
    return the bootstrap script URL for this genconf
    """
    tmp_config = helpers.session_tempfile(yaml.dump(config))
    installer_dir = os.path.dirname(installer_path)
    # copy config to genconf/
    ssh_tunnel.copy_file(tmp_config, os.path.join(installer_dir, 'genconf/config.yaml'))
    # try --genconf
    ssh_tunnel.command(['sudo', 'bash', installer_path, '--genconf'])
    # if OK we just need to restart nginx
    host_share_path = os.path.join(installer_dir, 'genconf/serve')
    volume_mount = host_share_path + ':/usr/share/nginx/html'
    nginx_service_name = 'dcos-bootstrap-nginx'
    if get_docker_service_status(ssh_tunnel, nginx_service_name):
        ssh_tunnel.command(['sudo', 'docker', 'rm', '-f', nginx_service_name])
    start_docker_service(
        ssh_tunnel,
        nginx_service_name,
        ['--publish=80:80', '--volume=' + volume_mount, 'nginx'])


def curl(download_url: str, out_path: str) -> list:
    """ returns a robust curl command in list form
    """
    return ['curl', '-fLsSv', '--retry', '20', '-Y', '100000', '-y', '60',
            '--create-dirs', '-o', out_path, download_url]


@retrying.retry(wait_fixed=3000, stop_max_delay=300 * 1000)
def download_dcos_installer(ssh_tunnel: ssh_client.Tunnelled, installer_path: str, download_url: str):
    """Response status 403 is fatal for curl's retry. Additionally, S3 buckets
    have been returning 403 for valid uploads for 10-15 minutes after CI finished build
    Therefore, give a five minute buffer to help stabilize CI
    """
    log.info('Attempting to download installer from: ' + download_url)
    try:
        ssh_tunnel.command(curl(download_url, installer_path))
    except Exception:
        log.exception('Download failed!')
        raise


def get_docker_service_status(ssh_tunnel: ssh_client.Tunnelled, docker_name: str) -> str:
    return ssh_tunnel.command(
        ['sudo', 'docker', 'ps', '-q', '--filter', 'name=' + docker_name,
         '--filter', 'status=running']).decode().strip()


def start_docker_service(ssh_tunnel: ssh_client.Tunnelled, docker_name: str, docker_args: list):
    ssh_tunnel.command(
        ['sudo', 'docker', 'run', '--name', docker_name, '--detach=true'] + docker_args)


def do_preflight(runner: ssh_client.MultiRunner, remote_script_path: str, bootstrap_script_url: str):
    """ Runs preflight instructions against runner
    remote_script_path: where the install script should be downloaded to on the remote host
    bootstrap_script_url: the URL where the install script will be pulled from
    """
    preflight_script_template = """
mkdir -p {remote_script_dir}
{download_cmd}
sudo bash {remote_script_path} --preflight-only master
"""
    preflight_script = preflight_script_template.format(
        remote_script_dir=os.path.dirname(remote_script_path),
        download_cmd=' '.join(curl(bootstrap_script_url, remote_script_path)),
        remote_script_path=remote_script_path)
    check_results(runner.run_command('run_async', [preflight_script]))


def do_deploy(
        cluster: onprem.OnpremCluster,
        node_client: ssh_client.SshClient,
        parallelism: int,
        remote_script_path: str):
    """ Creates a separate runner for each agent command and runs them asynchronously
    based on the chosen parallelism
    """
    # make distinct runners
    master_runner = get_runner(cluster, 'masters', node_client)
    private_agent_runner = get_runner(cluster, 'private_agents', node_client)
    public_agent_runner = get_runner(cluster, 'public_agents', node_client)

    # make shared semaphor or all
    sem = asyncio.Semaphore(parallelism)
    master_deploy = master_runner.start_command_on_hosts(
        'run_async', ['sudo', 'bash', remote_script_path, 'master'], sem=sem)
    private_agent_deploy = private_agent_runner.start_command_on_hosts(
        'run_async', ['sudo', 'bash', remote_script_path, 'private_agent'], sem=sem)
    public_agent_deploy = public_agent_runner.start_command_on_hosts(
        'run_async', ['sudo', 'bash', remote_script_path, 'public_agent'], sem=sem)
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        results = loop.run_until_complete(
                run_in_parallel(master_deploy, private_agent_deploy, public_agent_deploy))
    finally:
        loop.close()
    check_results(results)


def do_postflight(runner: ssh_client.MultiRunner):
    """ Runs a script that will check if DC/OS is operational without needing to authenticate
    """
    postflight_script = """
if [ -f /opt/mesosphere/etc/dcos-diagnostics-runner-config.json ]; then
    for check_type in node-poststart cluster; do
        T=900
        until OUT=$(sudo /opt/mesosphere/bin/dcos-shell /opt/mesosphere/bin/3dt check $check_type) || [[ T -eq 0 ]]; do
            sleep 1
            let T=T-1
        done
        RETCODE=$?
        echo $OUT
        if [[ RETCODE -ne 0 ]]; then
            exit $RETCODE
        fi
    done
else
    T=900
    until OUT=$(sudo /opt/mesosphere/bin/./3dt --diag) || [[ T -eq 0 ]]; do
        sleep 1
        let T=T-1
    done
    RETCODE=$?
    for value in $OUT; do
        echo $value
    done
fi
exit $RETCODE
"""
    check_results(runner.run_command('run_async', [postflight_script]))
