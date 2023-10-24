from setuptools import setup

setup(
    name="pvc",
    version="0.9.79",
    packages=["pvc.cli", "pvc.lib"],
    install_requires=[
        "Click",
        "PyYAML",
        "lxml",
        "colorama",
        "requests",
        "requests-toolbelt",
    ],
    entry_points={
        "console_scripts": [
            "pvc = pvc.cli.cli:cli",
        ],
    },
)
