"""
Helper functions for running TestDisk.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import os
import helpers

# For debugging: import pdb; pdb.set_trace() # DEBUG

def repair_instructions():
    "Blocking: How to write a repaired partition table with testdisk."
    instructions = """In TestDisk perform the following:
1. Press [Enter] on the Drive.
2. Press [Enter] on the selected partition table type.
3. Press [Enter] on [Analyse].
4. Press [Enter] on [Quick Search].
5. Press [L] to load a backup partition table. If in doubt choose the latest
   one (the timestamp is at the end).
6. Navigate Up/Down the partitions. Press [P] for each one you need to recover
   If files are listed, navigate as much of the filesystem as possible using the
   Up/Down/Left/Right keys. This gives us a map of the filesystem sectors.
   Press [Q] when complete and continue with other filesystems.
   NOTE: You should NOT copy files at this stage, the file data has not been
   copied to the image so copied files will be filled with zeros!
7. Using Left/Right mark each partition so it goes Green.
   TestDisk may only let you mark some of them Green. Pick the most
   important ones and those that show files when you press [P].
   Press [Enter] when Structure: says 'Ok'.
8. Now choose [Write]. Since we are operating on an image there is no danger to
   damaging your drive, though your partitions may become inaccessible if you
   get it wrong! Press [Y] to confirm or [N] to abort.
9. Choose [Quit] [Quit] [Quit] to exit.\n
   Press [Enter] when ready."""

    print(instructions)
    input('--> ')

def instruct_user():
    "Blocking call: How to recover a partition table with testdisk."
    instructions = """In TestDisk perform the following:
1. Press [Enter] on the Drive.
2. Press [Enter] on the selected partition table type.
3. Press [Enter] on [Analyse].
4. Press [Enter] on [Quick Search].
5. Navigate Up/Down the partitions. Press [P] for each one you need to recover
   If files are listed, navigate as much of the filesystem as possible using the
   Up/Down/Left/Right keys. This gives us a map of the filesystem sectors.
   Press [Q] when complete and continue with other filesystems.
6. Using Left/Right mark each partition so it goes Green.
   TestDisk will probably only let you mark some of them Green. Pick the most
   important ones and those that show files when you press [P].
   Press [Enter] when Structure: says 'Ok'.
7. DO NOT CHOOSE THE [WRITE] OPTION. This could cause damage to your drive.
   If your filesystems were not listed, continue with a [Deeper Search]
   and repeat the process above. If your disk has been reformatted or
   partitioned several times, there could be a lot of bogus entries.
8. Again DO NOT CHOOSE THE [WRITE] OPTION. We will use the log output later.
9. Choose [Quit] [Quit] [Quit] to exit.\n
   Press [Enter] when ready."""

    print(instructions)
    input('--> ')

def question_manual(ptable):
    "Blocking call: Get a user decision on whether to dig deeper into the PT."
    message = 'You have been given this message because:\n'
    for reason in ptable.gethealthflagsreasons():
        message += ' - ' + reason + '\n'
    question = """
Please enter Y/N whether you would like to manually try to recover more of the
partition table using TestDisk?
NOTE: You can load previous partition table backups in TestDisk using [L].
Press [Enter] after your selection.
"""
    print(message + question)
    while(True):
        chars = input('--> ')
        lower_chars = chars.strip('\n\r').lower()
        if len(lower_chars) == 1:
            if lower_chars == 'y':
                return True
            elif lower_chars == 'n':
                return False

def manual(options, target='device'):
    "Run manual TestDisk"
    removelog(options)
    if target == 'device':
        arg = [options.device]
    else:
        arg = [options.image_filename]
    cmd = ['testdisk', '/log'] + arg
    for proc in helpers.generator_context_switch(cmd, options.dest_directory):
        # Run the process until it exits
        yield proc.returncode is None
    return

def get_list(device):
    "Get testdisk PT dump from stdout."
    return helpers.get_procoutput(['testdisk', '/list', device], prunelog=False)[1]

LOGFILE = 'testdisk.log'
def logpath(dest):
    "Get the path to the testdisk log."
    return os.path.join(dest, LOGFILE)

def removelog(options):
    logp = logpath(options.dest_directory)
    helpers.removefile(logp)

def get_log(options):
    """Get testdisk PT dump from log file.

    If interface_write() at the end only load following PT, otherwise whole file.
    """
    with open(logpath(options.dest_directory), 'r') as logfd:
        log = logfd.read()
    if not options.keeplogs:
        # Remove logfile
        removelog(options)
    parts = log.rpartition('interface_write()')
    if len(parts[2]) > 0:
        return parts[2]
    else:
        return log

