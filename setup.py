from setuptools import setup
import versioneer
import os


def main():
    this_directory = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(this_directory, 'README.md'), 'r') as f:
        long_description = f.read()

    setup(name='microbench',
          version=versioneer.get_version(),
          description='Micro-benchmarking framework. Extensible, with '
                      'distributed/cluster support.',
          long_description=long_description,
          long_description_content_type='text/markdown',
          author='Alex Lubbock',
          author_email='code@alexlubbock.com',
          url='https://github.com/alubbock/microbench',
          packages=['microbench'],
          install_requires=[],
          tests_require=['pytest', 'pandas'],
          cmdclass=versioneer.get_cmdclass(),
          zip_safe=True,
          classifiers=[
              'Intended Audience :: Developers',
              'Intended Audience :: Science/Research',
              'License :: OSI Approved :: MIT License',
              'Programming Language :: Python'
          ]
    )


if __name__ == '__main__':
    main()
