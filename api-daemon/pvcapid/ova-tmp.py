
#
# TEMP
#
def tempstuff():
    # Verify that the cluster has enough space to store all OVA disk volumes
    total_size_bytes = 0
    for disk in disk_map:
        # Normalize the dev size to MB
        # The function always return XXXXB, so strip off the B and convert to an integer
        dev_size_bytes = int(pvc_ceph.format_bytes_fromhuman(disk.get('capacity', 0))[:-1])
        ova_size_bytes = int(pvc_ceph.format_bytes_fromhuman(ova_size)[:-1])
        # Get the actual image size
        total_size_bytes += dev_size_bytes
        # Add on the OVA size to account for the VMDK
        total_size_bytes += ova_size_bytes

    zk_conn = pvc_common.startZKConnection(config['coordinators'])
    pool_information = pvc_ceph.getPoolInformation(zk_conn, pool)
    pvc_common.stopZKConnection(zk_conn)
    pool_free_space_bytes = int(pool_information['stats']['free_bytes'])
    if total_size_bytes >= pool_free_space_bytes:
        output = {
            'message': "ERROR: The cluster does not have enough free space ({}) to store the VM ({}).".format(
                pvc_ceph.format_bytes_tohuman(pool_free_space_bytes),
                pvc_ceph.format_bytes_tohuman(total_size_bytes)
            )
        }
        retcode = 400
        cleanup_ova_maps_and_volumes()
        return output, retcode

        # Convert from the temporary to destination format on the blockdevs
        retcode, stdout, stderr = pvc_common.run_os_command(
            'qemu-img convert -C -f {} -O raw {} {}'.format(img_type, temp_blockdev, dest_blockdev)
        )
        if retcode:
            output = {
                'message': "ERROR: Failed to convert image '{}' format from '{}' to 'raw': {}".format(disk.get('src'), img_type, stderr)
            }
            retcode = 400
            cleanup_img_maps_and_volumes()
            cleanup_ova_maps_and_volumes()
            return output, retcode


