"""
ddrescue helpers.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import subprocess
import logging
import helpers
import os, shutil
from shlex import quote

ddrlog_suffix = '.xfer.log'
ddrlog = None

DDRESCUE = None

# Uses sparse and direct options
# CTRL-C to kill
def interactive(options, args=[]):
    global DDRESCUE
    image = helpers.image(options)
    cmd = ['ddrescue', '-S', '-d']
    cmd.extend(args)
    cmd.extend([options.device, image, ddrlog])
    for DDRESCUE in helpers.generator_context_switch(cmd):
        # Run the process until it exits
        yield DDRESCUE.returncode is None
    DDRESCUE = None

def stop():
    global DDRESCUE
    ddr = DDRESCUE
    DDRESCUE = None
    helpers.ctrlc_process(ddr)
    return ddr

def set_ddrlog(options):
    "Set ddrescue log if it doesn't exist."
    global ddrlog
    if ddrlog is None:
        ddrlog = helpers.image(options) + ddrlog_suffix
    # Create an empty file if it doesn't exist
    if not os.path.isfile(ddrlog):
        with open(ddrlog, 'w') as fd_log:
            pass
    return ddrlog

def remove_ddrlog(options):
    "Removes the log if finished."
    if ddrlog is not None and not options.keeplogs:
        helpers.removefile(ddrlog)

# ddrescuelog command output
def logcmd(options, cmd, prefix=''):
    """Runs a ddrescuelog shell command.

    Substitutes {0} with ddrlog in the command and overwrites ddrlog with the
    result.
    """
    tmpfile = helpers.randpath(options, 'tmp.')
    fullcmd = (cmd + ' > {1}').format(quote(ddrlog), quote(tmpfile))
    proc = helpers.get_procoutput(fullcmd, shell=True)[0]
    if proc.returncode != 0:
        raise Exception('ddrescuelog failed!')
    if options.keeplogs:
        shutil.copyfile(tmpfile, ddrlog)
    else:
        shutil.move(tmpfile, ddrlog)

# Start ddrescueview
VIEWER = None
def start_viewer(options):
    global VIEWER
    VIEWER = subprocess.Popen(['ddrescueview', ddrlog],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    logging.debug('ddrescueview: {}'.format(helpers.get_process_cmd(VIEWER)))
    return VIEWER

def stop_viewer():
    global VIEWER
    vwr = VIEWER
    VIEWER = None
    helpers.ctrlc_process(vwr)
    return vwr

