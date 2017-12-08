"""
"""
import asyncio
import logging
import os

import retrying
import yaml

from dcos_test_utils import helpers, ssh_client

from dcos_launch import util

log = logging.getLogger(__name__)


def get_runner(
        cluster,
        node_type: str,
        ssh: ssh_client.SshClient):
    targets = [host.public_ip for host in getattr(cluster, node_type)]
    return ssh_client.MultiRunner(
        ssh.user,
        ssh.key,
        targets)


def check_results(results):
    for result in results:
        if result['returncode'] != 0:
            print(result['stderr'])
    # FIXME: have meaningful error handling


@asyncio.coroutine
def run_in_parallel(*coroutines):
    """ takes coroutines that return lists of futures and waits upon those
    """
    all_tasks = list()
    for coroutine in coroutines:
        sub_tasks = yield from coroutine
        all_tasks.extend(sub_tasks)
    yield from asyncio.wait(all_tasks)
    return [task.result() for task in all_tasks]


def install_dcos(
        cluster,
        download_url: str,
        bootstrap_client,
        node_client,
        prereqs_script_path: str,
        parallelism: int,
        logging_enabled: bool,
        genconf_dir: str=None):
    # Check to make sure we can talk to the cluster
    bootstrap_client.wait_for_ssh_connection(cluster.bootstrap_host.public_ip)
    for host in cluster.cluster_hosts:
        node_client.wait_for_ssh_connection(host.public_ip)
    # do genconf and configure bootstrap if necessary
    bootstrap_script_url = prepare_bootstrap(
        bootstrap_client, cluster.bootstrap_host.public_ip, download_url)
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
        bootstrap_client,
        bootstrap_host: str,
        download_url: str,
        config: dict):
    """ Will setup a host as a 'bootstrap' host. This includes:
    * making the genconf/ dir in the bootstrap home dir
    * downloading dcos_generate_config.sh
    """
    with bootstrap_client.tunnel(bootstrap_host) as t:
        t.command(['mkdir', '-p', 'genconf'])
        bootstrap_home = t.command(['pwd']).decode().strip()
        installer_path = os.path.join(bootstrap_home, 'dcos_generate_config.sh')
        download_dcos_installer(t, installer_path, download_url)
        return do_genconf(t, config, installer_path)


def do_genconf(ssh_tunnel, config: dict, installer_path: str) -> str:
    """
    run --genconf with the installer
    if an nginx is running, kill it
    start the nginx to host the files
    return the bootstrap_url
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
    bootstrap_host_url = ssh_tunnel.host + ':80'
    return bootstrap_host_url + '/dcos_install.sh'


def curl(download_url, out_path) -> list:
    """ returns a robust curl command in list form
    """
    return ['curl', '-fLsSv', '--retry', '20', '-Y', '100000', '-y', '60',
            '--create-dirs', '-o', out_path, download_url]


@retrying.retry(wait_fixed=3000, stop_max_delay=300 * 1000)
def download_dcos_installer(ssh_tunnel, installer_path, download_url):
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


def get_docker_service_status(ssh_tunnel, docker_name: str) -> str:
    return ssh_tunnel.command(
        ['sudo', 'docker', 'ps', '-q', '--filter', 'name=' + docker_name,
         '--filter', 'status=running']).decode().strip()


def start_docker_service(ssh_tunnel, docker_name: str, docker_args: list):
    ssh_tunnel.command(
        ['sudo', 'docker', 'run', '--name', docker_name, '--detach=true'] + docker_args)


def do_preflight(runner, remote_script_path, bootstrap_script_url):
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


def do_deploy(cluster, node_client, parallelism, remote_script_path):
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


def do_postflight(runner):
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
