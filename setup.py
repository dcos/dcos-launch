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
        # Pins taken from 'azure==2.0.0rc4'
        #'azure-common==1.1.4',
        #'azure-storage==0.32.0',
        #'azure-mgmt-network==0.30.0rc4',
        #'azure-mgmt-resource==0.30.0rc4',
        #'msrestazure',
        'azure-storage',
        'azure-mgmt-network',
        'azure-mgmt-resource',
        'boto3',
        'botocore',
        'cerberus',
        'docopt',
        #'msrest==0.4.4',
        #'msrestazure==0.4.7',
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
