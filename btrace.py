"""
Starts a btrace process, parses the output and writes a ddrescue compatible log.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import logging
import subprocess
import fcntl, os, io, sys, re, shutil
from bisect import bisect_right
import constants
import pprint
import helpers, ddrescue

# NOTE: if you don't read from stdout deadlock can occur
# CTRL-C on blktrace to kill
blktrace = None
blkparse = None
parser = None
def start_bgproc(device, devsize):
    "Starts the btrace process."
    global blktrace
    global blkparse
    global parser

    # Flush the device buffers first
    # trial fix for fs OSError I/O problem after copying to image - didn't work
    helpers.get_procoutput(['blockdev', '--flushbufs', device])
    blktrace = subprocess.Popen(['blktrace', '-o-', device],
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
    logging.debug('blktrace: {}'.format(helpers.get_process_cmd(blktrace)))
    blkparse = subprocess.Popen(['blkparse', '-q', '-i-'],
                                    stdin=blktrace.stdout,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.DEVNULL)
    logging.debug('blkparse: {}'.format(helpers.get_process_cmd(blkparse)))
    # something to do with blktrace receiving a SIGPIPE if blkparse exits?
    blktrace.stdout.close()
    # make blkparse.stdout non-blocking. May receive IOError instead:
    fcntl.fcntl(blkparse.stdout.fileno(), fcntl.F_SETFL, os.O_NONBLOCK)

    # create instance of parser
    parser = BtraceParser(blkparse)
    return blktrace

def movelog(options):
    "Copies or moves the btrace log depending whether a copy should be kept."
    if options.keeplogs:
        shutil.copyfile(parser.usedlog, ddrescue.ddrlog)
    else:
        shutil.move(parser.usedlog, ddrescue.ddrlog)
        parser.usedlog = None

def stop():
    "Kill blktrace, returns blkparse because it will terminate after blktrace."
    global blktrace
    helpers.ctrlc_process(blktrace)
    blktrace = None
    return blkparse

def add_used_extent(start=None, size=None, next=None):
    "Add a 'used' extent to btrace list, must supply at least two parameters."
    if start is None:
        start = int(next) - int(size)
    if size is None:
        size = int(next) - int(start)
    parser.add_extent(start, size)

###
class Extent(object):
    "Mini-class for implementing 'in', overlaps and union for an extent to make code more readable."
    # When thinking about start and ends, think about boundaries to sectors rather than the sectors themselves:
    # | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
    # 0   1   2   3   4   5   6   7
    def __init__(self, start, n):
        self.start = int(start)
        self.n = int(n)
        self.next = self.start + self.n
        self.end = self.next - 1

    # Override 'in' operator. Only works for Extents.
    def __contains__(self, item):
        "Means: is item wholly inside self? 'item in self'"
        if self.start <= item.start and item.next <= self.next:
            return True
        else:
            return False

    def overlaps(self, item):
        "Means overlap or directly adjacent to."
        if self.start <= item.start <= self.next:
            return True
        elif self.start <= item.next <= self.next:
            return True
        elif item.start <= self.start <= item.next:
            return True
        elif item.start <= self.next <= item.next:
            return True
        else:
            return False

    # Pretty print the contents:
    def __str__(self):
        return 'E(s={}, n={}, e={})'.format(self.start, self.n, self.end)
    def __repr__(self):
        return 'Extent(start={}, n={})'.format(self.start, self.n)

    # union of two overlapping extents
    def union(self, item):
        if self.overlaps(item):
            start = min(self.start, item.start)
            next = max(self.next, item.next)
            n = next - start
            return Extent(start, n)
        else:
            raise ValueError('Extents do not overlap: {}, {}'.format(self, item))

###
class BtraceParser(object):
    "Class for parsing btrace output to a used space extent list and ddrescue log."
    def __init__(self, source):
        self.inproc = None
        self.infile = None
        self.usedlog = None
        if isinstance(source, subprocess.Popen):
            self.inproc = source
        elif isinstance(source, io.TextIOWrapper):
            self.infile = source
        else:
            raise Exception('Did not recognise btrace source: {}'.format(type(source)))
        self.stats = {'RWBS':{'R':0,'W':0,'D':0,'N':0,'F':0,'FUA':0,'A':0,'B':0,'S':0,'M':0},
                 'read_lines':0,
                 'commands':{},
                 'error_list':{},
                    'R_sectors':0,'W_sectors':0,
                    'C':0,'B':0,'D':0,'I':0,'Q':0,'F':0,'G':0,'M':0,
                    'S':0,'P':0,'U':0,'T':0,'X':0,'A':0,'payloads':0}
    # The extents list is formed of tuples: (start_sector, n_sectors)
    # and sorted by start_sector, sector size is 512 bytes
        self.extents = []
        self.start_sectors = []
        return None

    ddrlog_suffix = '.btrace.log'
    logmagic = 'MetaRescue'

    def get_closest_extent(self, sector, i_start):
        if len(self.extents) != 0:
            i_insert = bisect_right(self.start_sectors, sector, lo=i_start)
            i = i_insert
            if i > 0:
                i -= 1
            e = Extent(self.extents[i][0],self.extents[i][1])
            return (i_insert, i, e)
        else:
            return (0, 0, None)

    def add_extent(self, start, n):
        # Inputs must always be >= 0
        if start < 0 or n < 0:
            raise Exception('add_extent: Input less than zero: {}:{}'
                                .format(start, n))
        if n == 0:
            return
        # INSERT straight away if first extent
        if 0 == len(self.extents):
            self.extents.insert(0, (start, n))
            self.start_sectors.insert(0, start)
            logging.log(5, 'add_first_extent INSERT: pos={} new={}'
                            .format(0, Extent(start, n)))
            return

        e_new = Extent(start, n)
        (ii_left,  i_left,  e_left)  = self.get_closest_extent(e_new.start, 0)
        (ii_right, i_right, e_right) = self.get_closest_extent(e_new.next, ii_left)

        i_diff  = i_right - i_left
        overlaps = 0
        b_left = False
        eu = e_new
        if e_left.overlaps(eu):
            overlaps += 1
            b_left = True
            eu = eu.union(e_left)
        if i_diff > 0:
            if e_right.overlaps(eu):
                overlaps += 1
                b_left = False
                eu = eu.union(e_right)

        # INSERT if no overlaps
        if 0 == overlaps:
            self.extents.insert(ii_left, (eu.start, eu.n))
            logging.log(5, 'add_extent INSERT: pos={} new={}'
                            .format(ii_left, eu))
        # REPLACE if overlap once
        elif 1 == overlaps:
            if b_left:
                self.extents[i_left] = (eu.start, eu.n)
                logging.log(5, 'add_extent REPLACE: pos={} org={} new={} union={}'
                                .format(i_left, e_left, e_new, eu))
            else:
                self.extents[i_right] = (eu.start, eu.n)
                logging.log(5, 'add_extent REPLACE: pos={} org={} new={} union={}'
                                .format(i_right, e_right, e_new, eu))
        # REPLACE & DELETE if overlap twice or more
        else:
            self.extents[i_left] = (eu.start, eu.n)
            for i in range(i_left + 1, i_right + 1):
                del self.extents[i]
            logging.log(5, 'add_extent REPLACE&DELETE: pos={}-{} orgs={}-{} new={} union={}'
                            .format(i_left, i_right, e_left, e_right, e_new, eu))
        # Rebuild start_sectors list
        self.start_sectors = [data[0] for data in self.extents]
        return

    pat_plus = re.compile(r"(\d+) \+ (\d+)")
    pat_sqbraces = re.compile(r"\[(.+)\]")
    def parse_other(self, is_C, other):
        plus_match = self.pat_plus.search(other)
        sqbrace_match = self.pat_sqbraces.search(other)

        sector = 0
        n_sectors = 0
        if plus_match is None:
            self.stats['payloads'] += 1
        else:
            sector = int(plus_match.group(1))
            n_sectors = int(plus_match.group(2))

        if sqbrace_match is not None:
            sqbrace_content = sqbrace_match.group(1)
            if is_C:
                # Remove successes: error = "[0]"
                if sqbrace_content != '0':
                    if sqbrace_content not in self.stats['error_list']:
                        self.stats['error_list'][sqbrace_content] = 0
                    self.stats['error_list'][sqbrace_content] += 1
            else:
                if sqbrace_content not in self.stats['commands']:
                    self.stats['commands'][sqbrace_content] = 0
                self.stats['commands'][sqbrace_content] += 1

        return (sector, n_sectors)

    # 'other' formats:
    #  7,0    0       12     0.005528571 30641  Q   R 12583104 + 8 [testdisk]
    # C       payload: (payload) [error]
    # C    no_payload: sector + n_sectors (elapsed_time) [error]
    # BDIQ    payload: n_bytes (payload)
    # BDIQ no_payload: sector + n_sectors (elapsed_time) [command]
    # FGMS           : sector + n_sectors [command]
    # P      //ignore: [command]
    # UT     //ignore: [command] n_requests
    # X      //ignore: s_sector/n_sector [command]
    # A      //ignore: sector length org_device offset
    # each btrace line is made up from a header of 7 fixed fields followed by context-specific 'other' stuff
    def parse_btrace(self, major_minor, cpuid, seq, secnsec, pid, action, RWBS, other):
        # Update stats
        # RWBS can be (in this order):
        # F[lush]
        # One of: D[iscard], W[rite], R[ead], N[one of the above]
        # Any of: F[orce Unit Access(FUA)], A[head], S[ync], M[etadata]
        for i, char in enumerate(RWBS):
            if 0 == i and 'F' == char:
                self.stats['RWBS'][char] += 1
            elif 'F' == char:
                self.stats['RWBS']['FUA'] += 1
            else:
                self.stats['RWBS'][char] += 1
        for char in action:
            self.stats[char] += 1

        # Parse other
        if 'C' in action:
            (sector, n_sectors) = self.parse_other(True, other)
        elif 'B' in action or 'D' in action or 'I' in action or 'Q' in action or \
            'F' in action or 'G' in action or 'M' in action or 'S' in action:
            (sector, n_sectors) = self.parse_other(False, other)
        else:
            return

        # Add to extents list & update stats with n_sectors
        self.add_extent(sector, n_sectors)
        if 'R' in RWBS:
            self.stats['R_sectors'] += n_sectors
        elif 'W' in RWBS:
            self.stats['W_sectors'] += n_sectors
        return

    def read_btrace(self):
        if self.inproc is not None:
            local_lines = self.read_btrace_process()
        elif self.infile is not None:
            local_lines = self.read_btrace_file()
        else:
            raise Exception('parse_btrace: Unknown btrace input type')
        if local_lines > 0:
            logging.info('read_btrace: lines read = {}'.format(local_lines))
        return local_lines

    def read_btrace_process(self):
        full = True
        local_lines = 0
        while(full):
            try:
                bytes = self.inproc.stdout.readline()
                line = bytes.decode(encoding='ascii').strip('\n\r')
                length = len(line)
                if length > 0:
                    logging.log(5, '{}:{}'.format(self.stats['read_lines'],line))
                    self.stats['read_lines'] += 1
                    local_lines += 1
                    self.parse_btrace(*line.split(None,maxsplit=7))
                else:
                    full = False
            except IOError:
                full = False
        return local_lines

    # exits on EOF
    def read_btrace_file(self):
        local_lines = 0
        for line in self.infile:
            self.parse_btrace(*line.split(None,maxsplit=7))
            self.stats['read_lines'] += 1
            local_lines += 1
        return local_lines

    # Pretty print stats
    def pprint_stats(self):
        pprint.pprint(self.stats)

    ddrescue_status = {'non-tried':'?', 'non-trimmed':'*', 'non-split':'/',
                            'bad-sector':'-', 'finished':'+'}
    def get_status_char(self, status):
        if status in self.ddrescue_status.keys():
            return self.ddrescue_status[status]
        else:
            raise KeyError('Status must be one of: {}'.format(self.ddrescue_status.keys()) )

    header_l1 = '# Rescue Logfile. Created by ddrescue_used ' + constants.version + '\n'
    header_l2 = '# {} Command line: {}\n'
    header_l3 = '# current_pos  current_status\n'
    header_l4 = '0x0000000000   ?\n'
    header_l5 = '#        pos          size  status\n'
    def write_header(self, file_obj):
        file_obj.write(self.header_l1)
        file_obj.write(self.header_l2.format(self.logmagic, ' '.join(sys.argv)))
        file_obj.write(self.header_l3)
        file_obj.write(self.header_l4)
        file_obj.write(self.header_l5)

    def write_extent_line(self, file_obj, start, size, status_char):
        file_obj.write('{:#012X}  {:#012X}  {}\n'.format(start, size, status_char))
        return

    # Note all extents are in bytes rather than sectors
    def write_ddrescuelog(self, options, extent_status, fill_status,
                            sectstart, sectend):
        "Writes a ddrescue log file."
        prev_e = Extent(512 * sectstart, 0)
        fill_char    = self.get_status_char(fill_status)
        extent_char  = self.get_status_char(extent_status)
        filename = helpers.image(options) + self.ddrlog_suffix
        # Overwrite not append to file
        with open(filename,'w') as f:
            self.write_header(f)
            for tup in self.extents:
                e = Extent(512 * tup[0], 512 * tup[1])
                fill_e = Extent(prev_e.next, e.start - prev_e.next)
                if fill_e.n > 0:
                    # FILL
                    self.write_extent_line(f, fill_e.start, fill_e.n, fill_char)
                # EXTENT
                self.write_extent_line(f, e.start, e.n, extent_char)
                prev_e = e
            devend = 512 * sectend
            fill_e = Extent(prev_e.next, devend - prev_e.next)
            if fill_e.n > 0:
                # FILL to the end
                self.write_extent_line(f, fill_e.start, fill_e.n, fill_char)
            f.write('\n')
        self.usedlog = filename
        return filename

