"""
Filesystem support container.

Raises exception if fs is not supported or mandatory entries are missing.

pttype: mandatory, N/A, string, N/A
 DESC: string to be used with parted mkpart as 'fs-type' when creating table entry
 REPLACE: $ with fstype string

mkfs: mandatory, rw, shell command string, don't show progress
 DESC: makes a filesystem in the available space
 APPEND: target block device string will be appended with a space
 REPLACE: # will be replaced with partition start sector with sector size of 512
          $ with fstype string

scanmeta: optional, ro, arg tuple, show progress
 DESC: reads all filesystem metadata blocks
        clonemeta1 will be tried first replacing target with '/dev/null'
        if there is no clonemeta1, this becomes mandatory
 APPEND: source block device item will be appended

fixmeta: mandatory, rw, arg tuple, show progress
 DESC: checks and optionally fixes metadata (fsck)
 APPEND: target block device item will be appended

clonemeta1/2: optional, ro, arg tuple, show progress
 DESC: clones metadata in either one or two stages. If 2 is None, only 1 is used.
        if two stages: target1 is a file and source2 is the same file
 APPEND: If last arg is '>' then [source, target] is appended, otherwise [target, source]

clonedata: optional, ro, arg tuple, show progress
 DESC: clones both metadata & data
 APPEND: If last arg is '>' then [source, target] is appended, otherwise [target, source]

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
_HEADER = ('pttype', 'mkfs', 'scanmeta', 'fixmeta', 'clonemeta1', 'clonemeta2', 'clonedata')
_EXT = (
        '$',
        'mke2fs -L $ -t $',
        None,
        ('e2fsck', '-f', '-p'),
        ('e2image', '-rp', '>'),
        None,
        ('e2image', '-carp', '>') )
_FILESYSTEMS = {
    'vfat': (
        'fat32',
        'mkfs.fat -n VFAT',
        ('fsck.fat', '-n'),
        ('fsck.fat', '-a'),
        None,
        None,
        None ),
    'ext2': _EXT,
    'ext3': _EXT,
    'ext4': _EXT,
    'hfsplus': (
        'hfs',
        'mkfs.hfsplus -v hfsplus',
        ('fsck.hfsplus', '-f', '-n'),
        ('fsck.hfsplus', '-f', '-p'),
        None,
        None,
        None ),
    'ntfs': (
        'NTFS',
        'mkntfs -L NTFS -s 512 -p # -H 255 -S 63',
        None,
        # ntfsfix repair (no -n) is not recommended and tested badly
        ('ntfsfix', '-n'),
        ('ntfsclone', '--rescue', '-mstfO', '<'),
        ('ntfsclone', '--rescue', '-rO', '<'),
        ('ntfsclone', '--rescue', '-fO', '<') ),
    'xfs': (
        'xfs',
        'mkfs.xfs -f -L xfs',
        None,
        ('xfs_repair', '-n'),
        ('xfs_metadump', '-owg', '>'),
        ('xfs_mdrestore', '-g', '>'),
        ('xfs_copy', '-d', '>') ),
    'btrfs': (
        'btrfs',
        'mkfs.btrfs -f -d single -m single -L btrfs',
        None,
        # btrfs check --repair requires btrfs-tools v4 or later.
        # Not used - errors on new simple FSs!
        ('btrfs', 'check'),
        ('btrfs-image', '-t4', '-w', '>'),
        ('btrfs-image', '-t4', '-r', '>'),
        None )
    }

# Check correct lengths on load
for tup in _FILESYSTEMS.values():
    tup[6]

def _getclonecmd(index, fstype, source, target):
    "Returns index clone command with source & target appended in the right order."
    tup = _FILESYSTEMS[fstype]

    cmd = tup[index]
    if cmd:
        cmd = list(cmd)
        last = cmd.pop()
        if last == '>':
            cmd += [source, target]
        else:
            cmd += [target, source]
    return cmd

def support():
    "Returns list of supported filesystems."
    return _FILESYSTEMS.keys()

def pttype(fstype):
    "Returns the parted 'fs-type'."
    tup = _FILESYSTEMS[fstype]

    if tup[0]: return tup[0].replace('$', fstype)
    else: raise Exception("Empty pttype for {}!".format(fstype))

def mkfs(fstype, device, pstart):
    "Returns mkfs shell string with # replaced with partition 512B start sector."
    tup = _FILESYSTEMS[fstype]

    if tup[1]:
        cmd = tup[1].replace('#', str(pstart)) + ' '
        cmd = cmd.replace('$', fstype)
        return cmd + device
    else: raise Exception("Empty mkfs for {}!".format(fstype))

def scanmeta(fstype, device):
    """Returns command for scanning metadata.

    Clonemeta1 will be tried first replacing target with '/dev/null'.
    """
    tup = _FILESYSTEMS[fstype]

    cmd = clonemeta1(fstype, device, '/dev/null')
    if cmd: return cmd
    cmd = tup[2]
    if cmd:
        return list(cmd) + [device]
    else: raise Exception("No scanmeta found for {}!".format(fstype))

def fixmeta(fstype, device):
    "Returns command for fscking metadata."
    tup = _FILESYSTEMS[fstype]

    cmd = tup[3]
    if cmd:
        return list(cmd) + [device]
    else: raise Exception("No fixmeta found for {}!".format(fstype))

clonemeta1 = lambda fstype, source, target: _getclonecmd(4, fstype, source, target)
clonemeta2 = lambda fstype, source, target: _getclonecmd(5, fstype, source, target)
clonedata  = lambda fstype, source, target: _getclonecmd(6, fstype, source, target)

