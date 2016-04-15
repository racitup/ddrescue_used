#!/usr/bin/python3
"""
Tries its best to recover and image only used parts of a disk.

##License:
Original work Copyright 2016 Richard Case

Everyone is permitted to copy, distribute and modify this software,
subject to this statement and the copyright notice above being included.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM.
"""
import sys, signal
import os, shutil
import logging, traceback
import btrace, testdisk, pt, ddrescue, helpers, fsmeta, getused
import parse_args, check_deps, constants, clone, diff
from statemachine import State, StateMachine

#TODO: test with lots of images: MBR & GPT, FS combos, PEXL's, errors...

# INIT 1 - cleanup requires OPTIONS
NOT_INSTALLED = check_deps.check()
OPTIONS = parse_args.parse(NOT_INSTALLED)

# EXCEPTION & SIGNAL HANDLERS
SYSEXCEPTHOOK = sys.excepthook
def globalexceptions(typ, value, traceback):
    "Override system exception handler to clean up before exit."
    print('Caught Exception!')
    cleanup()
    SYSEXCEPTHOOK(typ, value, traceback)
sys.excepthook = globalexceptions

def signal_handler(sig, frame):
    "Add signal handler for termination."
    print('Caught signal {}!'.format(sig))
    traceback.print_stack(frame)
    cleanup()
    raise Exception("Signal cleanup!")
signal.signal(signal.SIGHUP,  signal_handler) #1
signal.signal(signal.SIGINT,  signal_handler) #2 or CTRL+C
signal.signal(signal.SIGQUIT, signal_handler) #3
signal.signal(signal.SIGTERM, signal_handler) #15

def cleanup():
    "Clean up on exit."
    ddrescue.stop()
    ddrescue.stop_viewer()
    ddrescue.remove_ddrlog(OPTIONS)
    pt.rmbackup(OPTIONS)
    btrace.stop()

# INIT 2
check_deps.checkroot()
# Initialise the ddrescue xfer log name
ddrescue.set_ddrlog(OPTIONS)
# device size in sectors
DEVSIZE = helpers.get_device_size(OPTIONS.device)
USED = parse_args.check_used(OPTIONS)
manualY = False
# If MetaRescue is interrupted, resume will assume all clones were a success
partinfo = helpers.getpartinfo(OPTIONS.device)
# Start ddrescueview if required
if hasattr(OPTIONS, 'noshow') and OPTIONS.noshow == False:
    ddrescue.start_viewer(OPTIONS)

# STATES
MetaClone = State('Transfer Clonable Metadata',
    "partinfo = clone.clonemeta(OPTIONS, DEVSIZE, partinfo)")
StartBtrace = State('Btrace',
    "btrace.start_bgproc(OPTIONS.device, DEVSIZE); BTRACE_POLL_COUNT = 0")
AddStartEnd = State('Mark Start & End 1Mi Used',
    "btrace.add_used_extent(start=0, size=2048); " +
    "btrace.add_used_extent(size=2048, next=DEVSIZE)")
PTRead = State('Auto TestDisk',
    "ptable = pt.PartitionTable(testdisk.get_list(OPTIONS.device), OPTIONS, DEVSIZE)")
PTAskUser = State('Manual TestDisk?',
    "manualY = testdisk.question_manual(ptable)")
PTManual = State('Manual TestDisk',
    "testdiskrunning = testdisk.manual(OPTIONS)")
PTReadTDLog = State('Read TestDisk Log',
    "ptable.read_testdisk(testdisk.get_log(OPTIONS))")
PTManualRpt = State('Repeat Manual TestDisk',
    "repeatY = testdisk.question_manual(ptable)")
FindMeta = State('Find FS Metadata RO',
    "findmetarunning = fsmeta.scanmeta_running(OPTIONS, OPTIONS.device, ptable, 'ro', partinfo)")
BtraceWait = State('Wait 0.3s',
    "BTRACE_POLL_COUNT = 0")
CloseBtrace = State('Stop Btrace',
    "btrace.stop()")
OutputBtraceStats = State('Btrace Stats',
    "btrace.parser.pprint_stats()")
MetaRescue = State('DDrescue PT & FSs',
    "ddrrunning = ddrescue.interactive(OPTIONS)")
PTResume = State('Read PT after Resume',
    "ptable = pt.PartitionTable(testdisk.get_list(OPTIONS.device), OPTIONS, DEVSIZE)")
PTRepair = State('Testdisk Repair Image PT',
    "testdiskrunning = testdisk.manual(OPTIONS, 'image')")
FixImgRW = State('Repair Image Using FSCK',
    "fixmetarunning = fsmeta.fixmeta_image_running(OPTIONS, ptable)")
MapExtents = State('Clone and/or Find Used Space',
    "mapper = getused.MapExtents(OPTIONS, DEVSIZE); partinfo = mapper.map(partinfo, USED)")
DataRescue = State('DDrescue Used Space',
    "ddrrunning = ddrescue.interactive(OPTIONS)")
DiffFS = State('Diff Corresponding Device and Image FSs',
    "diff.difffs(OPTIONS, partinfo)")

# TRANSITIONS
MetaClone.add_transition(StartBtrace,
    condition='True')
StartBtrace.add_transition(AddStartEnd,
    condition="BTRACE_POLL_COUNT >= 3")
