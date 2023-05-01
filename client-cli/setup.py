from setuptools import setup

setup(
    name="pvc",
    version="0.9.63",
    packages=["pvc", "pvc.lib"],
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
