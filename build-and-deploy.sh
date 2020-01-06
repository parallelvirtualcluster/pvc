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
echo "${HOSTS[@]}"

# Build the packages
$SUDO ./build-deb.sh

# Install the client(s) locally
$SUDO dpkg -i ../pvc-client*.deb

for HOST in ${HOSTS[@]}; do
    echo "****"
    echo "Deploying to host ${HOST}"
    echo "****"
    ssh $HOST $SUDO rm -rf /tmp/pvc
    ssh $HOST mkdir /tmp/pvc
    scp ../*.deb $HOST:/tmp/pvc/
    ssh $HOST $SUDO dpkg -i /tmp/pvc/*.deb
    ssh $HOST $SUDO systemctl restart pvcd
    ssh $HOST rm -rf /tmp/pvc
    echo "****"
    echo "Waiting 10s for host ${HOST} to stabilize"
    echo "****"
    sleep 10
done
