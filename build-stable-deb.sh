#!/bin/sh
pushd $( git rev-parse --show-toplevel ) &>/dev/null
ver="$( head -1 debian/changelog | awk -F'[()-]' '{ print $2 }' )"
git pull
rm ../pvc_*
find . -name "__pycache__" -exec rm -r {} \;
dh_make -p pvc_${ver} --createorig --single --yes
dpkg-buildpackage -us -uc
dh_clean
popd &>/dev/null
