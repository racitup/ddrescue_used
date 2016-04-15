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
import logging, time

def difffs(options, partinfo):
    "Run diff on corresponding device and image filesystems."
    image = helpers.image(options)
    with helpers.AttachLoop(image, 'ro') as loop:
        parts = helpers.getcommonparts(partinfo, loop)
        for part in parts:
            dev, loopdev, start, size, fstype = part[:5]
            try:
                with helpers.MountPoint(options) as devmnt, \
                     helpers.Mount(dev, devmnt), \
                     helpers.MountPoint(options) as loopmnt, \
                     helpers.Mount(loopdev, loopmnt):
                    logging.info("Diffing {} with {}, {}:{} as {}"
                                    .format(dev, loopdev, start, size, fstype))
                    cmd = ['diff', '-rqN', devmnt, loopmnt]
                    helpers.checkgcscmd(cmd)
            except OSError as e:
                logging.error("OSError [{}]: {}"
                    .format(e.errno, e.strerror))
            # Spurious mount errors on image, try a delay
            time.sleep(0.1)

