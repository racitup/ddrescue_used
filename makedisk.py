#!/usr/bin/python3
"""
Create a disk for testing. Run with sudo.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import os, random, sys, logging
from helpers import get_procoutput, randpath, get_freeloop, rereadpt, getparts

fileblksz = 787
files = [
    # path, name, size in 787B blocks
    ('', 'file.1', 1),
    ('', 'file.2', 13),
    ('', 'lotsOFrandomGARBAGEforTHEfileNAME.3', 12613),
    ('directory', 'file.4', 113),
    ('directory/DEEPER', 'file.5', 4261)
]

# Between 200 and 400MB, in 2048s
ptsizeinterval = (200, 400)

partitions = [
    # fstype, pttype, mkfs switch
    ('vfat', 'fat32', ''),
    ('ext4', 'ext4', ''),
    ('hfsplus', 'hfs', ''),
    ('ntfs', 'NTFS', ''),
    ('xfs', 'xfs', '-f'),
    ('btrfs', 'btrfs', '--force')
]

#INIT
logging.basicConfig(level=logging.DEBUG)
exe = lambda cmd: get_procoutput(cmd, shell=True)[0]
options = lambda: None
options.dest_directory = './'
filepath = randpath(options, 'files.')
mntpath = randpath(options, 'mnt.')
image = 'disk.img'
loop = ' ' + get_freeloop() + ' '

# Cleanup
MOUNTED = False
def cleanup():
    "Cleanup after script."
    if MOUNTED:
        exe('umount ' + mntpath)
    exe('losetup --detach' + loop)
    exe('rm -r ' + filepath)
    exe('rmdir ' + mntpath)

# EXCEPTION HANDLER
SYSEXCEPTHOOK = sys.excepthook
def globalexceptions(typ, value, traceback):
    "Override system exception handler to clean up before exit."
    print('Caught Exception!')
    cleanup()
    SYSEXCEPTHOOK(typ, value, traceback)
sys.excepthook = globalexceptions

# START
# On average disk image should be around 2GB in size
exe('mkdir ' + mntpath)
for subpath, name, size in files:
    path = os.path.join(filepath, subpath)
    exe('mkdir ' + path)
    exe('dd if=/dev/urandom of=' + os.path.join(path, name) +
                    ' bs=' + str(fileblksz) + ' count=' + str(size))
ptsizes = []
excess = 4096
for _ in range(len(partitions)):
    ptsizes += [random.randint(*ptsizeinterval) * 2048]
    excess += 2048
disksize = sum(ptsizes) + excess
exe('truncate -s ' + str(disksize*512) + ' ' + image)
exe('losetup' + loop + image)
exe('parted -s' + loop + 'mklabel msdos')
# Create PT
start = 2048
for i in range(len(partitions)):
    end = start + ptsizes[i] - 3
    if i < 3:
        parttype = ' primary '
    elif i == 3:
        parttype = ' logical '
        exe('parted -s' + loop + 'mkpart extended ' + str(start) + 's ' + str(disksize - 1) + 's')
        start += 2048
        end += 2048
    exe('parted -s' + loop + 'mkpart' + parttype + str(start) + 's ' + str(end) + 's')
    start = end + 3
#exe('blockdev --flushbufs' + loop)
#rereadpt(loop.strip())
random.shuffle(partitions)
# Sort by reverse size order to get rid of the extended partition
parts = getparts(loop.strip())
parts.sort(key=lambda tup: tup[2], reverse=True)

for i, (fstype, pttype, force) in enumerate(partitions):
    print('### START {} ###'.format(fstype))
    loopsub = ' ' + parts[i][0] + ' '
    proc = exe('mkfs -t ' + fstype + ' ' + force + loopsub)
    if proc.returncode != 0:
        print('### FAILED {} ###'.format(fstype))
        continue
    exe('mount' + loopsub + mntpath)
    MOUNTED = True
    exe('cp -r ' + filepath + ' ' + mntpath)
    exe('umount ' + mntpath)
    MOUNTED = False
    print('### FINISH {} ###'.format(fstype))

cleanup()

