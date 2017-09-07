""" Integration testing for dcos-launch.platforms functions used by dcos-launch-control (tagging and listing
deployments)
"""
import os
import yaml

from dcos_launch import util
from dcos_launch.platforms import gce, aws, arm

tags = {'integration-test': 'test-tagging'}
config = yaml.load(os.environ['DCOS_LAUNCH_CONFIG'])
deployment_name = config['deployment_name']
platform = config['platform']


def test_platform():
    if platform == 'gce':
        test_gce()
    elif platform == 'aws':
        test_aws()
    elif platform == 'azure':
        test_azure()


def test_gce():
    gce_wrapper = gce.GceWrapper()

    # check that getting all deployments works: get all the deployments and verify that our deployment is in that list
    deployment = None
    found = False
    for d in gce_wrapper.get_deployments():
        if d.name == deployment_name:
            found = True
            deployment = d
            break
    assert found

    # tag the deployment
    deployment.update_tags(tags)

    # wait for the tag is done being applied to the deployment (update operation)
    deployment.wait_for_completion()

    # get the tags from the deployment and make sure they match the tags we tried to apply
    assert deployment.get_tags() == tags


def test_aws():
    boto_wrapper = aws.BotoWrapper(None, util.set_from_env('AWS_ACCESS_KEY_ID'),
                                   util.set_from_env('AWS_SECRET_ACCESS_KEY'))

    # make sure getting all key pairs works: check that there's a key pair with our deployment's name
    found = False
    for keypair in boto_wrapper.get_all_keypairs():
        if keypair.key_name == deployment_name:
            found = True
            break
    assert found

    # check that getting all deployments works: get all the deployments and verify that our deployment is in that list
    stack = None
    found = False
    for s in boto_wrapper.get_all_stacks():
        if s.name == deployment_name:
            found = True
            stack = s
            break
    assert found

    # tag the deployment
    stack.update_tags(tags)

    # wait for the tag is done being applied to the deployment (update operation)
    stack.wait_for_deploy_complete()

    # get the tags from the deployment and make sure they match the tags we tried to apply
    assert tags == {entry['Key']: entry['Value'] for entry in stack.stack.tags}


def test_azure():
    azure_wrapper = arm.AzureWrapper(None, util.set_from_env('AZURE_SUBSCRIPTION_ID'),
                                     util.set_from_env('AZURE_CLIENT_ID'),
                                     util.set_from_env('AZURE_CLIENT_SECRET'),
                                     util.set_from_env('AZURE_TENANT_ID'))

    # check that getting all deployments works: get all the deployments and verify that our deployment is in that list
    resource_group = None
    found = False
    for rg in azure_wrapper.rmc.resource_groups.list():
        if rg.name == deployment_name:
            resource_group = rg
            found = True
            break
    assert found

    # tag the deployment
    if resource_group.tags is None:
        resource_group.tags = dict()
    resource_group.tags.update(tags)
    azure_wrapper.rmc.resource_groups.patch(resource_group.name, {
        'tags': resource_group.tags,
        'location': resource_group.location}, raw=True)

    # wait for the tag is done being applied to the deployment (update operation)
    arm.DcosAzureResourceGroup(deployment_name, azure_wrapper).wait_for_deployment()

    # get the tags from the deployment and make sure they match the tags we tried to apply
    assert azure_wrapper.rmc.resource_groups.get(deployment_name).tags == tags
