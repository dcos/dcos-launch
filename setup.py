from setuptools import setup


setup(
    name='dcos_test_utils',
    version='0.1',
    description='DC/OS test orchestration and lower-level cluster interface',
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
    packages=['dcos_test_utils'],
    install_requires=[
        # Pins taken from 'azure==2.0.0rc4'
        'msrest==0.4.0',
        'msrestazure==0.4.1',
        'azure-common==1.1.4',
        'azure-storage==0.32.0',
        'azure-mgmt-network==0.30.0rc4',
        'azure-mgmt-resource==0.30.0rc4',
        'boto3',
        'botocore',
        'pytest',
        'pyyaml',
        'requests==2.10.0',
        'retrying'],
    package_data={
        'dcos_test_utils': [
            'templates/vpc-cluster-template.json',
            'templates/vpc-ebs-only-cluster-template.json'
        ]
    },
    zip_safe=False
)
