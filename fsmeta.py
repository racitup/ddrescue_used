"""
Library for helping detect FS, finding metadata blocks and running fsck.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import helpers, clone
import logging
import os

# For debugging: import pdb; pdb.set_trace()

def get_blkidtype(loop):
    "Returns strings like: ext2\\3\\4,ntfs,btrfs,vfat,hfsplus,xfs."
    cmd = ['blkid', '-s', 'TYPE', '-o', 'value', loop]
    return helpers.get_procoutput(cmd)[1]

_IDTOFSTYPE = {0x07:'ntfs', 0xAF:'hfsplus',
               0x01:'vfat', 0x04:'vfat', 0x06:'vfat',
               0x0B:'vfat', 0x0C:'vfat', 0x0E:'vfat'}

_METACMD =    { 'vfat'   :(['fsck.fat'], ['-n'], ['-a']),
                # No found image command for hfs+ or vfat
                'hfsplus':(['fsck.hfsplus', '-f'], ['-n'], ['-p']),
                # ntfsfix repair (no -n) is not recommended and tested badly
                #'ntfs'   :(['ntfsfix'], ['-n'], ['-n']),
                'ntfs'   :([], ['ntfsclone', '-O', '/dev/null', '-mtfs', '--rescue'], ['ntfsfix', '-n']),
                # btrfs check --repair requires btrfs-tools v4 or later. Not used - errors on new simple FSs!
                'btrfs'  :(['btrfs', 'check'], [], []),
                'xfs'    :([], ['xfs_db', '-F', '-i',  '-c', 'metadump -o -w /dev/null'], ['xfs_repair'])}
                #'xfs'    :(['xfs_repair'], ['-n'], [])}
def get_metacmd(loop, partn, mode, clonefails):
    "Returns an fsck command as a list of args for subprocess."
    probetype = get_blkidtype(loop)
    if probetype == '':
        try:
            partn_id = partn['Id']
            probetype = _IDTOFSTYPE[partn_id]
        except KeyError:
            return None

    if probetype in clone.CLONEABLE:
        failed = False
        for devpath, start, size, fstype in clonefails:
            if partn['SStart'] == start:
                if probetype == fstype:
                    failed = True
                    break
                else:
                    raise Exception('Contradicting types: "{}" vs "{}" for partition {}'
                        .format(probetype, fstype, partn['Number']))
        # If clone failed or repairing image, continue
        if failed == False and mode != 'rw':
            return False

    # We do not support copying btrfs metadata using our method if clone has
    # failed due to clashing UUIDs causing confusion and corruption
    if probetype == 'btrfs' and mode != 'rw':
        return False
    if probetype in _METACMD:
        args = _METACMD[probetype]
        if mode == 'rw':
            cmd = args[0] + args[2]
        else:
            cmd = args[0] + args[1]
        cmd += [loop]
    elif probetype.startswith('ext'):
        if mode == 'rw':
            # -a mostly synonym for -p
            # -f is essential for ext2/3/4 otherwise checks are skipped if clean
            cmd = ['fsck', '-t', probetype, loop, '--', '-f', '-a']
        else:
            cmd = ['e2image', '-Q', loop, '/dev/null']
    else:
        return None

    logging.info('Scanning partition number {} as {} with: {}'
                    .format(partn['Number'], probetype, ' '.join(cmd)))
    return cmd

def fixmeta_image_running(options, ptable):
    "A generator for repairing the image using fsck."
    image = helpers.image(options)
    mode = 'rw'
    with helpers.AttachLoop(image, mode) as device:
        for running in scanmeta_running(options, device, ptable, mode):
            yield running

def scanmeta_running(options, device, ptable, mode='ro', clonefails=[]):
    "A generator for filesystem scanning, telling us when it is complete."
    for partn in ptable:
        if partn['*PEXL'] in ('E', 'X'):
            continue

        with helpers.AttachLoop(device, mode, partn) as loop:
            metacmd = get_metacmd(loop, partn, mode, clonefails)
            if metacmd is None:
                logging.warning('Partition number {} not supported!'
                                    .format(partn['Number']))
            elif metacmd is False:
                logging.info('Skipping partition number {}'
                                    .format(partn['Number']))
            else:
                for proc in helpers.generator_context_switch(metacmd):
                    # Run the process until it exits
                    yield proc.returncode is None
                if proc.returncode != 0:
                    logging.warning('Detected errors on partition: {}'
                                        .format(partn))
                # Walk the filesystem to read all inodes - required
                if mode != 'rw':
                    for path in helpers.fswalk(options, loop):
                        os.stat(path)

