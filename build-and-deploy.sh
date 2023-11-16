#!/usr/bin/env bash

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

KEEP_ARTIFACTS=""
if [[ -n ${1} ]]; then
    for arg in ${@}; do
        case ${arg} in
            -k|--keep)
                KEEP_ARTIFACTS="y"
                shift
            ;;
        esac
    done
fi

HOSTS=( ${@} )
echo "> Deploying to host(s): ${HOSTS[@]}"

# Move to repo root if we're not
pushd $( git rev-parse --show-toplevel ) &>/dev/null

# Prepare code
echo "Preparing code (format and lint)..."
./format || exit 1
./lint || exit 1

# Build the packages
echo -n "Building packages..."
version="$( ./build-unstable-deb.sh 2>/dev/null )"
echo " done. Package version ${version}."

# Install the client(s) locally
echo -n "Installing client packages locally..."
$SUDO dpkg -i ../pvc-client*_${version}*.deb &>/dev/null
echo " done".

for HOST in ${HOSTS[@]}; do
    echo "> Deploying packages to host ${HOST}"
    echo -n "Copying packages..."
    ssh $HOST $SUDO rm -rf /tmp/pvc &>/dev/null
    ssh $HOST mkdir /tmp/pvc &>/dev/null
    scp ../pvc-*_${version}*.deb $HOST:/tmp/pvc/ &>/dev/null
    echo " done."
    echo -n "Installing packages..."
    ssh $HOST $SUDO dpkg -i /tmp/pvc/{pvc-client-cli,pvc-daemon-common,pvc-daemon-api,pvc-daemon-node}*.deb &>/dev/null
    ssh $HOST rm -rf /tmp/pvc &>/dev/null
    echo " done."
    echo -n "Restarting PVC daemons..."
    ssh $HOST $SUDO systemctl restart pvcapid &>/dev/null
    ssh $HOST $SUDO systemctl restart pvcworkerd &>/dev/null
    ssh $HOST $SUDO systemctl restart pvcnoded &>/dev/null
    echo " done."
    echo -n "Waiting for node daemon to be running..."
    while [[ $( ssh $HOST "pvc -q node list -f json ${HOST%%.*} | jq -r '.[].daemon_state'" 2>/dev/null ) != "run" ]]; do
        sleep 5
        echo -n "."
    done
    echo " done."
done
if [[ -z ${KEEP_ARTIFACTS} ]]; then
    rm ../pvc*_${version}*
fi

popd &>/dev/null
