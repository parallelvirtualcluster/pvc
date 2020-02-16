#!/bin/sh
ver="$( head -1 debian/changelog | awk -F'[()-]' '{ print $2 }' )"
git pull
rm ../pvc_*
dh_make -p pvc_${ver} --createorig --single --yes
dpkg-buildpackage -us -uc
dh_clean
