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
import fs

if not os.geteuid() == 0:
    sys.exit('Must be run as root (sudo)')

fileblksz = 787
files = [
    # path, name, size in 787B blocks
    ('', 'file.1', 1),
    ('', 'file.2', 13),
    ('', 'lotsOFrandomGARBAGEforTHEfileNAME.3', 12613),
    ('directory', 'file.4', 113),
    ('directory/DEEPER', 'file.5', 4261)
]

def usage():
    "Print simple usage."
    print("\nmakedisk.py IMAGEFILE [FS1] [FS2]...\n")
    print("  Supported filesystems:\n  {}\n"
                    .format(' '.join(fs.support())))
    sys.exit(2)

def parseargs():
    "Parse input args."
    args = sys.argv[1:]
    if len(args) > 0: image = args[0]
    else: usage()
    if len(args) > 1: fss = args[1:]
    else: fss = fs.support()
    return image, fss

# Between 200 and 400MB, in 2048s
ptsizeinterval = (200, 400)

#INIT
logging.basicConfig(level=logging.DEBUG)
exe = lambda cmd: get_procoutput(cmd, shell=True)[0]
options = lambda: None
options.dest_directory = './'
filepath = randpath(options, 'files.')
cppath = os.path.join(filepath, '*')
mntpath = randpath(options, 'mnt.')
image, filesystems = parseargs()
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
# On average disk image should be around 2.4GB in size
exe('mkdir ' + mntpath)
for subpath, name, size in files:
    path = os.path.join(filepath, subpath)
    exe('mkdir ' + path)
    exe('dd if=/dev/urandom of=' + os.path.join(path, name) +
                    ' bs=' + str(fileblksz) + ' count=' + str(size))
ptlist = []
disksize = 4096
for fstype in filesystems:
    ptsize = random.randint(*ptsizeinterval) * 2048
    disksize += ptsize + 2048
    ptlist += [(fstype, ptsize)]

exe('truncate -s ' + str(disksize*512) + ' ' + image)
exe('losetup' + loop + image)
exe('parted -s' + loop + 'mklabel msdos')

# Create PT
random.shuffle(ptlist)
start = 2048
for i, (fstype, ptsize) in enumerate(ptlist):
    pttype = fs.pttype(fstype)
    end = start + ptsize - 3
    if i < 3:
        parttype = ' primary '
    elif i == 3:
        parttype = ' logical '
        exe('parted -s' + loop + 'mkpart extended ' + str(start) + 's ' + str(disksize - 1) + 's')
        start += 2048
        end += 2048
    exe('parted -s' + loop + 'mkpart' + parttype + pttype + ' ' + str(start) + 's ' + str(end) + 's')
    start = end + 3

# Get partition devices
rereadpt(loop.strip())
parts = getparts(loop.strip())
if len(parts) >= 4:
    del parts[3]

# Format filesystems and copy files
for i, (fstype, ptsize) in enumerate(ptlist):
    print('### START {} ###'.format(fstype))
    loopsub = ' ' + parts[i][0] + ' '
    proc = exe(fs.mkfs(fstype, loopsub, parts[i][1]))
    if proc.returncode != 0:
        print('### FAILED {} ###'.format(fstype))
        continue
    exe('mount' + loopsub + mntpath)
    MOUNTED = True
    exe('cp -r ' + cppath + ' ' + mntpath)
    exe('umount ' + mntpath)
    MOUNTED = False
    print('### FINISH {} ###'.format(fstype))

cleanup()

