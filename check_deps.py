"""
Checks for tool package dependencies.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import shutil
import sys
import os, re
import helpers
from pkg_resources import parse_version

deps_mandatory = {
            'blktrace':     ('1.0.5-1', 'blktrace', 'blkparse'),
            'testdisk':     ('6.14-2', 'testdisk'),
# NOTE: there a lot of bugs in ddrescuelog before 1.19.1
            'gddrescue':    ('1.17-1', 'ddrescue', 'ddrescuelog'),
            'mount':        ('2.20.1-5.1ubuntu20.7', 'losetup', 'mount', 'umount'),
            'util-linux':   ('2.20.1-5.1ubuntu20.7', 'blkid', 'blockdev'),
            'coreutils':    ('8.21-1ubuntu5.4', 'truncate'),
            'hdparm':       ('9.43-1ubuntu3', 'hdparm'),
            'e2fsprogs':    ('1.43~WIP.2016.03.15-2', 'filefrag', 'e2image', 'e2fsck'),
            'diffutils':    ('1:3.3-1', 'diff') }

deps_optional = {
            'dosfstools':   ('3.0.26-1', 'fsck.fat'),
            'hfsprogs':     ('332.25-11', 'fsck.hfsplus'),
            'ntfs-3g':      ('1:2013.1.13AR.1-2ubuntu2', 'ntfsfix', 'ntfsclone'),
            'btrfs-tools':  ('4.1', 'btrfs', 'btrfstune', 'btrfs-image'),
            'xfsprogs':     ('3.2.1ubuntu1', 'xfs_repair', 'xfs_db'),
            'ddrescueview': ('0.4~alpha2-1~ubuntu14.04.1', 'ddrescueview') }

def checkroot():
    "Checks for running as root."
    if not os.geteuid() == 0:
        sys.exit('Must be run as root (sudo)')

def processdeps(deps):
    "Checks the versions of installed dependencies. Returns list of missing progs."
    missing = []
    for package in deps:
        version = deps[package][0]
        vernum = parse_version(version)
        cmd = ['dpkg', '-s', package]
        proc, text = helpers.get_procoutput(cmd, log=False)
        if proc.returncode == 0:
            pkgver = re.search(r"^Version: (.+)$", text, re.MULTILINE).group(1)
            pkgnum = parse_version(pkgver)
            if vernum > pkgnum:
                print('ERROR: Package dependency: {} >= {} required, {} installed.'
                        .format(package, version, pkgver))
                missing += deps[package][1:]
        else:
            print('ERROR: Package dependency: {} >= {} required but not installed.'
                        .format(package, version))
            missing += deps[package][1:]
    return missing

def check():
    """Checks application dependencies.

    Returns list of optional progs if not installed
    Requires python 3.3 for which()
    """
    if not shutil.which('dpkg'):
        sys.exit('Cannot check dependencies; dpkg not installed')

    if processdeps(deps_mandatory):
        sys.exit('Mandatory dependency errors.')

    not_installed = processdeps(deps_optional)
    if not_installed:
        print('\nWARNING: Old or missing programs may cause unexpected results:\n{}\n'
                                .format(not_installed))

    return not_installed