AddStartEnd.add_transition(PTRead,
    condition='True')
PTRead.add_transition(PTAskUser,
    condition='ptable.healthflags',
    actions="ptable.write_testdisk('AutoBad')")
PTRead.add_transition(FindMeta,
    condition='not ptable.healthflags',
    actions="ptable.write_testdisk('AutoGood')")
PTAskUser.add_transition(PTManual,
    condition='True == manualY',
    actions="testdisk.instruct_user()")
PTAskUser.add_transition(FindMeta,
    condition='False == manualY')
PTManual.add_transition(PTReadTDLog,
    condition='not next(testdiskrunning, False)')
PTReadTDLog.add_transition(PTManualRpt,
    condition='ptable.healthflags')
PTReadTDLog.add_transition(FindMeta,
    condition='not ptable.healthflags',
    actions="ptable.write_testdisk('Repaired')")
PTManualRpt.add_transition(PTManual,
    condition='True == repeatY',
    actions="ptable.clear(); testdisk.removelog(OPTIONS)")
PTManualRpt.add_transition(FindMeta,
    condition='False == repeatY',
    actions="ptable.write_testdisk('RepairFail')")
FindMeta.add_transition(BtraceWait,
    condition='not next(findmetarunning, False)')
BtraceWait.add_transition(CloseBtrace,
    condition='BTRACE_POLL_COUNT >= 3')
CloseBtrace.add_transition(OutputBtraceStats,
    condition="btrace.blkparse.poll() is not None and OPTIONS.stats",
    actions="btrace.blkparse = None; btrace.movelog(OPTIONS)")
CloseBtrace.add_transition(MetaRescue,
    condition="btrace.blkparse.poll() is not None and not OPTIONS.stats",
    actions="btrace.blkparse = None; btrace.movelog(OPTIONS)")
OutputBtraceStats.add_transition(MetaRescue,
    condition="True")
MetaRescue.add_transition(FixImgRW,
    condition="not next(ddrrunning, False) and not manualY and not resumed")
MetaRescue.add_transition(PTResume,
    condition="not next(ddrrunning, False) and not manualY and resumed")
PTResume.add_transition(FixImgRW,
    condition="True")
MetaRescue.add_transition(PTRepair,
    condition="not next(ddrrunning, False) and manualY",
    actions="testdisk.repair_instructions()")
PTRepair.add_transition(FixImgRW,
    condition="not next(testdiskrunning, False)",
    actions="ptable = pt.PartitionTable(testdisk.get_list(OPTIONS.device), OPTIONS, DEVSIZE)")
FixImgRW.add_transition(MapExtents,
    condition="not next(fixmetarunning, False)")
MapExtents.add_transition(DataRescue,
    condition="True")
DataRescue.add_transition(DiffFS,
    condition="not next(ddrrunning, False) and OPTIONS.diff")
DataRescue.add_transition(None,
    condition="not next(ddrrunning, False) and not OPTIONS.diff")
DiffFS.add_transition(None,
    condition="True")

# RESUME
def resumable(options):
    "Check to see if ddrescue log files exist and they indicate a resumable state."
    imgfile = helpers.image(options)
    ddrlog = imgfile + ddrescue.ddrlog_suffix
    btracelog = imgfile + btrace.BtraceParser.ddrlog_suffix
    usedlog = imgfile + getused.MapExtents.ddrlog_suffix
    if os.path.isfile(ddrlog) and os.stat(ddrlog).st_size > 0:
        if (os.path.isfile(usedlog) and
                helpers.grep(usedlog, 'ddrescue_used') and
                helpers.grep(usedlog, getused.MapExtents.logmagic)):
            return 'data'
        elif (os.path.isfile(btracelog) and
                helpers.grep(btracelog, 'ddrescue_used') and
                helpers.grep(btracelog, btrace.BtraceParser.logmagic)):
            return 'meta'
        else:
            raise Exception('Non-resumable state. Use {} in ddrescue directly or remove it.'
                                .format(ddrlog))
    else:
        return None

statetag = resumable(OPTIONS)
resumed = False
if 'data' == statetag:
    startstate = DataRescue
    resumed = True
    logging.info("Resuming at Data Rescue...")
elif 'meta' == statetag:
    startstate = MetaRescue
    resumed = True
    logging.info("Resuming at Metadata Rescue...")
else:
    startstate = MetaClone

# STATEMACHINE
sm = StateMachine(0.1, startstate, globals(), locals())

BTRACE_POLL_COUNT = 0
def btrace_poller(smobj):
    global BTRACE_POLL_COUNT
    if btrace.blkparse is not None and btrace.parser is not None:
        lines_read = btrace.parser.read_btrace()
        BTRACE_POLL_COUNT += 1
        if lines_read > 0:
            # unused are marked finished so when ANDed using ddrescuelog
            # only definitely unused parts remain finished
            btracelog = btrace.parser.write_ddrescuelog(OPTIONS,
                'non-tried', 'finished', 0, DEVSIZE)
            if ddrescue.VIEWER is not None:
                shutil.copyfile(btracelog, ddrescue.ddrlog)
sm.add_persistent_task(btrace_poller)

# EXECUTE
sm.run()

# CLEANUP BEFORE NORMAL EXIT
cleanup()

