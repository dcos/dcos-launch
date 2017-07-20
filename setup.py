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
    packages=['dcos_launch', 'cloudcleaner'],
    install_requires=[
        'aiodns',
        'aiohttp',
        'aiohttp-debugtoolbar',
        'aiomysql',
        'azure-common',
        'azure-storage',
        'azure-mgmt-network',
        'azure-mgmt-resource',
        'azure-monitor',
        'boto3',
        'botocore',
        'cerberus',
        'docopt',
        'google-api-python-client',
        'jinja2',
        'msrest==0.4.4',
        'msrestazure==0.4.7',
        'oauth2client==3.0.0',
        'pyinstaller==3.2',
        'py',
        'pytest',
        'pyyaml',
        'requests==2.14.1',
        'retrying',
        'slacker'],
    entry_points={
        'console_scripts': [
            'dcos-launch=dcos_launch.cli:main',
        ],
    },
    dependency_links=[
        'https://github.com/mesosphere/dcos-test-utils@remove_dcos_launch'
    ],
    package_data={
        'cloudcleaner': ['report.html.jinja'],
        'dcos_launch': [
            'sample_configs/*.yaml'
            'ip-detect/aws.sh',
            'ip-detect/aws_public.sh',
            'ip-detect/gce.sh',
            'ip-detect/gce_public.sh',
            'templates/vpc-cluster-template.json',
            'templates/vpc-ebs-only-cluster-template.json'
        ],
    }
)
