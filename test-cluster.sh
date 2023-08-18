#!/usr/bin/env bash

if [[ -z ${1} ]]; then
    echo "Please specify a cluster to run tests against."
    exit 1
fi
test_cluster="${1}"
shift

if [[ ${1} == "--test-dangerously" ]]; then
    test_dangerously="y"
else
    test_dangerously=""
fi

_pvc() {
    echo "> pvc --connection ${test_cluster} $@"
    pvc --quiet --connection ${test_cluster} "$@"
    sleep 1
}

time_start=$(date +%s)

set -o errexit

pushd $( git rev-parse --show-toplevel ) &>/dev/null

# Cluster tests
_pvc connection list
_pvc connection detail

_pvc cluster maintenance on
_pvc cluster maintenance off
_pvc cluster status
backup_tmp=$(mktemp)
_pvc cluster backup --file ${backup_tmp}
if [[ -n ${test_dangerously} ]]; then
    # This is dangerous, so don't test it unless option given
    _pvc cluster restore --yes --file ${backup_tmp}
fi
rm ${backup_tmp} || true

# Provisioner tests
_pvc provisioner profile list test || true
_pvc provisioner template system add --vcpus 1 --vram 1024 --serial --vnc --vnc-bind 0.0.0.0 --node-limit hv1 --node-selector mem --node-autostart --migration-method live system-test || true
_pvc provisioner template network add network-test || true
_pvc provisioner template network vni add network-test 10000 || true
_pvc provisioner template storage add storage-test || true
_pvc provisioner template storage disk add --pool vms --size 8 --filesystem ext4 --mountpoint / storage-test sda || true
_pvc provisioner script add script-test $( find . -name "3-debootstrap.py" ) || true
_pvc provisioner profile add --profile-type provisioner --system-template system-test --network-template network-test --storage-template storage-test --userdata empty --script script-test --script-arg deb_release=bullseye test || true
_pvc provisioner create --wait testx test
sleep 30

# VM tests
vm_tmp=$(mktemp)
_pvc vm dump testx --file ${vm_tmp}
_pvc vm shutdown --yes --wait testx
_pvc vm start testx
sleep 30
_pvc vm stop --yes testx
_pvc vm disable --yes testx
_pvc vm undefine --yes testx
_pvc vm define --target hv3 --tag pvc-test ${vm_tmp}
_pvc vm start testx
sleep 30
_pvc vm restart --yes --wait testx
sleep 30
_pvc vm migrate --wait testx
sleep 5
_pvc vm unmigrate --wait testx
sleep 5
_pvc vm move --wait --target hv1 testx
sleep 5
_pvc vm meta testx --limit hv1 --node-selector vms --method live --profile test --no-autostart
_pvc vm tag add testx mytag
_pvc vm tag get testx
_pvc vm list --tag mytag
_pvc vm tag remove testx mytag
_pvc vm network get testx
_pvc vm vcpu set --no-restart testx 4
_pvc vm vcpu get testx
_pvc vm memory set --no-restart testx 4096
_pvc vm memory get testx
_pvc vm vcpu set --no-restart testx 2
_pvc vm memory set testx 2048 --restart --yes
sleep 5
_pvc vm list testx
_pvc vm info --format long testx
rm ${vm_tmp} || true

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
sleep 10

# Network tests
_pvc network add 10001 --description testing --type managed --domain testing.local --ipnet 10.100.100.0/24 --gateway 10.100.100.1 --dhcp --dhcp-start 10.100.100.100 --dhcp-end 10.100.100.199
sleep 5
_pvc vm network add --restart --yes testx 10001
sleep 30
_pvc vm network remove --restart --yes testx 10001
sleep 5

_pvc network acl add 10001 --in --description test-acl --order 0 --rule "'ip daddr 10.0.0.0/8 counter'"
_pvc network acl list 10001
_pvc network acl remove --yes 10001 test-acl
_pvc network dhcp add 10001 10.100.100.200 test99 12:34:56:78:90:ab
_pvc network dhcp list 10001
_pvc network dhcp remove --yes 10001 12:34:56:78:90:ab

_pvc network modify --domain test10001.local 10001
_pvc network list
_pvc network info --format long 10001

# Network-VM interaction tests
_pvc vm network add testx 10001 --model virtio --restart --yes
sleep 30
_pvc vm network get testx
_pvc vm network remove testx 10001 --restart --yes
sleep 5

_pvc network remove --yes 10001

# Storage tests
_pvc storage status
_pvc storage util
if [[ -n ${test_dangerously} ]]; then
    # This is dangerous, so don't test it unless option given
    _pvc storage osd set noout
    _pvc storage osd out 0
    _pvc storage osd in 0
    _pvc storage osd unset noout
fi
_pvc storage osd list
_pvc storage pool add testing 64 --replcfg "copies=3,mincopies=2"
sleep 5
_pvc storage pool list
_pvc storage volume add testing testx 1G
_pvc storage volume resize --yes testing testx 2G
_pvc storage volume rename --yes testing testx testerX
_pvc storage volume clone testing testerX testerY
_pvc storage volume list --pool testing
_pvc storage volume snapshot add testing testerX asnapshotX
_pvc storage volume snapshot rename testing testerX asnapshotX asnapshotY
_pvc storage volume snapshot list
_pvc storage volume snapshot remove --yes testing testerX asnapshotY

# Storage-VM interaction tests
_pvc vm volume add testx --type rbd --disk-id sdh --bus scsi testing/testerY --restart --yes
sleep 30
_pvc vm volume get testx
_pvc vm volume remove testx testing/testerY --restart --yes
sleep 5

_pvc storage volume remove --yes testing testerY
_pvc storage volume remove --yes testing testerX
_pvc storage pool remove --yes testing

# Remove the VM
_pvc vm stop --yes testx
_pvc vm remove --yes testx

_pvc provisioner profile remove --yes test
_pvc provisioner script remove --yes script-test
_pvc provisioner template system remove --yes system-test
_pvc provisioner template network remove --yes network-test
_pvc provisioner template storage remove --yes storage-test

popd

time_end=$(date +%s)

echo
echo "Completed PVC functionality tests against cluster ${test_cluster} in $(( ${time_end} - ${time_start} )) seconds."
