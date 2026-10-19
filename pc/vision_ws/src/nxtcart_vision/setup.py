from glob import glob
from setuptools import setup
setup(name='nxtcart_vision', version='2.0.0', packages=['nxtcart_vision'],
      data_files=[('share/ament_index/resource_index/packages', ['resource/nxtcart_vision']),
                  ('share/nxtcart_vision', ['package.xml']),
                  ('share/nxtcart_vision/launch', glob('launch/*.launch.py'))],
      install_requires=['setuptools'], zip_safe=False,
      maintainer='NXTCart', maintainer_email='maintainer@example.com',
      description='PC product verification service', license='MIT',
      entry_points={'console_scripts': ['vision_verify_node = nxtcart_vision.node:main',
                                       'capture_references = nxtcart_vision.reference_capture:main']})
