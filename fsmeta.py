"""
Library for finding metadata blocks and running fsck.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import logging, os
import helpers, fs

# For debugging: import pdb; pdb.set_trace()

_IDTOFSTYPE = {0x07:'ntfs', 0xAF:'hfsplus',
               0x01:'vfat', 0x04:'vfat', 0x06:'vfat',
               0x0B:'vfat', 0x0C:'vfat', 0x0E:'vfat'}

def getmetacmd(loop, partn, mode, partinfo):
    "Returns an fsck command as a list of args for subprocess."
    probetype = helpers.getblkidtype(loop)
    if probetype == '':
        try:
            probetype = _IDTOFSTYPE[partn['Id']]
        except KeyError:
            return None

    if mode == 'rw':
        try:
            cmd = fs.fixmeta(probetype, loop)
        except KeyError:
            return None
    else:
        try:
            cmd = fs.scanmeta(probetype, loop)
        except KeyError:
            return None

        for devpath, start, size, fstype, metaresult, dataresult in partinfo:
            if partn['SStart'] == start and partn['Size'] == size:
                if probetype == fstype:
                    if metaresult: return False
                    else: break
                else:
                    logging.error("Contradicting types for {}: {} & {}"
                        .format(partn['Number'], probetype, fstype))

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

def scanmeta_running(options, device, ptable, mode='ro', partinfo=[]):
    "A generator for filesystem scanning, telling us when it is complete."
    for partn in ptable:
        if partn['*PEXL'] in ('E', 'X'):
            continue

        with helpers.AttachLoop(device, mode, partn) as loop:
            metacmd = getmetacmd(loop, partn, mode, partinfo)
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

