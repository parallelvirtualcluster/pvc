#!/usr/bin/env bash
set -o xtrace
exec 3>&1
exec 1>&2
pushd $( git rev-parse --show-toplevel ) &>/dev/null
# Ensure we're up to date
git pull --rebase
# Update the version to a sensible git revision for easy visualization
base_ver="$( head -1 debian/changelog | awk -F'[()-]' '{ print $2 }' )"
new_ver="${base_ver}~git-$(git rev-parse --short HEAD)"
echo ${new_ver} >&3
# Back up the existing changelog and Daemon.py files
tmpdir=$( mktemp -d )
cp -a debian/changelog client-cli/setup.py ${tmpdir}/
cp -a node-daemon/pvcnoded/Daemon.py ${tmpdir}/node-Daemon.py
cp -a health-daemon/pvchealthd/Daemon.py ${tmpdir}/health-Daemon.py
cp -a worker-daemon/pvcworkerd/Daemon.py ${tmpdir}/worker-Daemon.py
cp -a api-daemon/pvcapid/Daemon.py ${tmpdir}/api-Daemon.py
# Replace the "base" version with the git revision version
sed -i "s/version = \"${base_ver}\"/version = \"${new_ver}\"/" node-daemon/pvcnoded/Daemon.py health-daemon/pvchealthd/Daemon.py worker-daemon/pvcworkerd/Daemon.py api-daemon/pvcapid/Daemon.py client-cli/setup.py
sed -i "s/${base_ver}-0/${new_ver}/" debian/changelog 
cat <<EOF > debian/changelog
pvc (${new_ver}) unstable; urgency=medium

  * Unstable revision for commit $(git rev-parse --short HEAD)

 -- Joshua Boniface <joshua@boniface.me>  $( date -R )
EOF
find . -name "__pycache__" -exec rm -r {} \;
# Build source tarball
dh_make -p pvc_${new_ver} --createorig --single --yes
# Build packages
dpkg-buildpackage -us -uc
# Restore original changelog and Daemon.py files
cp -a ${tmpdir}/changelog debian/changelog
cp -a ${tmpdir}/setup.py client-cli/setup.py
cp -a ${tmpdir}/node-Daemon.py node-daemon/pvcnoded/Daemon.py
cp -a ${tmpdir}/health-Daemon.py health-daemon/pvchealthd/Daemon.py
cp -a ${tmpdir}/worker-Daemon.py worker-daemon/pvcworkerd/Daemon.py
cp -a ${tmpdir}/api-Daemon.py api-daemon/pvcapid/Daemon.py

# Clean up
rm -r ${tmpdir}
dh_clean
popd &>/dev/null
