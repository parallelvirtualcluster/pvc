#!/bin/sh
set -o xtrace
exec 3>&1
exec 1>&2
# Ensure we're up to date
git pull --rebase
# Update the version to a sensible git revision for easy visualization
base_ver="$( head -1 debian/changelog | awk -F'[()-]' '{ print $2 }' )"
new_ver="${base_ver}~git-$(git rev-parse --short HEAD)"
echo ${new_ver} >&3
# Back up the existing changelog and Daemon.py files
tmpdir=$( mktemp -d )
cp -a debian/changelog node-daemon/pvcnoded/Daemon.py ${tmpdir}/
# Replace the "base" version with the git revision version
sed -i "s/version = '${base_ver}'/version = '${new_ver}'/" node-daemon/pvcnoded/Daemon.py
sed -i "s/${base_ver}-0/${new_ver}/" debian/changelog 
cat <<EOF > debian/changelog
pvc (${new_ver}) unstable; urgency=medium

  * Unstable revision for commit $(git rev-parse --short HEAD)

 -- Joshua Boniface <joshua@boniface.me>  $( date -R )
EOF
# Build source tarball
dh_make -p pvc_${new_ver} --createorig --single --yes
# Build packages
dpkg-buildpackage -us -uc
# Restore original changelog and Daemon.py files
cp -a ${tmpdir}/changelog debian/changelog
cp -a ${tmpdir}/Daemon.py node-daemon/pvcnoded/Daemon.py
# Clean up
rm -r ${tmpdir}
dh_clean
