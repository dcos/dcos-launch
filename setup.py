from setuptools import setup

setup(
    name='dcos-launch',
    version='0.1.0',
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
        'azure-monitor',
        'boto3',
        'botocore',
        'cerberus',
        'docopt',
        'google-api-python-client',
        'oauth2client==3.0.0',
        'pyinstaller==3.3',
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
        'https://github.com/dcos/dcos-test-utils@449eb8018468c0eafbc85342b68639ac89e8f6be'
    ],
    package_data={
        'dcos_launch': [
            'sample_configs/*.yaml',
            'ip-detect/aws.sh',
            'ip-detect-public/aws.sh',
            'ip-detect/gcp.sh',
            'ip-detect-public/gcp.sh',
            'scripts/install_prereqs.sh',
            'templates/vpc-cluster-template.json',
            'templates/vpc-ebs-only-cluster-template.json',
            'fault-domain-detect/aws.sh',
            'fault-domain-detect/gcp.sh'
        ]
    }
)
