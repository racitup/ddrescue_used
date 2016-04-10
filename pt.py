"""
Class to deal with partition table reading, checking and backups.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import logging
import re, os
import btrace
import time
import zlib
import helpers

# For debugging: import pdb; pdb.set_trace()

BACKUP = None
def rmbackup(options):
    global BACKUP
    if BACKUP and not options.keeplogs:
        helpers.removefile(BACKUP)
        BACKUP = None

class PartitionTable(object):
    def __init__(self, text, options, devsize):
        if not isinstance(text, str):
            raise Exception('param1 is not a string: {}'.format(type(text)))
        if not isinstance(devsize, int):
            raise Exception('param2 is not an int: {}'.format(type(devsize)))
        self.devsize = devsize
        self.device = options.device
        self.dest = options.dest_directory
        self.unaccounted_limit = options.unaccounted
        self.healthflags = 0
        self.pt = []
        self.read_testdisk(text)
        return None

    # TestDisk list is in order of start sector; doesn't necessarily match PT number, list preserves order
    # Note you can't use format alignment on None
    def read_testdisk(self, text):
        # We always add to the existing pt, mark good and checks will mark bad
        self.healthflags = 0
        foundgeo, foundlba = False, False
        chsmatch, lbamatch, geomatch = None, None, None
        for line in text.splitlines():
            p = None
            if foundgeo:
                geomatch = self.pat_testdiskpt_geo.search(line)
                chsmatch = self.pat_testdiskpt_chs.match(line)
            elif foundlba:
                lbamatch = self.pat_testdiskpt_lba.match(line)
            else:
                geomatch = self.pat_testdiskpt_geo.search(line)
                lbamatch = self.pat_testdiskpt_lba.match(line)

            if geomatch:
                geoCHS = list( map(int, geomatch.groups()) )
                sectspercyl = geoCHS[1] * geoCHS[2]
                if (geoCHS[0] - 1) * sectspercyl <= self.devsize <= geoCHS[0] * sectspercyl:
                    foundgeo = True
                else:
                    logging.error('CHS geometry: {} does not match device size: {}!'
                        .format(geoCHS, self.devsize))
            elif lbamatch:
                foundlba = True
                p = list(lbamatch.groups())
                p[3] = int(p[3])
                p[4] = int(p[4])
            elif chsmatch:
                raw = chsmatch.groups()
                p = list(raw[:3])
                chs2lba = lambda chs, geo: (chs[0] * geo[1] + chs[1]) * geo[2] + chs[2] - 1
                chs = list( map(int, raw[3:6]) )
                start = chs2lba(chs, geoCHS)
                chs = list( map(int, raw[6:9]) )
                end = chs2lba(chs, geoCHS)
                p.extend([start, end])
                p.extend(list(raw[9:]))
            else: continue

            if p:
                if p[0] is None:
                    p[0] = 'None'
                else:
                    p[0] = int(p[0])
                p[5] = int(p[5])
                p.insert(6, self.get_mbrtypeid(p[2]))
                logging.debug('testdisk: PT entry: {}'.format(p))
                # Remove exact duplicates
                if p not in self.pt:
                    self.pt.append(p)
        # Sort by start sector keeping original order if possible:
        self.pt.sort(key=lambda p: p[3])
        # Filter PT
        self.sift()
        if self.length() == 0:
            logging.warning('testdisk: Did not find partition table entries.')
            self.healthflags |= 1
        self.pprint()
        self.get_unaccounted_sectors()
        logging.debug('Healthflags: {:#09b}'.format(self.healthflags))
        return self

    dict_hfreasons = {
1  :'No partition table entries were found.',
2  :'There are {0} unaccounted MB of space in the partition table.',
4  :'More than one Extended partition was found.',
8  :'No Extended partition was found but is necessary.',
16 :'Partitions with duplicate numbers were found.',
32 :'Gaps in partition numbers were found.',
64 :'Partition overlaps were found.',
}
    def gethealthflagsreasons(self):
        "Returns a list of printable strings explaining why the PT is bad."
        reasonlist = []
        for flag in self.dict_hfreasons:
            if flag & self.healthflags:
                reasonlist.append(self.dict_hfreasons[flag]
                    .format(self.unaccounted//2048))
        return reasonlist

    # Get PT MBR type ID
    tbl_typeids = { 'extended':0x05,'extended LBA':0x0F,
                    'NTFS':0x07,'HFS':0xAF,
                    'Linux':0x83,'Linux Swap':0x82,
                    'FAT12':0x01,
                    'FAT16 <32M':0x04,'FAT16':0x06,
                    'FAT16 LBA':0x0E,
                    'FAT32':0x0B,'FAT32 LBA':0x0C }
    def get_mbrtypeid(self, typestr):
        items = self.tbl_typeids.items()
        match = None
        for ts, val in items:
            # Exact match
            if ts == typestr:
                match = val
            # Substring match
            elif match is None and ts in typestr:
                match = val
        if match is None:
            match = 0
            logging.warning('Unsupported partition type: {}'
                                .format(typestr))
        return match

    # Writes to the testdisk PT backup file
    backup_format = '{0:>2} : start={3:>9}, size={5:>9}, Id={6:02X}, {1}\n'
    def write_testdisk(self, desc):
        global BACKUP
        filepath = os.path.join(self.dest, 'backup.log')
        with open(filepath,'a') as f:
            # output header
            f.write('#{} {}:Disk {} - {} MiB / {} sectors - {:#010x} crc\n'
                .format(int(time.time()),
                    desc,
                    self.device,
                    self.devsize//2048, self.devsize,
                    hash(self)))
            for p in self.pt:
                f.write(self.backup_format.format(*p))
        BACKUP = filepath

    def length(self):
        return len(self.pt)
    def clear(self):
        "Clears the partition table ready for another run."
        self.pt = []
    def pprint_info(self):
        self.pprint()
        return (self.length(), self.get_unaccounted_sectors())

    def __str__(self):
        return str(self.pt)
    def __repr__(self):
        return repr(self.pt)
    def __hash__(self):
        return zlib.crc32(str(self).encode('utf-8'),0xdeadbeef) & 0xffffffff
    def __eq__(self, other):
        return str(self) == str(other)
    def __iter__(self):
        """Use a generator to yield a dictionary version for external use."""
        for p in self.pt:
            yield dict(zip(self.field_names, p))

    pat_testdiskpt_lba = re.compile(
        r"\s+(\d+)?\s+([*PEXL])\s+(\w.{,18}\w)\s+(\d+)\s+(\d+)\s+(\d{4,})\s*\[?(\w+)?\]?")
    pat_testdiskpt_chs = re.compile(
        r"\s+(\d+)?\s+([*PEXL])\s+(\w.{,18}\w)\s+(\d+)\s+(\d{1,3})\s+(\d{1,2})\s+(\d+)\s+(\d{1,3})\s+(\d{1,2})\s+(\d{4,})\s*\[?(\w+)?\]?")
    pat_testdiskpt_geo = re.compile(r"CHS\s(\d+)\s(\d+)\s(\d+)")
    field_names = ('Number','*PEXL','Type','SStart','SEnd','Size','Id','Label')
    header_format = '{:>6}{:>6}{:>15}{:>12}{:>12}{:>12}  {:>4}  {!s}'
    row_format = '{:>6}{:>6}{:>15}{:>12}{:>12}{:>12}  {:#04X}  {!r}'
    # Doesn't print if length == 0
    def pprint(self, level=None):
        if self.length() > 0:
            if logging.INFO == level:
                func = logging.info
            elif logging.DEBUG == level:
                func = logging.debug
            else:
                func = print
            func('PartTable Header: ' + self.header_format.format(*self.field_names))
            for p in self.pt:
                func(' Partition Table: ' + self.row_format.format(*p))

    # Filter pt according to the rules:
    # 1. Remove duplicates that differ only by Number, prefer the first
    # 2. Fix E: If no E but distinct */P/L's > 4 and X or L, insert E with Number 4 - Done
    #    If more than one E, keep only first - Done
    #    If E Number > 4, assign 4 - Done
    # 3. Fix X & L: For */P/L's inside E, change P to L. If X, number with same number. - Done
    #    If no X, insert. If L outside E, change L to P. - Done
    #    Rerun 1. - Done
    # 4. Remove duplicates that differ only by number and PEXL, prefer the first - Done
    # 5. Check numbers & warn about overlaps - Done
    def sift(self):
        self.pprint(logging.DEBUG)
        self.sift_rm_dups(1)
        self.sift_fix_ext()
        self.sift_rm_dups(1)
        self.sift_rm_dups(2)
        self.sift_check_nums()

    def sift_check_nums(self):
        "Warn about duplicate numbers (not X), gaps and overlaps"
        duplicateof = {}
        prev_data_end = 0
        warning = False
        for p in self.pt:
            if p[1] in '*PEL':
                if p[1] != 'E':
                    if p[3] > prev_data_end:
                        warning = False
                        prev_data_end = p[4]
                    elif warning is False:
                        logging.warning('Partition overlap between sectors {} and {}'
                                            .format(p[3], prev_data_end))
                        warning = True
                        self.healthflags |= 64
                if p[0] in duplicateof:
                    if duplicateof[p[0]] is False:
                        duplicateof[p[0]] = True
                        logging.warning('Duplicate partition number: {}'
                            .format(p[0]))
                        self.healthflags |= 16
                else:
                    duplicateof[p[0]] = False
        prevnum = 0
        for num in sorted(iter(duplicateof)):
            if num - prevnum > 1:
                logging.warning('Gap in partition numbering: {} to {}'
                            .format(prevnum, num))
                self.healthflags |= 32
            prevnum = num

    # index: 1 is ignore Number, 2 is ignore Number and *PEXL
    def sift_rm_dups(self, index):
        "Remove duplicates. Param is starting index of slice to compare against."
        ptnonums = []
        for p in self.pt[:]:
            pnonum = p[index:]
            if pnonum in ptnonums:
                self.pt.remove(p)
            else:
                ptnonums.append(pnonum)

    def sift_fix_E(self):
        "Insert an E if one doesn't exist and should, and remove multiple."
        eE = None
        counts = {'*':0, 'P':0, 'L':0, 'X':0}
        prev_data_end = 0
        Estart = None
        Eend = self.devsize
        # scan for extended partition
        for iE, pE in enumerate(self.pt[:]):
            if pE[1] == 'E':
                if eE is None:
                    eE = btrace.Extent(pE[3], pE[5])
                    if self.pt[iE][0] > 4:
                        self.pt[iE][0] = 4
                else:
                    logging.warning('Only one extended partition allowed! Keeping the first.')
                    self.healthflags |= 4
                    self.pt.remove(pE)
            elif pE[1] in '*PL' and pE[3] > prev_data_end:
                counts[pE[1]] += 1
                prev_data_end = pE[4]
                if (counts['*'] + counts['P'] + counts['L']) == 3:
                    Estart = pE[4]
            elif pE[1] == 'X':
                counts[pE[1]] += 1
        if (eE is None and
                # detect MBR PT
                (counts['X'] + counts['L']) > 0 and
                (counts['*'] + counts['P'] + counts['L']) > 4):
            eE = btrace.Extent(Estart, Eend - Estart)
            newE = [4, 'E', 'extended', eE.start, eE.end, eE.n, 0x05, None]
            self.pt.append(newE)
            self.pt.sort(key=lambda p: p[3])
            logging.warning('No extended partition found, adding: {}'
                                .format(newE))
            self.healthflags |= 8
        return eE

    def sift_fix_ext(self):
        "Fix any problems with extended and logical partitions."
        # Will only get E if there was one already or we have detected an MBR style PT
        eE = self.sift_fix_E()
        iXlast, pXlast, eXlast = None, None, None
        bootable = 0
        for pP in self.pt:
            if pP[1] == 'X':
                pXlast = pP
                eXlast = btrace.Extent(pP[3], pP[5])
            elif pP[1] in '*PL':
                eP = btrace.Extent(pP[3], pP[5])
                if pP[1] == '*':
                    bootable += 1
                # Outside E
                if eE is None or eP not in eE:
                    if pP[1] == 'L' or bootable > 1: pP[1] = 'P'
                # Inside E
                else:
                    if pP[1] == 'P' or bootable > 1: pP[1] = 'L'
                    # Inside existing X, renumber X
                    if eXlast is not None and eP in eXlast:
                        if isinstance(pXlast[0], str) and isinstance(pP[0], int):
                            pXlast[0] = pP[0]
                    # Outside X, first X, create X
                    elif eXlast is None:
                        pXlast = [pP[0], 'X', 'extended', eE.start + 1, pP[4],
                            pP[4] - eE.start, 0x05, None]
                        eXlast = btrace.Extent(pXlast[3], pXlast[5])
                        self.pt.append(pXlast)
                    # Outside X, other X, create X
                    else:
                        pXlast = [pP[0], 'X', 'extended', eXlast.next, pP[4],
                            pP[4] - eXlast.next + 1, 0x05, None]
                        eXlast = btrace.Extent(pXlast[3], pXlast[5])
                        self.pt.append(pXlast)
        self.pt.sort(key=lambda p: p[3])

    # Return number of unaccounted sectors from PT
    # Remove E and X's, union overlapping FS's, remove from total size
    # Already sorted in order of start sector above
    def get_unaccounted_sectors(self):
        # Remove Es and Xs & build list of extents
        extents = []
        for entry in self.pt:
            # *PEXL
            if not (entry[1] == 'E' or entry[1] == 'X'):
                e = btrace.Extent(entry[3], entry[5])
                extents.append(e)
        # Union overlaps
        distinct = []
        i_prev = None
        for e in extents:
            if i_prev is None:
                distinct.append(e)
                i_prev = distinct.index(e)
            else:
                if e.overlaps(distinct[i_prev]):
                    distinct[i_prev] = distinct[i_prev].union(e)
                else:
                    distinct.append(e)
                    i_prev = distinct.index(e)
        logging.debug('PT: Distinct extents: {}'.format(distinct))
        # Add up the sizes
        total = 0
        for e in distinct:
            total += e.n
        # Take away from total device size:
        self.unaccounted = self.devsize - total
        if self.unaccounted > self.unaccounted_limit:
            logging.warning('More than {} MB unaccounted for by partition table: {} MB. Disk size: {} MB'
                    .format(self.unaccounted_limit//2048, self.unaccounted//2048, self.devsize//2048))
            self.healthflags |= 2
        else:
            logging.info('Unaccounted space according to partition table: {} sectors, {} kB, {} MB'
                    .format(self.unaccounted, self.unaccounted//2, self.unaccounted//2048))
        return self.unaccounted

