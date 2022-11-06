from setuptools import setup

setup(
    name="pvc",
    version="0.9.57",
    packages=["pvc", "pvc.cli_lib"],
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
            "pvc = pvc.pvc:cli",
        ],
    },
)
