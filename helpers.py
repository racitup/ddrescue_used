"""
Tool helpers.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import subprocess
import signal
import os, io, sys, time, re
import logging
import parse_args
import random, string
from contextlib import contextmanager

@contextmanager
def ImageCopy(options):
    "Uses cp command to preserve sparse files. Python shutil does not do this."
    source = image(options)
    dest = randpath(options, 'img.')
    if os.path.exists(dest):
        raise Exception('{} exists!'.format(dest))
    cmd = ['cp', '--sparse=always', source, dest]
    proc = get_procoutput(cmd)[0]
    try:
        yield dest
    finally:
        os.remove(dest)

@contextmanager
def MountPoint(options):
    "Generates a unique mountpoint and cleans up afterward."
    mnt = randpath(options, 'mnt.')
    os.mkdir(mnt)
    try:
        yield mnt
    finally:
        os.rmdir(mnt)

@contextmanager
def Mount(device, mnt, mode=None):
    "Mounts and unmounts a device with required permissions."
    cmd = ['mount', '-o']
    if mode is 'rw':
        cmd += ['rw']
    else:
        cmd += ['ro,noexec']
    cmd.extend([device, mnt])
    proc = get_procoutput(cmd, log=False)[0]
    if proc.returncode != 0:
        raise OSError(proc.returncode, STRERROR, device, None, mnt)
    try:
        yield mnt
    finally:
        count = 3
        while True:
            proc = get_procoutput(['umount', mnt])[0]
            if proc.returncode == 0:
                break
            elif count > 0:
                count -= 1
                time.sleep(0.1)
            else:
                raise OSError(proc.returncode, STRERROR, mnt)

@contextmanager
def AttachLoop(source, mode, partn=None):
    "Context Manager for attaching a loop device to a partition or file."
    loop = get_freeloop()
    # flushbufs & rereadpt added to fix incorrect filesystem detected on
    # loop device reuse - fixed
    get_procoutput(['blockdev', '--flushbufs', loop])
    if partn is None:
        cmd = ['losetup']
    else:
        cmd = ['losetup', '--offset', str(partn['SStart']*512),
               '--sizelimit', str(partn['Size']*512)]
    if mode != 'rw':
        cmd.append('--read-only')
    cmd.extend([loop, source])
    get_procoutput(cmd)
    if partn is None:
        rereadpt(loop)
    try:
        yield loop
    finally:
        get_procoutput(['losetup', '--detach', loop])
        rereadpt(loop)

def rereadpt(loop):
    "Reread the partition table from a block device. Can get device busy error."
    count = 3
    while True:
        proc = get_procoutput(['blockdev', '--rereadpt', loop])[0]
        if proc.returncode == 0:
            break
        elif count > 0:
            count -= 1
            time.sleep(0.1)
        else:
            raise OSError(proc.returncode, STRERROR, loop)

def randpath(options, prefix):
    "Returns a random destination path."
    return os.path.join(options.dest_directory, prefix + randstring8())

def randstring8():
    "Returns a length8 pseudorandom string to use as a temporary file or path."
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(8))

def fswalk(options, device):
    "Generator for mounting and walking a filesystem ro, returning file/dir paths."
    with MountPoint(options) as mnt:
        with Mount(device, mnt):
            for path in getfile(mnt):
                yield path

def getfile(mnt):
    "Generator for getting individual filesystem elements (files/dirs)."
    for dirpath, dirs, files in os.walk(mnt):
        for name in files:
            yield os.path.join(dirpath, name)
        for name in dirs:
            yield os.path.join(dirpath, name)

def getparts(looppath):
    """Get the list of subdevices for each partition detected in a block device.

    List of 3-tuples sorted by start sector: (path, start sector, size in sectors)
    """
    loopname = os.path.split(looppath)[1]
    genloopsub = (n for n in os.listdir('/dev/') if loopname in n and loopname != n)
    tuplist = []
    for loopsub in genloopsub:
        loopsubpath = os.path.join('/dev/', loopsub)
        loopsubsysstartpath = os.path.join('/sys/class/block/', loopsub, 'start')
        with open(loopsubsysstartpath, 'r') as f:
            start = int(f.read())
        size = get_device_size(loopsubpath)
        tuplist.append( (loopsubpath, start, size) )
    tuplist.sort(key=lambda tup: tup[1])
    return tuplist

def get_device_size(devpath):
    "Returns the size in sectors of a device from the sysfs."
    devname = os.path.split(devpath)[1]
    devsyssizepath = os.path.join('/sys/class/block/', devname, 'size')
    with open(devsyssizepath, 'r') as f:
        size = int(f.read())
    return size

def get_freeloop():
    "Returns the next free loop device string."
    return get_procoutput(['losetup', '--find'])[1]

def grep(log, text):
    "Quick grep for text in log, returns True if found."
    with open(log, 'r') as fdesc:
        for line in fdesc:
            if re.search(text, line):
                return True
    return False

def image(options):
    "Returns the image path."
    return os.path.join(options.dest_directory, options.image_filename)

def removefile(path):
    "Removes a file ignoring non-existent error."
    try:
        os.remove(path)
    except FileNotFoundError:
        pass

def cmd_str(cmd):
    "Returns a printable version of a command."
    if isinstance(cmd, str):
        return cmd
    elif isinstance(cmd, list):
        return ' '.join(cmd)
    else:
        raise Exception('Unknown cmd structure!')

def cmdlog(bulk, ret):
    "Logs command output at appropriate level according to returncode."
    if ret == 0:
        logging.debug(bulk)
    else:
        bulk += ', RETURNCODE={}'.format(ret)
        logging.info(bulk)

STRERROR = None
def get_procoutput(cmd, cwd=None, shell=False, log=True, prunelog=True):
    "Runs a subprocess and returns (process object, stdout) tuple."
    global STRERROR
    proc = subprocess.Popen(cmd, cwd=cwd, shell=shell,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (stdout, stderr) = proc.communicate()
    out = stdout.decode('utf-8').strip()
    err = stderr.decode('utf-8').strip()
    STRERROR = err
    if log:
        lines = out.splitlines()
        if prunelog and len(lines) > 12:
            topbottom = lines[:8] + ['...'] + lines[-4:]
            debstr = '\n'.join(topbottom)
        else:
            debstr = out
        cmdlog('exe: cmd={}, out={}, err={}'.format(cmd_str(cmd), debstr, err),
                                proc.returncode)
    return (proc, out)

def checkgcscmd(cmd):
    "Helper for context switches."
    for proc in generator_context_switch(cmd):
        time.sleep(0.1)
    if proc.returncode != 0 or proc.returncode is None:
        logging.error('Problem during command: {}'
                .format(cmd_str(cmd)))
        return False
    return True

def generator_context_switch(cmd, cwd=None):
    "Uses yield to save app context, switch shell to subprocess and switch back when subprocess exits."
    old_stds = (sys.stdin, sys.stdout, sys.stderr)
    with open(os.devnull, "r") as sys.stdin:
        with io.StringIO() as sys.stdout:
            with io.StringIO() as sys.stderr:
            # DEBUG context switcher:
            #with open("debug_context.log", "a", encoding="utf-8") as sys.stderr:
                parse_args.reset_logging_config()
                proc = subprocess.Popen(cmd, cwd=cwd,
                    stdin=old_stds[0], stdout=old_stds[1], stderr=old_stds[2])
                # Ensure we yield proc at least once
                yield proc
                while(proc.poll() == None):
                    yield proc
                cmdlog('gcs: cmd={}'.format(cmd_str(cmd)), proc.returncode)
                # Play out stdout and stderr StringIOs
                old_stds[2].write(sys.stderr.getvalue())
            old_stds[1].write(sys.stdout.getvalue())
    # Put environment back
    sys.stdin = old_stds[0]
    sys.stdout = old_stds[1]
    sys.stderr = old_stds[2]
    # Must be after sys.stderr is assigned
    parse_args.reset_logging_config()
    return

def get_process_cmd(proc):
    "Get linux command of pid from the OS."
    filepath = '/proc/' + str(proc.pid) + '/cmdline'
    if os.access(filepath, os.R_OK):
        with open(filepath,'r') as f:
            cmd = f.readline()
        # cmd arguments are separated by NUL characters:
        cmd = cmd.replace('\0',' ')
    else:
        cmd = filepath
    cmd = str(proc.pid) + '=' + cmd
    return cmd

def ctrlc_process(proc):
    "Politely kill a process with CTRL-C/SIGINT(2)."
    if proc is not None:
        if proc.poll() is None:
            return proc.send_signal(signal.SIGINT)
    return 0

