#!/usr/bin/env python3

import os, sys, libvirt, uuid

#
# Generic function helpers for PVC
#

# > lookupByUUID
# This function is a wrapper for libvirt.lookupByUUID which fixes some problems
# 1. Takes a text UUID and handles converting it to bytes
# 2. Disables stdout to avoid stupid printouts
# 3. Try's it and returns a sensible value if not
def lookupByUUID(tuuid):
    dom = None

    # Convert the text UUID to bytes
    buuid = uuid.UUID(tuuid).bytes

    # Disable stdout
    sys.stdout = open(os.devnull, 'w')

    # Try
    try:
        # Open a libvirt connection
        libvirt_name = "qemu:///system"
        conn = libvirt.open(libvirt_name)
        if conn == None:
            print('>>> %s - Failed to open local libvirt connection.' % self.domuuid)
            return dom
    
        # Lookup the UUID
        dom = conn.lookupByUUID(buuid)

        # Close the libvirt connection
        conn.close()
    # Fail
    except:
        # Close the libvirt connection
        if conn != None:
            conn.close()

    # Enable stdout
    sys.stdout = sys.__stdout__

    # Return the dom object (or None)
    return dom

