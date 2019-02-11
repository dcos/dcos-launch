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
        'azure-storage==0.36.0',
        'azure-mgmt-network==2.0.0',
        'azure-mgmt-resource==2.0.0',
        'azure-monitor==0.3.1',
        'boto3',
        'botocore',
        'cerberus',
        'docopt',
        'google-api-python-client',
        'keyring==12.0.2',
        # Pinning msrestazure because of failing dependncy - see DCOS-40236
        'msrestazure==0.4.34',
        'oauth2client==3.0.0',
        'pyinstaller==3.3',
        'py',
        'pytest',
        'pyyaml',
        'requests',
        'requests-oauthlib==0.8.0',
        'retrying'],
    entry_points={
        'console_scripts': [
            'dcos-launch=dcos_launch.cli:main',
        ],
    },
    dependency_links=[
        'https://github.com/dcos/dcos-test-utils@a1a33c5465a9b9370209718fa72ae9429982bf35'
    ],
    package_data={
        'dcos_launch': [
            'sample_configs/*.yaml',
            'ip-detect/aws.sh',
            'ip-detect/gcp.sh',
            'ip-detect-public/aws.sh',
            'ip-detect-public/gcp.sh',
            'scripts/*',
            'templates/vpc-cluster-template.json',
            'templates/vpc-ebs-only-cluster-template.json',
            'fault-domain-detect/aws.sh',
            'fault-domain-detect/gcp.sh'
        ]
    }
)
