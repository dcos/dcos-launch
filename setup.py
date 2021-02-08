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
        'adal==1.2.0',
        'altgraph==0.16.1',
        'asn1crypto==0.24.0',
        'atomicwrites==1.2.1',
        'attrs==18.2.0',
        'azure-common==1.1.16',
        'azure-mgmt-network==2.0.0',
        'azure-mgmt-nspkg==3.0.2',
        'azure-mgmt-resource==2.0.0',
        'azure-monitor==0.3.1',
        'azure-nspkg==3.0.2',
        'azure-storage==0.36.0',
        'boto3==1.9.76',
        'botocore==1.12.76',
        'cachetools==3.0.0',
        'Cerberus==1.2',
        'certifi==2018.11.29',
        'cffi==1.11.5',
        'chardet==3.0.4',
        'cryptography==2.4.2',
        'docopt==0.6.2',
        'docutils==0.14',
        'entrypoints==0.3',
        'filelock==3.0.10',
        'future==0.17.1',
        'google-api-python-client==1.7.7',
        'google-auth==1.6.2',
        'google-auth-httplib2==0.0.3',
        'httplib2==0.19.0',
        'idna==2.8',
        'isodate==0.6.0',
        'jmespath==0.9.3',
        'keyring==12.0.2',
        'macholib==1.11',
        'more-itertools==5.0.0',
        'msrest==0.6.4',
        'msrestazure==0.4.34',
        'oauth2client==3.0.0',
        'oauthlib==2.1.0',
        'pathlib2==2.3.3',
        'pefile==2018.8.8',
        'pluggy==0.8.1',
        'py==1.7.0',
        'pyasn1==0.4.5',
        'pyasn1-modules==0.2.3',
        'pycparser==2.19',
        'PyInstaller==3.3',
        'PyJWT==1.7.1',
        'pytest==4.1.0',
        'python-dateutil==2.7.5',
        'PyYAML==3.13',
        'requests==2.21.0',
        'requests-oauthlib==1.1.0',
        'retrying==1.3.3',
        'rsa==4.0',
        's3transfer==0.1.13',
        'SecretStorage==2.3.1',
        'six==1.12.0',
        'teamcity-messages==1.21',
        'toml==0.10.0',
        'tox==3.6.1',
        'uritemplate==3.0.0',
        'urllib3==1.24.1',
        'virtualenv==16.2.0'],
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
