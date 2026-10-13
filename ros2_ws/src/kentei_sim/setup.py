from glob import glob

from setuptools import find_packages, setup

package_name = 'kentei_sim'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', glob('launch/*.launch.py')),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='taku0310',
    maintainer_email='taku0310@users.noreply.github.com',
    description='仮想検定くん: OpenPLC Runtime と ROS 2 をつなぐ仮想 I/O パネル',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'io_server = kentei_sim.io_server_node:main',
            'panel = kentei_sim.panel_node:main',
            'kentei_openplc = kentei_sim.openplc_tool:main',
        ],
    },
)
