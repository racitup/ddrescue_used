"""
Class for finding the used data blocks of a disk.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
from btrace import BtraceParser
import helpers
import ddrescue
import fsmeta, clone
import os, re, logging, shutil
from shlex import quote

# For debugging: import pdb; pdb.set_trace() # DEBUG

class MapExtents(BtraceParser):
    "Class for getting used filesystem space either by walking files or filling empty space."
    def __init__(self, options, devsize, usedevice=False):
        self.usedevice = usedevice
        self.devsize = devsize
        self.options = options
        self.extents = []
        self.start_sectors = []

    ddrlog_suffix = '.used.log'
    logmagic = 'DataRescue'

    def getpartn(self, source, mode, clonefails):
        """Generator for returning mounted partitions in the source.

        Returned tuple is: (mountpoint, fstype string, loop, start, size sectors)
        """
        with helpers.AttachLoop(source, mode) as loop:
            # (looppath, start, size)
            devtuplist = helpers.getparts(loop)
            if len(devtuplist) > 0:
                with helpers.MountPoint(self.options) as mnt:
                    for devtup in devtuplist:
                        fstype = fsmeta.get_blkidtype(devtup[0])
                        if self.ptfilter(fstype, devtup[1], devtup[2], clonefails):
                            with helpers.Mount(devtup[0], mnt, mode):
                                yield (mnt, fstype) + devtup
                        else:
                            logging.info('Skipping {}, start={}, size={}'
                                            .format(*devtup))
            else:
                logging.error('No disk partitions found in {}!'
                                .format(source))

    def ptfilter(self, fstype, start, size, clonefails):
        "Returns True if we should map the data, False if not."
        # clonefail: (devpath, start, size, fstype)
        if fstype == '':
            return False
        elif fstype in clone.CLONEABLE:
            for devpath, cstart, csize, cfstype in clonefails:
                if cstart == start:
                    if fstype == cfstype:
                        # Clone failed
                        if fstype == 'btrfs':
                            return False
                        else:
                            return True
                    else:
                        raise Exception('Contradicting types for {}'.format(devpath))
            # Clone was successful
            if fstype == 'btrfs':
                return True
            else:
                return False
        else:
            return True

    pat_filefrag = re.compile(r"\s*\d+:\s+\d+\.\.\s+\d+:\s+(\d+)\.\.\s+(\d+):\s+(\d+)")
    # hdparm --fibmap v9.43 has a bug fixed in v9.45
    # filefrag has a bug in v1.42.9 fixed in v1.42.12
    # Another bug requires 1.43-WIP 2015 or later
    # Example:
    #filefrag -b512 -e edisk.img 
    #Filesystem type is: ef53
    #File size of edisk.img is 3221225472 (6291456 blocks of 512 bytes)
    # ext:     logical_offset:        physical_offset: length:   expected: flags:
    #   0:        0..    3351:   27557888..  27561239:   3352:            
    #   1:     3360..   18431:   27561248..  27576319:  15072:   27561240:
    #   2:    18432..   23847:   28624896..  28630311:   5416:   27576320:
    #   3:    34816..   35335:   28854272..  28854791:    520:   28630312:
    #...
    # 186:  6152192.. 6275071:   32641024..  32763903: 122880:   33308416:
    # 187:  6275072.. 6291455:   32784384..  32800767:  16384:   32763904: eof
    #edisk.img: 185 extents found
    def parse_extents(self, path, offset, diskorder=True):
        "Parse file extents & return sorted extent list & the number of sectors."
        text = helpers.get_procoutput(['filefrag', '-b512', '-e', path])[1]
        genline = (m.group(0) for m in re.finditer(r"^.+$", text, re.MULTILINE))
        total = 0
        extent_list = []
        for line in genline:
            ematch = self.pat_filefrag.match(line)
            if ematch:
                extent = ematch.groups()
                # filefrag returns physical offsets relative to partition start
                start = int(extent[0]) + offset
                size = int(extent[2])
                total += size
                extent_list += [(start, size)]
        if total > 0 and len(extent_list) > 0:
            # merge consecutive extents
            if diskorder:
                # sort by start sector; default is file order
                extent_list.sort(key=lambda e: e[0])
            mergetotal = 0
            merged = []
            prev_start, prev_size = None, None
            for estart, esize in extent_list:
                # start
                if prev_start is None:
                    prev_start, prev_size = estart, esize
                # consecutive
                elif prev_start + prev_size == estart:
                    prev_size += esize
                elif estart + esize == prev_start:
                    prev_start = estart
                    prev_size += esize
                # overlap!
                elif (prev_start <= estart < prev_start + prev_size or
                      prev_start < estart + esize <= prev_start + prev_size):
                    logging.error('Overlap found: {}:{} & {}:{}'
                            .format(prev_start, prev_size, estart, esize))
                    prev_start = min(prev_start, estart)
                    prev_size = max(prev_start + prev_size, estart + esize) - prev_start
                # gap
                else:
                    merged += [(prev_start, prev_size)]
                    mergetotal += prev_size
                    prev_start, prev_size = estart, esize
            merged += [(prev_start, prev_size)]
            mergetotal += prev_size
            logging.debug('Merged extents: before={}:{}, after={}:{}, list={}'
                .format(len(extent_list), total, len(merged), mergetotal, merged))
            if total != mergetotal:
                logging.warning('filefrag extent overlaps giving incorrect size!')
            extent_list = merged
            total = mergetotal
        return total, extent_list

    def getfreesectors(self, mnt):
        "Returns integer numbers: (blocksize, freespace) in 512 byte sectors."
        stat = os.statvfs(mnt)
        blksects = stat.f_frsize // 512
        return (blksects, stat.f_bavail * blksects)

    def foundfree(self, freespace, pstart, psize):
        """Returns nsectors if >=1024 sectors of space was found, 0 otherwise.

        Also adds extents as used items to the list.
        Input start and size are the partition absolute start position and size.
        """
        nsectors, elist = self.parse_extents(freespace, pstart)
        if nsectors > 1024:
            usedstart = pstart
            usedtotal = 0
            # Add dummy free extent for end of partition space
            elist += [(pstart + psize, 0)]
            for estart, esize in elist:
                usedsize = estart - usedstart
                self.add_extent(usedstart, usedsize)
                usedstart = estart + esize
                usedtotal += usedsize
            logging.info('Found {} MB used.'.format(usedtotal//2048))
            return nsectors
        else:
            return 0

    def findfreesectors(self, mnt, start, size):
        """Gets the list of free sectors by allocating them to a file.

        Needs rw permission.
        Tries 3 techniques (uses the equivalent python file commands instead of dd):
        1. hdparm --fallocate <nk>(1024bytes) <file> - returns 95 on operation not supported
        2. dd if=/dev/zero of=<file> bs=512*1024 count=1 seek=<nsectors//1024-1>
        3. dd if=/dev/zero of=<file> bs=<512*x> count=<nsectors//x>
        """
        free = self.getfreesectors(mnt)[1]
        if free <= 1024:
            logging.warning('OS reports less than 0.5MB free space on {}'
                                .format(mnt))
            return 0
        # Some filesystems sometimes can't seem to fill all reported free space
        free -= 64
        empty = os.path.join(mnt, 'emptyspace.zeros')
        # 1. FALLOCATE
        cmd = ['hdparm', '--fallocate', str(free // 2), empty]
        proc = helpers.get_procoutput(cmd)[0]
        if proc.returncode == 0:
            nsectors = self.foundfree(empty, start, size)
            if nsectors:
                helpers.removefile(empty)
                return nsectors
        helpers.removefile(empty)
        # 2. DD SPARSE
        with open(empty, 'wb') as f:
            with open('/dev/zero', 'rb') as z:
                f.seek((free - 1024) * 512)
                zeros = z.read(1024 * 512)
                f.write(zeros)
        nsectors = self.foundfree(empty, start, size)
        helpers.removefile(empty)
        if nsectors:
            return nsectors
        # 3. DD FILL
        # Check destination has enough space
        destfree = self.getfreesectors(self.options.dest_directory)[1]
        if free > destfree:
            logging.error('Not enough destination space to fill empty blocks')
            return 0
        else:
            logging.warning('Filling image free space with zeros to find extents...')
        with open(empty, 'wb') as f:
            for _ in range(free//1024):
                f.write(zeros)
        nsectors = self.foundfree(empty, start, size)
        helpers.removefile(empty)
        return nsectors

    def wrapfindallused(self, usedmethod=None, clonefails=[]):
        "Tidiness wrapper for setup logic."
        if usedmethod is True:
            mode = 'ro'
            if self.usedevice:
                source = self.options.device
                self.findallused(usedmethod, source, mode, clonefails)
            else:
                source = helpers.image(self.options)
                self.findallused(usedmethod, source, mode, clonefails)
        else:
            mode = 'rw'
            if self.usedevice:
                raise Exception('Writing to device using free space method is not permitted.')
            else:
                with helpers.ImageCopy(self.options) as source:
                    self.findallused(usedmethod, source, mode, clonefails)

    def findallused(self, usedmethod, source, mode, clonefails):
        """Gets the used disk extents.

        Uses one of two methods:
          Used: walk the filesystems to find used extents directly (ro)
          Free: find the free space by allocating it all to a file (rw)
        By default perform the Used method for ext2, ext3 and NTFS,
        otherwise Free. This is for performance reasons on finding free space.
        Can be overridden by passing usedmethod=True/False as parameter.
        """
        for mnt, fstype, loop, start, size in self.getpartn(source, mode, clonefails):
            logging.info('Mapping {} pt {}:{} of type {} on {}'
            .format(source, str(start), str(size), fstype, mnt))

            if (usedmethod is True or
                (usedmethod is None and fstype in ['ext2', 'ext3', 'ntfs'])):
                total_sectors = 0
                for filepath in helpers.getfile(mnt):
                    sects, elist = self.parse_extents(filepath, start)
                    for e in elist: self.add_extent(*e)
                    logging.log(5, 'Used: {} sectors in {} extents for {}'
                                .format(sects, len(elist), filepath))
                    total_sectors += sects
                logging.info('Found {} MB used.'.format(total_sectors//2048))
            else:
                # Requires rw permission
                sects = self.findfreesectors(mnt, start, size)
                logging.info('Found {} MB free.'.format(sects//2048))
        self.write_log()

    def write_log(self):
        "Overwrites a ddrescue compatible file, output is directly useful."
        helpers.removefile(ddrescue.ddrlog)
        self.write_ddrescuelog(self.options, 'non-tried', 'bad-sector',
                                0, self.devsize)
        if self.options.keeplogs:
            shutil.copyfile(self.usedlog, ddrescue.ddrlog)
        else:
            shutil.move(self.usedlog, ddrescue.ddrlog)
            self.usedlog = None
        return

