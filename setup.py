from setuptools import setup

setup(
    name='dcos-launch',
    version='0.1',
    description='DC/OS cluster provisioning',
    url='https://dcos.io',
    author='Mesosphere, Inc.',
    author_email='help@dcos.io',
    license='apache2',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'License :: OSI Approved :: Apache Software License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
    ],
    packages=['dcos_launch', 'dcos_launch.platforms'],
    install_requires=[
        'azure-storage',
        'azure-mgmt-network',
        'azure-mgmt-resource',
        'boto3',
        'botocore',
        'cerberus',
        'docopt',
        'google-api-python-client',
        'oauth2client==3.0.0',
        'pyinstaller==3.2',
        'py',
        'pytest',
        'pyyaml',
        'requests',
        'retrying'],
    entry_points={
        'console_scripts': [
            'dcos-launch=dcos_launch.cli:main',
        ],
    },
    dependency_links=[
        'https://github.com/dcos/dcos-test-utils@924d84d8b79f39bf6a1cdd8043b0e65fe9171eec'
    ],
    package_data={
        'dcos_launch': [
            'sample_configs/*.yaml',
            'ip-detect/aws.sh',
            'ip-detect/aws_public.sh',
            'ip-detect/gce.sh',
            'ip-detect/gce_public.sh',
            'templates/vpc-cluster-template.json',
            'templates/vpc-ebs-only-cluster-template.json'
        ],
    }
)
