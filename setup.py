from setuptools import setup
import versioneer


def main():
    setup(name='microbench',
          version=versioneer.get_version(),
          description='Micro-benchmarking framework. Extensible, with '
                      'distributed/cluster support.',
          author='Alex Lubbock',
          author_email='code@alexlubbock.com',
          packages=['microbench'],
          install_requires=[],
          tests_require=['pytest', 'pandas'],
          cmdclass=versioneer.get_cmdclass(),
          zip_safe=True
    )


if __name__ == '__main__':
    main()
