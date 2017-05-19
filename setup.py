from setuptools import setup


setup(
    name='dcos-test-utils',
    version='0.1',
    description='DC/OS cluster provisioning and orchestration utilities',
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
    packages=['dcos_launch', 'dcos_test_utils'],
    install_requires=[
        'azure-storage',
        'azure-mgmt-network',
        'azure-mgmt-resource',
        'boto3',
        'botocore',
        'cerberus',
        'docopt',
        'requests',
        'retrying',
        'pyinstaller==3.2',
        'py',
        'pytest',
        'pyyaml'],
    entry_points={
        'console_scripts': [
            'dcos-launch=dcos_launch.cli:main',
        ],
    },
    package_data={
        'dcos_launch': [
            'ip-detect/aws.sh',
            'ip-detect/aws_public.sh',
            'sample_configs/*.yaml',
            'dcos-launch.spec'
        ],
        'dcos_test_utils': [
            'templates/vpc-cluster-template.json',
            'templates/vpc-ebs-only-cluster-template.json'
        ],
    },
    zip_safe=False
)
