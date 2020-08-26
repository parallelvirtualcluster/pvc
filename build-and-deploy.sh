#!/bin/bash

# A useful script for testing out changes to PVC by building the debs and deploying them out to a
# set of hosts automatically, including restarting the daemon (with a pause between) on the remote
# side. Mostly just useful for quickly testing/debugging changes as Ansible should be used for
# production upgrades.

# Check if we're root, or not
if [[ $( id -u ) -eq 0 ]]; then
    SUDO=""
else
    SUDO="sudo"
fi

HOSTS=( ${@} )
echo "> Deploying to host(s): ${HOSTS[@]}"

# Build the packages
echo -n "Building packages... "
version="$( ./build-unstable-deb.sh 2>/dev/null )"
echo "done. Package version ${version}."

# Install the client(s) locally
echo -n "Installing client packages locally... "
$SUDO dpkg -i ../pvc-client*_${version}*.deb &>/dev/null
echo "done".

for HOST in ${HOSTS[@]}; do
    echo "> Deploying packages to host ${HOST}"
    echo -n "Copying packages... "
    ssh $HOST $SUDO rm -rf /tmp/pvc &>/dev/null
    ssh $HOST mkdir /tmp/pvc &>/dev/null
    scp ../pvc-*_${version}*.deb $HOST:/tmp/pvc/ &>/dev/null
    echo "done."
    echo -n "Installing packages... "
    ssh $HOST $SUDO dpkg -i /tmp/pvc/{pvc-client-cli,pvc-daemon-common,pvc-daemon-api,pvc-daemon-node}*.deb &>/dev/null
    ssh $HOST rm -rf /tmp/pvc &>/dev/null
    echo "done."
    echo -n "Restarting PVC daemons... "
    ssh $HOST $SUDO systemctl restart pvcapid &>/dev/null
    ssh $HOST $SUDO systemctl restart pvcapid-worker &>/dev/null
    ssh $HOST $SUDO systemctl restart pvcnoded &>/dev/null
    echo "done."
    echo -n "Waiting 15s for host to stabilize... "
    sleep 15
    echo "done."
done
