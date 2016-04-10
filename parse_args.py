"""
Parse the tool commandline arguments.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import argparse
import constants
import os
import sys
import stat
import logging
import helpers

def writable_dir(dirpath):
    "Check to see if the destination is a directory and writable."
    if not os.path.isdir(dirpath):
        raise argparse.ArgumentTypeError('{} is not a directory'
                                            .format(dirpath))
    if os.access(dirpath, os.W_OK):
        return dirpath
    else:
        raise argparse.ArgumentTypeError('{} is not writable'
                                            .format(dirpath))

def readable_blockfile(filepath):
    "Check to see if device is a block special and readable."
    mode = os.stat(filepath).st_mode
    if not stat.S_ISBLK(mode):
        raise argparse.ArgumentTypeError('{} is not a block special device'
                                            .format(filepath))
    if os.access(filepath, os.R_OK):
        return filepath
    else:
        raise argparse.ArgumentTypeError('{} is not readable'
                                            .format(filepath))

def check_used(options):
    "Checks the --used and --free switches. Returns True, False or None."
    if options.used == True and options.free == True:
        raise argparse.ArgumentTypeError('--used and --free are mutually exclusive.')
    elif options.used == True:
        return True
    elif options.free == True:
        return False
    else:
        return None

options = None
def parse(not_installed):
    "Parse commandline arguments."
    global options
    parser = argparse.ArgumentParser(
        description="""
ddrescue/testdisk-based tool that creates a disk image containing only the used
parts of a disk.
If available, the clone/image application is first tried for the following
filesystems: ext*, btrfs, ntfs & xfs.
Otherwise the tool will attempt to repair partition table errors and filesystem
errors on the image interactively to be able to find the used parts.
Used space is found in one of two ways: the -f switch maps the free space on an
image copy and assumes the intervening space is used, the -u switch maps the
used space directly by walking all files and directories. -f is recommended if
you have the time and disk space required since it is the more robust approach.
Finding free space on certain filesystems (e.g. ext2, ext3 & ntfs) can use a lot
of time and disk space since the only way is to physically write to the blocks.
If neither switch is specified a hybrid approach is used: for the filesystems
listed above -u is used, for all others -f is used.
""", epilog="""
This tool will NEVER write to the source device.
Please ensure partitions are not already mounted.
Does not support btrfs volumes with multiple partitions; this will cause errors.
If recovery disk space is limited, use a compressed filesystem that supports
sparse files as destination, such as btrfs.
Example usage:
  mkdir ~/diskrecovery/
  mount         # and check output for sdb entries; umount if necessary
  sudo ddrescue_used -vkf /dev/sdb sdb.img ~/diskrecovery/
""", formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('device', type=readable_blockfile,
        help='the input block device file to rescue')
    parser.add_argument('image_filename',
        help='output image filename')
    parser.add_argument('dest_directory', type=writable_dir,
        help='destination directory for all output files')
    parser.add_argument('--unaccounted', '-a', type=int, default=1000000,
        help='the maximum number of 512B sectors that you will allow outside a filesystem partition, default 1M')
    parser.add_argument('--diff', '-d', action='store_true', default=False,
        help='diff the corresponding device and image filesystems after transfer to stdout. Not recommended for failing source drives')
    parser.add_argument('--stats', '-s', action='store_true', default=False,
        help='print statistics from the btrace parsing that captures metadata blocks')
    parser.add_argument('--used', '-u', action='store_true', default=False,
        help='force used space to be mapped directly by walking the filesystem')
    parser.add_argument('--free', '-f', action='store_true', default=False,
        help='force used space to be mapped indirectly by allocating free space')
    parser.add_argument('--keeplogs', '-k', action='store_true', default=False,
        help='keep all the logs generated; also makes the ddrescue stages resumable')
    parser.add_argument('--version', action='version',
        version=constants.version, help='prints the version and exits')
    parser.add_argument('--verbose', '-v', action='count', default=0,
        help='use multiple times to increase stderr verbosity, -vvv should be redirected to file')
    if 'ddrescueview' not in not_installed:
        parser.add_argument('--noshow', '-n', action='store_true', default=False,
            help='do not pop up ddrescueview to visualise progress')

    options = parser.parse_args()
    # Should be called before any actual logging
    reset_logging_config()
    logging.debug('parse_args: {}'.format(options))
    return options

def reset_logging_config():
    "Set logging level, default WARNING."
    rootLogger = logging.getLogger()
    for handler in rootLogger.handlers:
        rootLogger.removeHandler(handler)

    kwargs = {'format':'{levelname}:{module}:{message}',
                'style':'{', 'stream':sys.stderr}
    if options.verbose == 1:
        logging.basicConfig(level=logging.INFO, **kwargs)
    elif options.verbose == 2:
        logging.basicConfig(level=logging.DEBUG, **kwargs)
    elif options.verbose > 2:
        logging.basicConfig(level=0, **kwargs)
    else:
        logging.basicConfig(level=logging.WARNING, **kwargs)
    logging.addLevelName(5, 'EXTRA')
    rootLogger.addFilter(repeat_logfilter)
    return

PREV_MSG = None
PREV_COUNT = 0
def repeat_logfilter(record):
    "Withold repeat log messages and output number of repeats before next msg."
    global PREV_MSG, PREV_COUNT
    pmsg, pcount = PREV_MSG, PREV_COUNT
    msg = record.getMessage()
    if msg == pmsg:
        PREV_COUNT += 1
        return 0
    else:
        PREV_COUNT = 0
        if pcount > 0:
            logging.debug('Previous message repeated {} times'.format(pcount))
        PREV_MSG = msg
        return 1

