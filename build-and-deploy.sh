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
API_ONLY=""
PRIMARY_NODE=""
if [[ -n ${1} ]]; then
    for arg in ${@}; do
        case ${arg} in
            -k|--keep)
                KEEP_ARTIFACTS="y"
                shift
            ;;
            -a|--api-only)
                API_ONLY="y"
                shift
            ;;
            -p=*|--become-primary=*)
                PRIMARY_NODE=$( awk -F'=' '{ print $NF }' <<<"${arg}" )
                shift
            ;;
        esac
    done
fi

HOSTS=( ${@} )
echo "Deploying to host(s): ${HOSTS[@]}"
if [[ -n ${PRIMARY_NODE} ]]; then
    echo "Will become primary on ${PRIMARY_NODE} after updating it"
fi

# Move to repo root if we're not
pushd $( git rev-parse --show-toplevel ) &>/dev/null

# Prepare code
echo "> Preparing code (format and lint)..."
./format || exit 1
./lint || exit 1

# Build the packages
echo -n "> Building packages..."
version="$( ./build-unstable-deb.sh 2>/dev/null )"
echo " done. Package version ${version}."

# Install the client(s) locally
echo -n "> Installing client packages locally..."
$SUDO dpkg -i --force-all ../pvc-client*_${version}*.deb &>/dev/null
echo " done".

echo "> Copying packages..."
for HOST in ${HOSTS[@]}; do
    echo -n ">>> Copying packages to host ${HOST}..."
    ssh $HOST $SUDO rm -rf /tmp/pvc &>/dev/null
    ssh $HOST mkdir /tmp/pvc &>/dev/null
    scp ../pvc-*_${version}*.deb $HOST:/tmp/pvc/ &>/dev/null
    echo " done."
done
if [[ -z ${KEEP_ARTIFACTS} ]]; then
    rm ../pvc*_${version}*
fi

for HOST in ${HOSTS[@]}; do
    echo "> Deploying packages on host ${HOST}"
    echo -n ">>> Installing packages..."
    ssh $HOST $SUDO dpkg -i --force-all /tmp/pvc/*.deb &>/dev/null
    ssh $HOST rm -rf /tmp/pvc &>/dev/null
    echo " done."
    echo -n ">>> Restarting PVC daemons..."
    ssh $HOST $SUDO systemctl restart pvcapid &>/dev/null
    sleep 2
    ssh $HOST $SUDO systemctl restart pvcworkerd &>/dev/null
    if [[ -z ${API_ONLY} ]]; then
    sleep 2
    ssh $HOST $SUDO systemctl restart pvchealthd &>/dev/null
    sleep 2
    ssh $HOST $SUDO systemctl restart pvcnoded &>/dev/null
    echo " done."
    echo -n ">>> Waiting for node daemon to be running..."
    while [[ $( ssh $HOST "pvc -q node list -f json ${HOST%%.*} | jq -r '.[].daemon_state'" 2>/dev/null ) != "run" ]]; do
        sleep 5
        echo -n "."
    done
    fi
    echo " done."
    if [[ -n ${PRIMARY_NODE} && ${PRIMARY_NODE} == ${HOST} ]]; then
        echo -n ">>> Setting node $HOST to primary coordinator state... "
        ssh $HOST pvc -q node primary --wait &>/dev/null
        ssh $HOST $SUDO systemctl restart pvcworkerd &>/dev/null
        echo "done."
    fi
done

popd &>/dev/null
