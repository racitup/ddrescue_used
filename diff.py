"""
Diff device and image filesystems.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import helpers, fsmeta
import logging

def difffs(options):
    "Run diff on corresponding device and image filesystems."
    helpers.rereadpt(options.device)
    # (devpath, start, size)
    devparts = helpers.getparts(options.device)
    image = helpers.image(options)
    with helpers.AttachLoop(image, 'ro') as loop:
        imgparts = helpers.getparts(loop)
        parts = getcommonparts(devparts, imgparts)
        for dev, loop, start, size in parts:
            fstype = fsmeta.get_blkidtype(dev)
            if fstype == '':
                continue
            try:
                with helpers.MountPoint(options) as devmnt, \
                     helpers.Mount(dev, devmnt), \
                     helpers.MountPoint(options) as loopmnt, \
                     helpers.Mount(loop, loopmnt):
                    logging.info("Diffing {} with {}, {}:{}"
                                    .format(dev, loop, start, size))
                    cmd = ['diff', '-rqN', devmnt, loopmnt]
                    helpers.checkgcscmd(cmd)
            except OSError as e:
                logging.error("OSError [{}]: {}"
                    .format(e.errno, e.strerror))

def getcommonparts(list1, list2):
    "Checks two input partition lists and combines into one list."
    common = []
    if len(list1) > 0 and len(list2) > 0:
        for dev1, start1, size1 in list1:
            for dev2, start2, size2 in list2:
                if start1 == start2 and size1 == size2:
                    common += [(dev1, dev2, start1, size1)]
                    # find longest string of digits at the end, e.g. /dev/sdb3
                    for pos in range(-3, 0):
                        number = dev1[pos:]
                        if number.isdigit():
                            break
                    else: # nobreak
                        logging.error("No digit suffix found in device string: {}"
                                        .format(dev1))
                        break
                    if number != dev2[pos:]:
                        logging.warning("Partition numbers don't agree: {}:{}"
                                        .format(dev1, dev2))
                    break
    else:
        logging.error("No partitions found: {}, {}".format(list1, list2))
    return common

