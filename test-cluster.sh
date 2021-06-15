#!/usr/bin/env bash

set -o errexit

if [[ -z ${1} ]]; then
    echo "Please specify a cluster to run tests against."
    exit 1
fi
test_cluster="${1}"

_pvc() {
    echo "> pvc --cluster ${test_cluster} $@"
    pvc --quiet --cluster ${test_cluster} "$@"
    sleep 1
}

time_start=$(date +%s)

# Cluster tests
_pvc maintenance on
_pvc maintenance off
backup_tmp=$(mktemp)
_pvc task backup --file ${backup_tmp}
_pvc task restore --yes --file ${backup_tmp}
rm ${backup_tmp}

# Provisioner tests
_pvc provisioner profile list test
_pvc provisioner create --wait testX test
sleep 30

# VM tests
vm_tmp=$(mktemp)
_pvc vm dump testX --file ${vm_tmp}
_pvc vm shutdown --yes --wait testX
_pvc vm start testX
sleep 30
_pvc vm stop --yes testX
_pvc vm disable testX
_pvc vm undefine --yes testX
_pvc vm define --target hv3 ${vm_tmp}
_pvc vm start testX
sleep 30
_pvc vm restart --yes --wait testX
sleep 30
_pvc vm migrate --wait testX
sleep 5
_pvc vm unmigrate --wait testX
sleep 5
_pvc vm move --wait --target hv1 testX
sleep 5
_pvc vm meta testX --limit hv1 --selector vms --method live --profile test --no-autostart
_pvc vm list testX
_pvc vm info --long testX
rm ${vm_tmp}

# Node tests
_pvc node primary --wait hv1
sleep 10
_pvc node secondary --wait hv1
sleep 10
_pvc node primary --wait hv1
sleep 10
_pvc node flush --wait hv1
_pvc node ready --wait hv1
_pvc node list hv1
_pvc node info hv1

# Network tests
_pvc network add 10001 --description testing --type managed --domain testing.local --ipnet 10.100.100.0/24 --gateway 10.100.100.1 --dhcp --dhcp-start 10.100.100.100 --dhcp-end 10.100.100.199
sleep 5
_pvc vm network add --restart --yes testX 10001
sleep 30
_pvc vm network remove --restart --yes testX 10001
sleep 5

_pvc network acl add 10001 --in --description test-acl --order 0 --rule "'ip daddr 10.0.0.0/8 counter'"
_pvc network acl list 10001
_pvc network acl remove --yes 10001 test-acl
_pvc network dhcp add 10001 10.100.100.200 test99 12:34:56:78:90:ab
_pvc network dhcp list 10001
_pvc network dhcp remove --yes 10001 12:34:56:78:90:ab

_pvc network modify --domain test10001.local 10001
_pvc network list
_pvc network info --long 10001
_pvc network remove --yes 10001

# Storage tests
_pvc storage status
_pvc storage util
_pvc storage osd set noout
_pvc storage osd out 0
_pvc storage osd in 0
_pvc storage osd unset noout
_pvc storage osd list
_pvc storage pool add testing 64 --replcfg "copies=3,mincopies=2"
sleep 5
_pvc storage pool list
_pvc storage volume add testing testX 1G
_pvc storage volume resize testing testX 2G
_pvc storage volume rename testing testX testerX
_pvc storage volume clone testing testerX testerY
_pvc storage volume list --pool testing
_pvc storage volume snapshot add testing testerX asnapshotX
_pvc storage volume snapshot rename testing testerX asnapshotX asnapshotY
_pvc storage volume snapshot list
_pvc storage volume snapshot remove --yes testing testerX asnapshotY
_pvc storage volume remove --yes testing testerY
_pvc storage volume remove --yes testing testerX
_pvc storage pool remove --yes testing

# Remove the VM
_pvc vm stop --yes testX
_pvc vm remove --yes testX

time_end=$(date +%s)

echo
echo "Completed PVC functionality tests against cluster ${test_cluster} in $(( ${time_end} - ${time_start} )) seconds."
