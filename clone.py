"""
Module for cloning btrfs, ext, ntfs and xfs filesystems.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import helpers, fsmeta
import logging, os

# For debugging: import pdb; pdb.set_trace() # DEBUG

CLONEABLE = ('btrfs', 'ext2', 'ext3', 'ext4', 'ntfs', 'xfs')

def clonefs(options, devsize):
    "Transfers filesystems that support it using a clone application."
    helpers.rereadpt(options.device)
    # (devpath, start, size)
    partlist = helpers.getparts(options.device)
    faillist = []
    image = helpers.image(options)
    create_image(image, devsize)
    if len(partlist) > 0:
        for part in partlist:
            fstype = fsmeta.get_blkidtype(part[0])
            #showsizes(image) # DEBUG
            if fstype in CLONEABLE:
                info = part + (fstype,)
                logging.info('Cloning {}, start={}, size={}, type={}'
                                .format(*info))
                partn = {}
                partn['SStart'] = part[1]
                partn['Size'] = part[2]
                args = (image, part[0], partn)
                if fstype == 'btrfs':
                    args += (options,)
                    result = clonebtrfs(*args)
                elif fstype in ('ext2', 'ext3', 'ext4'):
                    result = cloneext(*args)
                elif fstype == 'ntfs':
                    result = clonentfs(*args)
                elif fstype == 'xfs':
                    result = clonexfs(*args)
                else:
                    raise Exception('Should not get here.')
                if not result:
                    # (devpath, start, size, fstype)
                    faillist += [part + (fstype, )]
    else:
        logging.error('No disk partitions found in {}!'.format(options.device))
    return faillist

def showsizes(path):
    "Debug helper for finding allocated/apparent/ls and used sizes."
    helpers.get_procoutput(['du', '-h', path])
    helpers.get_procoutput(['du', '-h', '--apparent-size', path])

def create_image(image, devsize):
    "Check if the image exists, that it is the correct size, otherwise create."
    devsizeB = devsize*512
    if os.path.exists(image):
        imgsize = os.stat(image).st_size
        if imgsize == devsizeB:
            return
        elif imgsize == 0:
            os.remove(image)
        else:
            raise Exception('{} is not the correct size'.format(image))
    # Create a sparse file if possible
    proc = helpers.get_procoutput(['truncate', '-s', str(devsizeB), image])[0]
    if proc.returncode != 0:
        raise Exception('Could not allocate image file.')

def clonebtrfs(image, partdev, partn, options):
    """BTRFS clone.

     - Clone metadata to file
     - Attach loop device to an image offset
     - Restore file to loop
     - Change UUID on loop
     - Recover data later in getused
    """
    clonepath = helpers.randpath(options, 'btrfs.')
    clonecmd = ['btrfs-image', '-t4', '-w', partdev, clonepath]
    result = helpers.checkgcscmd(clonecmd)
    if result:
        with helpers.AttachLoop(image, 'rw', partn=partn) as loop:
            restorecmd = ['btrfs-image', '-r', '-t4', clonepath, loop]
            result = helpers.checkgcscmd(restorecmd)
            helpers.get_procoutput(['blockdev', '--flushbufs', loop])
            # btrfstune -u requires btrfs-tools v4.1+
            # Not used here because new UUID causes FSCK to fail and fs is unmountable!!
            #helpers.get_procoutput(['btrfstune', '-fu', loop])
    helpers.removefile(clonepath)
    return result

def cloneext(image, partdev, partn):
    """ext2/3/4 clone.

     - Attach loop device to an image offset
     - Clone whole partition to loop
    """
    with helpers.AttachLoop(image, 'rw', partn=partn) as loop:
        clonecmd = ['e2image', '-arp', partdev, loop]
        result = helpers.checkgcscmd(clonecmd)
    return result

def clonentfs(image, partdev, partn):
    """NTFS clone.

     - Attach loop device to an image offset
     - Clone whole partition to loop
    """
    with helpers.AttachLoop(image, 'rw', partn=partn) as loop:
        clonecmd = ['ntfsclone', '--rescue', '-fO', loop, partdev]
        result = helpers.checkgcscmd(clonecmd)
    return result

def clonexfs(image, partdev, partn):
    """XFS clone.

     - Attach loop device to an image offset
     - Clone whole partition to loop
    """
    with helpers.AttachLoop(image, 'rw', partn=partn) as loop:
        clonecmd = ['xfs_copy', '-d', partdev, loop]
        result = helpers.checkgcscmd(clonecmd)
    return result

