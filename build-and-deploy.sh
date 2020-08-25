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
./build-deb.sh

# Install the client(s) locally
$SUDO dpkg -i ../pvc-client*.deb

for HOST in ${HOSTS[@]}; do
    echo "****"
    echo "Deploying to host ${HOST}"
    echo "****"
    ssh $HOST $SUDO rm -rf /tmp/pvc
    ssh $HOST mkdir /tmp/pvc
    scp ../*.deb $HOST:/tmp/pvc/
    echo "Installing packages..."
    ssh $HOST $SUDO dpkg -i /tmp/pvc/{pvc-client-cli,pvc-daemon-common,pvc-daemon-api,pvc-daemon-node}*.deb
    ssh $HOST rm -rf /tmp/pvc
    echo "Restarting PVC node daemon..."
    ssh $HOST $SUDO systemctl restart pvcapid
    ssh $HOST $SUDO systemctl restart pvcapid-worker
    ssh $HOST $SUDO systemctl restart pvcnoded
    echo "****"
    echo "Waiting 15s for host ${HOST} to stabilize"
    echo "****"
    sleep 15
done
