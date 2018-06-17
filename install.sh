#!/usr/bin/env bash

DEPS=( python3-kazoo python3-libvirt python3-psutil python3-apscheduler )

# Install required packages
sudo apt install ${DEPS[@]}
